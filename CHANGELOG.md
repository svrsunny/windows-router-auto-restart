# Changelog

## 2.2.1

- Android companion app: now a standard Gradle project (Android Gradle Plugin 9.4, Gradle wrapper
  9.8 with checksum verification). It builds with `gradlew assembleRelease` or opens in Android
  Studio, on Windows too. The custom Linux-only toolchain scripts are removed.
- Android app 2.2.1: no behaviour changes. App data is excluded from Android 12+ cloud backup and
  device transfer, and the launcher icon supports Android 13 themed icons.

## 2.2.0

- New: **Android companion app** (`android/`, guide in `docs/android.md`). It's installed from the
  release APK and appears on the phone as *Router Auto Restart*. It alerts you when the router is
  reachable but the internet is down, and restarts the router from the app or from the alert
  notification. The Windows app is otherwise unchanged.
  - Checks go out over Wi-Fi explicitly, so mobile data can't hide an outage. Before alerting it
    re-checks, and it stays quiet after a restart or after the router itself was unreachable.
  - Same login protocol as the `gx-gpon-e4222` adapter. Tests compare its encoding and checksum
    against the Windows adapter.
  - Same restart safety rules: the request is sent once and never retried, there's a 10-minute
    cooldown, login attempts are limited to 3, and a busy admin session is never retried.
  - Password encrypted with an Android Keystore key, app backup disabled, no built-in router address.
  - Built without Gradle from a pinned toolchain (`android/tools/fetch_toolchain.sh`), with
    reproducible unsigned output. The signing key is git-ignored.

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
