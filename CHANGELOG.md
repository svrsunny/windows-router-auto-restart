# Changelog

## 3.1.0

- Android: new **Fix it automatically** switch, off by default. When the app finds the router up but
  the internet down, it restarts the router itself instead of only alerting. This is for routers
  that lose their connection overnight and don't reconnect. It acts on a confirmed outage only,
  **once per outage**, and never within the 10-minute cooldown. If that doesn't help, or the restart
  can't be sent, you get the normal alert. *Simulate an outage* never triggers it.
- Android: the app checks within seconds of the phone joining Wi-Fi, instead of waiting for the next
  regular check. An outage found in the morning is fixed about 1½–2 minutes after Wi-Fi is turned on.
- Windows app unchanged.

## 3.0.0

- New: **Wi-Fi clients**, in the Windows dashboard (*Wi-Fi clients* button, or `routerctl.py clients`)
  and in the Android app (*Wi-Fi clients* button). Devices are listed under each SSID with name, IP
  address and signal. A device whose SSID the router doesn't report clearly is listed as
  "network not known" instead of being guessed.
- New: **Block / Unblock** a device's internet access (`routerctl.py block|unblock MAC` too). It adds
  or removes a Parental Control rule for the device's MAC address (every day, 00:00-23:59). The
  device stays on Wi-Fi, and other devices aren't disconnected. Rules are named `RC-<mac>`. Rules
  you made in the router's own page are never changed, and Parental Control is switched off again
  only when no rules are left. Each change is checked by reading the rule table back.
- On the GX GPON E4222 the block doesn't apply to the extra (virtual) SSIDs, so devices there are
  listed as view-only.
- Android: router sessions now take turns (the router allows one admin session), and form posts that
  change settings are never silently re-sent.
- Docs: README section *Wi-Fi clients and blocking*, Android guide, troubleshooting and security notes.
  New screenshots of the Wi-Fi clients screens, and updated dashboard and Android main-screen
  screenshots showing the new button (sample data only).

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
