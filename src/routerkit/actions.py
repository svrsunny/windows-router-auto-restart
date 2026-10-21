"""High-level operations shared by the CLI, the scheduled task and the dashboard."""
from __future__ import annotations

import logging
import os
import socket
import time
from typing import Callable

from . import credentials, events, net
from .config import DATA, Config, ensure_dirs
from .routers import RouterError, SessionBusyError, get_adapter
from .routers.base import AuthError
from .util import dur

log = logging.getLogger(__name__)

# exit codes (also shown as the scheduled task's "Last Run Result")
OK, FAILED, NO_PASSWORD, NOT_VERIFIED, BLOCKED = 0, 1, 2, 3, 4
LOCK_FILE = DATA / "restart.lock"
LOCK_STALE = 20 * 60
Progress = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


# ---------- duplicate-restart protection ----------

class RestartLock:
    """Cross-process lock so the dashboard and the scheduled task can never send two restart
    requests at once. A lock older than LOCK_STALE (crashed process) is taken over."""

    def __init__(self, path=None):
        self.path = path or LOCK_FILE
        self.held = False

    def acquire(self) -> bool:
        ensure_dirs()
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {time.time():.0f}".encode())
                os.close(fd)
                self.held = True
                return True
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > LOCK_STALE:
                        self.path.unlink()
                        continue
                except OSError:
                    continue
                return False
        return False

    def release(self) -> None:
        if self.held:
            self.path.unlink(missing_ok=True)
            self.held = False


def recent_restart(cfg: Config, now: float | None = None) -> float | None:
    """Time of a successful restart within the cooldown window, else None."""
    if cfg.reboot_cooldown_minutes <= 0:
        return None
    now = now or time.time()
    lr = events.last_reboot(events.read_events(since=now - cfg.reboot_cooldown_minutes * 60))
    return lr if lr and now - lr < cfg.reboot_cooldown_minutes * 60 else None


# ---------- restart / login test ----------

def run_reboot(cfg: Config, dry_run: bool = False, wait: bool = True, progress: Progress = _noop,
               force: bool = False, session=None) -> int:
    """Log in and restart (or only log in when dry_run).

    Returns OK, FAILED, NO_PASSWORD, NOT_VERIFIED (request sent but the router was not seen going
    down and coming back) or BLOCKED (another restart is running or one just happened).
    The restart request itself is sent at most once per call.
    """
    kind = "login_test" if dry_run else "reboot"
    password, _source = credentials.get_password()
    if not password:
        log.error("no router password stored - run scripts\\Configure.ps1 (or routerctl.py set-password)")
        events.record(kind, ok=False, detail="no password")
        return NO_PASSWORD
    events.protect(password)

    lock = RestartLock()
    if not dry_run:
        lr = None if force else recent_restart(cfg)
        if lr:
            log.warning("restart refused: the router was already restarted %s ago "
                        "(cooldown %g min; use --force to override)", dur(time.time() - lr),
                        cfg.reboot_cooldown_minutes)
            events.record(kind, ok=False, detail="cooldown")
            return BLOCKED
        if not lock.acquire():
            log.warning("restart refused: another restart is already in progress")
            events.record(kind, ok=False, detail="already running")
            return BLOCKED
    try:
        try:
            with get_adapter(cfg, password, session=session) as rc:
                progress("Logging in to the router...")
                rc.login()
                log.info("logged in")
                if dry_run:
                    log.info("dry run: not restarting")
                    events.record(kind, ok=True)
                    return OK
                progress("Sending restart request...")
                rc.reboot()
            sent = time.time()
            events.record(kind, ok=True)
        except SessionBusyError as e:
            log.error("%s", e)
            events.record(kind, ok=False, detail="admin session busy")
            return FAILED
        except AuthError as e:
            log.error("%s", e)
            events.record(kind, ok=False, detail="login rejected")
            return FAILED
        except RouterError as e:
            log.error("%s", e)
            events.record(kind, ok=False, detail=str(e)[:200])
            return FAILED
        except Exception as e:  # noqa: BLE001
            log.exception("unexpected error")
            events.record(kind, ok=False, detail=type(e).__name__)
            return FAILED
        if wait and cfg.reboot_wait_seconds > 0:
            status = wait_for_return(cfg, sent, progress)
            return OK if status == "recovered" else NOT_VERIFIED
        return OK
    finally:
        lock.release()


