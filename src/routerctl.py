#!/usr/bin/env python3
"""
router-auto-restart command line. The PowerShell scripts in scripts\\ wrap these commands.

  routerctl.py                        open the dashboard (same as `dashboard`)
  routerctl.py test [--no-login]      diagnostics: reachability, login page, login+logout, internet, DNS
  routerctl.py reboot                 restart the router now (asks for confirmation)
  routerctl.py reboot --dry-run       log in and out only, no restart
  routerctl.py reboot --prompt        countdown window first (used by the scheduled task)
  routerctl.py watchdog [--demo]      background internet watchdog
  routerctl.py status                 one-screen summary
  routerctl.py models                 list supported router models
  routerctl.py check-config           validate config\\config.json
  routerctl.py set-password [--stdin] store the password in Windows Credential Manager
  routerctl.py clear-password         remove it
  routerctl.py install [--time HH:MM --every-days N --warn-minutes M --with-watchdog --print-only]
  routerctl.py uninstall [--with-watchdog]

Exit codes: 0 ok, 1 failed, 2 no password, 3 restart sent but recovery not verified,
            4 restart refused (cooldown / already running), 5 configuration problem.
"""
from __future__ import annotations

import argparse
import getpass
import logging
import sys

from routerkit import __version__, actions, credentials, events, net, scheduler, state
from routerkit.config import CONFIG_FILE, ConfigError, load_config

CONFIG_PROBLEM = 5


def cmd_reboot(cfg, args) -> int:
    events.setup_logging("reboot")
    if args.prompt and not args.dry_run and state.consume_skip():
        logging.info("scheduled run skipped (skip-next flag set from the dashboard)")
        events.record("reboot_skipped", reason="skip flag")
        return 0
    if args.prompt:
        from routerkit.ui.prompt import confirm_reboot
        warn = cfg.warn_minutes if args.warn_minutes is None else args.warn_minutes
        choice = confirm_reboot(cfg.theme, warn_secs=warn * 60,
                                postpone_secs=tuple(m * 60 for m in cfg.postpone_minutes))
        if choice == "skip":
            logging.info("restart skipped by user")
            events.record("reboot_skipped", reason="user")
            return 0
        logging.info("countdown finished or restart-now chosen")
    elif not args.dry_run and not args.yes:
        refuse = "refusing to restart without confirmation; pass --yes for unattended use"
        if sys.stdin is None or not sys.stdin.isatty():
            logging.error(refuse)
            return actions.FAILED
        print(f"This restarts the router at {cfg.router_url} now. The internet connection will drop "
              "for a few minutes.")
        try:
            answer = input("Type RESTART to continue: ")
        except EOFError:              # e.g. stdin is NUL, which Windows reports as a terminal
            logging.error(refuse)
            return actions.FAILED
        if answer.strip() != "RESTART":
            print("Cancelled.")
            return actions.FAILED
    return actions.run_reboot(cfg, dry_run=args.dry_run, wait=not args.no_wait, force=args.force)


def cmd_test(cfg, args) -> int:
    events.setup_logging("test", console=False)
    return actions.test_connection(cfg, login=not args.no_login)


def cmd_watchdog(cfg, args) -> int:
    from routerkit import watchdog
    events.setup_logging("watchdog")
    return watchdog.run(cfg, demo=args.demo)


def cmd_dashboard(cfg, _args) -> int:
    from routerkit.ui import dashboard
    events.setup_logging("dashboard")
    return dashboard.run(cfg)


def cmd_status(cfg, _args) -> int:
    from routerkit import watchdog
    pr = net.probe(cfg)
    ms = lambda v: "down" if v is None else f"up ({v:.0f} ms)"  # noqa: E731
    print(f"router-auto-restart {__version__}")
    print(f"  router    {cfg.router_url} [{cfg.router_model}]  {ms(pr.router_ms)}")
    print(f"  internet  {ms(pr.internet_ms)}")
    print(f"  password  {credentials.get_password()[1]}")
    print(f"  watchdog  {'running' if watchdog.is_running() else 'not running'}")
    t = scheduler.query_task(cfg.task_name)
    if "error" in t:
        print(f"  schedule  error: {t['error']}")
    elif t.get("missing"):
        print(f"  schedule  task '{cfg.task_name}' is not registered (scripts\\Register-ScheduledTask.ps1)")
    else:
        nxt = t["next"].strftime("%a %d %b %Y %H:%M") if t["next"] else "-"
        print(f"  schedule  {t['state']}; every {t.get('days') or '?'} day(s) at {t.get('at') or '?'}; next run {nxt}")
        if t.get("last"):
            print(f"            last run {t['last']:%a %d %b %H:%M}: {scheduler.result_text(t['result'])}")
    print(f"  skip next {'yes' if state.skip_is_set() else 'no'}")
    return 0


def cmd_models(_cfg, _args) -> int:
    from routerkit.routers import ADAPTERS
    for mid, cls in sorted(ADAPTERS.items()):
        print(f"{mid}\t{cls.display_name} (verified on firmware {cls.firmware})")
    return 0


def cmd_check_config(_cfg, _args) -> int:
    load_config()                    # raises ConfigError with details
    print(f"{CONFIG_FILE} is valid.")
    return 0


