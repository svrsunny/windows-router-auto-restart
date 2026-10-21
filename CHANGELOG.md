# Changelog

## 2.1.0 (first public version)

- Packaged as a standalone repository with PowerShell entry points: `Install`, `Configure`,
  `Test-Connection`, `Restart-Router`, `Register-ScheduledTask`, `Remove-ScheduledTask`, `New-Shortcut`
  and `Uninstall`.
- Router support split into per-model adapters (`gx-gpon-e4222`), with a documented template for new models.
- No built-in router address or personal data. Configuration lives in a git-ignored `config/config.json`.
- Password stored in Windows Credential Manager. Set through `Read-Host -AsSecureString` and standard input.
- Log redaction filter for the password.
- Restart safety: cross-process lock, cooldown after a successful restart, the restart request never
  retried, and "request sent" reported separately from "recovery verified" (exit code 3).
- `Test-Connection` diagnostics that never restart.
- Scheduled task runs as the current user (interactive, limited rights), with no automatic retries.
- Taskbar-pinnable dashboard shortcut with its own AppUserModelID and icon.
- Tests with a simulated router, plus tests of the CLI and PowerShell scripts.

## 2.0.0

- Rewrite of the original scripts: dashboard with countdown ring, latency chart and 24-hour uptime;
  themed countdown window and watchdog pop-up; structured event history; reboot recovery timing.

## 1.x

- Original scripts: reboot via the router's web UI, Task Scheduler countdown, Tk dashboard, internet watchdog.
