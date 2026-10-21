"""Internet watchdog: a quiet background process that pops up a warning when the router is
reachable but the internet is down, and records every outage for the dashboard's uptime bar.
"""
from __future__ import annotations

import logging
import queue
import socket
import subprocess
import threading
import time
import tkinter as tk

from . import events, net
from .config import CLI, ICON, ROOT, Config
from .monitor import Monitor
from .util import clock, dur

log = logging.getLogger(__name__)

LOCK_PORT = 47655          # localhost only; also lets the dashboard see that a watchdog is running
INTERVAL = 5.0             # seconds between checks while all is well
FAST_INTERVAL = 3.0        # while an outage is being confirmed


# ---------- single instance + liveness ----------

def acquire_lock() -> socket.socket | None:
    """Listen on a local port: a second watchdog fails to bind and exits, and the dashboard can
    connect to it to see that a watchdog is running."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(4)
    except OSError:
        s.close()
        return None

    def serve():
        while True:
            try:
                conn, _ = s.accept()
                conn.close()
            except OSError:
                return
    threading.Thread(target=serve, daemon=True, name="lock").start()
    return s


def is_running(timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", LOCK_PORT), timeout):
            return True
    except OSError:
        return False


class LastReboot:
    """events.last_reboot(), re-read only when the events file changes."""

    def __init__(self):
        self.mtime, self.value = None, None

    def __call__(self) -> float | None:
        try:
            m = events.EVENTS_FILE.stat().st_mtime
        except OSError:
            return self.value
        if m != self.mtime:
            self.mtime = m
            self.value = events.last_reboot(events.read_events(since=time.time() - 86400))
        return self.value


# ---------- main loop ----------

class Watchdog:
    def __init__(self, root: tk.Tk, cfg: Config, ui, demo: bool = False):
        from .ui.popup import Popup
        self.root, self.cfg = root, cfg
        self.q: queue.Queue = queue.Queue()
        self.monitor = Monitor()
        self.last_reboot = LastReboot()
        self.popup = Popup(root, ui, open_dashboard=self.open_dashboard)
        root.after(200, self.drain)
        if demo:
            now = time.time()
            root.after(300, lambda: self.popup.show_down(now - 12))
            root.after(8000, lambda: self.popup.show_back(now - 12, time.time() + 135))
            root.after(22000, root.destroy)
        else:
            threading.Thread(target=self.probe_loop, daemon=True, name="probe").start()
            log.info("watchdog started")

    def open_dashboard(self):
        from .scheduler import NO_WINDOW, pythonw
        try:
            subprocess.Popen([pythonw(), str(CLI), "dashboard"], cwd=str(ROOT), creationflags=NO_WINDOW)
        except OSError as e:
            log.warning("could not open the dashboard: %s", e)
        self.popup.dismiss()

    def probe_loop(self):
        mon = self.monitor
        while True:
            try:
                pr = net.probe(self.cfg)
                for ev in mon.step(time.time(), pr.router_up, pr.internet_up, self.last_reboot):
                    if ev[0] == "alert":
                        log.info("internet down (router reachable) since %s", clock(ev[1]))
                        events.record("outage_start", since=ev[1])
                    elif ev[0] == "recovered":
                        log.info("internet back after %s", dur(ev[2] - ev[1]))
                        events.record("outage_end", since=ev[1], until=ev[2])
                    elif ev[0] == "reset":
                        log.info("PC resumed from sleep - outage state cleared, re-checking")
                        events.record("outage_end", since=ev[1], until=ev[2], note="pc slept")
                    self.q.put(ev)
            except Exception:  # noqa: BLE001
                log.exception("check failed")
            time.sleep(FAST_INTERVAL if mon.fails else INTERVAL)

    def drain(self):
        try:
            while True:
                ev = self.q.get_nowait()
                if ev[0] == "alert":
                    self.popup.show_down(ev[1])
                elif ev[0] == "recovered":
                    self.popup.show_back(ev[1], ev[2])
                elif ev[0] == "reset":
                    self.popup.reset()
        except queue.Empty:
            pass
        self.root.after(200, self.drain)


def run(cfg: Config, demo: bool = False) -> int:
    from .ui.theme import resolve_theme, set_icon
    from .ui.widgets import UI

    lock = None
    if not demo:
        lock = acquire_lock()
        if lock is None:
            log.info("already running - exiting")
            return 0
    root = tk.Tk()
    root.withdraw()
    set_icon(root, ICON)
    Watchdog(root, cfg, UI(root, resolve_theme(cfg.theme)), demo=demo)
    try:
        root.mainloop()
    finally:
        if lock is not None:
            lock.close()
    return 0