def cmd_set_password(cfg, args) -> int:
    username = cfg.username if cfg else "admin"
    if args.stdin:
        raw = sys.stdin.buffer.readline() if sys.stdin is not None else b""
        pw = raw.decode("utf-8-sig").rstrip("\r\n")
    else:
        pw = getpass.getpass(f"Router password for '{username}': ")
        if pw and getpass.getpass("Again: ") != pw:
            print("The two entries differ; unchanged.")
            return 1
    if not pw:
        print("Nothing entered; unchanged.")
        return 1
    credentials.vault_write(pw, username)
    print("Password saved to Windows Credential Manager for this Windows user.")
    return 0


def cmd_clear_password(_cfg, _args) -> int:
    print("Removed from Credential Manager." if credentials.vault_delete() else "No stored password found.")
    return 0


def cmd_install(cfg, args) -> int:
    at = args.time or cfg.restart_time
    days = args.every_days or cfg.interval_days
    warn = cfg.warn_minutes if args.warn_minutes is None else args.warn_minutes
    if args.print_only:
        print(scheduler.reboot_task_script(cfg.task_name, at, days, warn))
        if args.with_watchdog:
            print(scheduler.watchdog_task_script(cfg.watchdog_task_name))
        return 0
    ok, err = scheduler.install_reboot_task(cfg.task_name, at, days, warn)
    print(f"Restart task '{cfg.task_name}': " + (f"registered (every {days} day(s) at {at})" if ok else f"FAILED - {err}"))
    rc = 0 if ok else 1
    if args.with_watchdog:
        ok, err = scheduler.install_watchdog_task(cfg.watchdog_task_name)
        print(f"Watchdog task '{cfg.watchdog_task_name}': " + ("registered (starts at logon)" if ok else f"FAILED - {err}"))
        rc = rc or (0 if ok else 1)
    return rc


def cmd_uninstall(cfg, args) -> int:
    names = [cfg.task_name] + ([cfg.watchdog_task_name] if args.with_watchdog else [])
    rc = 0
    for name in names:
        ok, err = scheduler.uninstall(name)
        print(f"{name}: " + ("removed (or was not registered)" if ok else f"FAILED - {err}"))
        rc = rc or (0 if ok else 1)
    return rc


NO_CONFIG_NEEDED = {"models", "set-password", "clear-password", "check-config"}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="routerctl", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("reboot", help="restart the router (or test the login)")
    r.add_argument("--dry-run", action="store_true", help="log in and out, do not restart")
    r.add_argument("--prompt", action="store_true", help="show the countdown window first")
    r.add_argument("--warn-minutes", type=float, default=None, help="countdown length for --prompt")
    r.add_argument("--no-wait", action="store_true", help="do not follow the router while it restarts")
    r.add_argument("--yes", action="store_true", help="do not ask for confirmation (unattended use)")
    r.add_argument("--force", action="store_true", help="ignore the cooldown after a recent restart")
    t = sub.add_parser("test", help="diagnostics; never restarts")
    t.add_argument("--no-login", action="store_true", help="skip the login/logout step")
    w = sub.add_parser("watchdog", help="run the internet watchdog")
    w.add_argument("--demo", action="store_true", help="show the pop-ups once, without network checks")
    sub.add_parser("dashboard", help="open the dashboard")
    sub.add_parser("status", help="print a status summary")
    sub.add_parser("models", help="list supported router models")
    sub.add_parser("check-config", help="validate the configuration file")
    sp = sub.add_parser("set-password", help="store the router password in Credential Manager")
    sp.add_argument("--stdin", action="store_true", help="read it from standard input (used by Configure.ps1)")
    sub.add_parser("clear-password", help="remove the stored password")
    i = sub.add_parser("install", help="register the scheduled task(s)")
    i.add_argument("--time", default=None, help="time of day HH:MM (default from config)")
    i.add_argument("--every-days", type=int, default=None, help="days between restarts (default from config)")
    i.add_argument("--warn-minutes", type=float, default=None, help="countdown length (default from config)")
    i.add_argument("--with-watchdog", action="store_true", help="also start the watchdog at logon")
    i.add_argument("--print-only", action="store_true", help="print the PowerShell that would run; change nothing")
    u = sub.add_parser("uninstall", help="remove the scheduled task(s)")
    u.add_argument("--with-watchdog", action="store_true", help="also remove the watchdog task")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"reboot": cmd_reboot, "test": cmd_test, "watchdog": cmd_watchdog, "dashboard": cmd_dashboard,
                None: cmd_dashboard, "status": cmd_status, "models": cmd_models, "check-config": cmd_check_config,
                "set-password": cmd_set_password, "clear-password": cmd_clear_password,
                "install": cmd_install, "uninstall": cmd_uninstall}
    try:
        if args.cmd in NO_CONFIG_NEEDED:
            try:
                cfg = load_config(strict=False) if args.cmd != "check-config" else None
            except ConfigError:
                cfg = None
        else:
            cfg = load_config()
        return handlers[args.cmd](cfg, args)
    except ConfigError as e:
        _report_config_error(str(e), args.cmd)
        return CONFIG_PROBLEM
    except ValueError as e:              # bad --time / --every-days etc.
        print(f"error: {e}", file=sys.stderr) if sys.stderr else None
        return 1


def _report_config_error(msg: str, cmd) -> None:
    if sys.stderr is not None:
        print(msg, file=sys.stderr)
        return
    # pythonw (scheduled task / shortcut): no console, so log it and show it if a window makes sense
    events.setup_logging("config", console=False)
    logging.error("%s", msg.replace("\n", " "))
    if cmd in (None, "dashboard"):
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("router-auto-restart", msg)
        root.destroy()


if __name__ == "__main__":
    sys.exit(main())