def wait_for_return(cfg: Config, sent: float, progress: Progress = _noop, sleep=time.sleep,
                    clock=time.time) -> str:
    """Follow the router through its restart. Never sends anything to the router.

    Returns 'recovered', 'not_down' (router kept answering: the restart may not have happened),
    'router_not_back' or 'internet_not_back'.
    """
    progress("Waiting for the router to go down...")
    went_down = False
    while clock() < sent + 60:
        if not net.router_up(cfg, 1.0):
            went_down = True
            break
        sleep(1)
    if not went_down:
        log.warning("router still answering 60 s after the restart request - it may not have restarted")
        events.record("reboot_recovered", ok=False, status="not_down", router_s=None, internet_s=None)
        return "not_down"
    progress("Router is restarting...")
    router_back = None
    while clock() < sent + cfg.reboot_wait_seconds:
        if net.router_up(cfg, 1.0):
            router_back = clock()
            break
        sleep(1)
    if router_back is None:
        log.warning("router not back %s after the restart request", dur(cfg.reboot_wait_seconds))
        events.record("reboot_recovered", ok=False, status="router_not_back", router_s=None, internet_s=None)
        return "router_not_back"
    log.info("router back online after %s", dur(router_back - sent))
    progress(f"Router is back after {dur(router_back - sent)} - waiting for the internet...")
    internet_back = None
    while clock() < router_back + 180:
        if net.probe(cfg).internet_up:
            internet_back = clock()
            break
        sleep(2)
    if internet_back is None:
        log.warning("internet not back 3 min after the router came up")
        status = "internet_not_back"
    else:
        log.info("internet back after %s", dur(internet_back - sent))
        status = "recovered"
    events.record("reboot_recovered", ok=internet_back is not None, status=status,
                  router_s=round(router_back - sent, 1),
                  internet_s=round(internet_back - sent, 1) if internet_back else None)
    return status


# ---------- diagnostics (never restarts anything) ----------

def test_connection(cfg: Config, login: bool = True, out: Callable[[str], None] = print, session=None) -> int:
    """Step-by-step check: TCP, login page, optional login+logout, internet, DNS."""
    ok = True

    def step(name: str, passed: bool | None, detail: str = "") -> None:
        nonlocal ok
        mark = {True: "[ OK ]", False: "[FAIL]", None: "[SKIP]"}[passed]
        out(f"{mark} {name}" + (f" - {detail}" if detail else ""))
        if passed is False:
            ok = False

    ms = net.tcp_ping(cfg.router_host, cfg.router_port, max(1.0, min(cfg.request_timeout, 5)))
    step(f"Router reachable at {cfg.router_host}:{cfg.router_port}", ms is not None,
         f"{ms:.0f} ms" if ms is not None else "no TCP connection (wrong address, or not on this network?)")
    if ms is None:
        return FAILED
    password, source = credentials.get_password()
    events.protect(password)
    adapter = get_adapter(cfg, password or "", session=session)
    try:
        step("Router web interface", True, adapter.check())
    except RouterError as e:
        step("Router web interface", False, str(e))
        adapter.session.close()
        return FAILED
    if not login:
        step("Login test", None, "skipped")
        adapter.session.close()
    elif not password:
        step("Password stored", False, "run scripts\\Configure.ps1 to store it")
        adapter.session.close()
    else:
        step("Password stored", True, source)
        try:
            with adapter:
                adapter.login()
            step("Login and logout (no restart)", True)
            events.record("login_test", ok=True)
        except RouterError as e:
            step("Login and logout (no restart)", False, str(e))
            events.record("login_test", ok=False, detail=type(e).__name__)
    pr = net.probe(cfg)
    step("Internet reachable", pr.internet_up,
         f"{pr.internet_ms:.0f} ms" if pr.internet_ms is not None else "no probe target answered")
    try:
        socket.getaddrinfo(cfg.dns_check_host, 443)
        step(f"DNS resolves {cfg.dns_check_host}", True)
    except OSError as e:
        step(f"DNS resolves {cfg.dns_check_host}", False, str(e))
    out("")
    out("All checks passed. This does not prove a restart will work - only a real restart can." if ok
        else "Some checks failed - see docs/troubleshooting.md.")
    return OK if ok else FAILED
