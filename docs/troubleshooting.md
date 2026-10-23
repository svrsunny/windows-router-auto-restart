# Troubleshooting

Start with:

```powershell
.\scripts\Test-Connection.ps1
.\.venv\Scripts\python.exe src\routerctl.py status
Get-Content .\logs\router-auto-restart.log -Tail 30
```

## Exit codes

Shown by the scripts, and as *Last Run Result* of the scheduled task.

| Code | Meaning | What to do |
|---|---|---|
| 0 | OK | |
| 1 | Failed | Read the log; see below |
| 2 | No password stored | `.\scripts\Configure.ps1` |
| 3 | Restart request sent, recovery not verified | The router kept answering (it may not have restarted), or it, or the internet, didn't come back within the wait time. Check the router |
| 4 | Refused: a restart is running or one just happened | Wait for the cooldown (`reboot_cooldown_minutes`) or use `Restart-Router.ps1 -IgnoreCooldown` |
| 5 | Configuration problem | The message names the setting; run `Configure.ps1` |

## Common problems

**"running scripts is disabled on this system"**
Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that window. For a downloaded
ZIP, also run `Get-ChildItem -Recurse | Unblock-File`.

**"The project's Python environment (.venv) is missing"**
Run `.\scripts\Install.ps1`.

**Router reachable: FAIL**
Wrong address, or this PC isn't on the router's network (VPN, guest Wi-Fi, cable unplugged). Open
the address in a browser to compare.

**"router already has an admin session open"**
The router allows one admin login at a time. Log out of its web page in your browser (or close the
tab and wait a few minutes), then try again. Use `Test-Connection.ps1 -SkipLogin` meanwhile.

**"login rejected … check the username and password"**
Re-enter them with `.\scripts\Configure.ps1`. The login is tried `login_attempts` times, never more.

**"does not look like a … page (captcha field not found)"**
The configured `router_model` doesn't match this router, or its firmware changed the login page.
See [router-compatibility.md](router-compatibility.md).

**Certificate errors with https**
See [security.md](security.md#https-routers-and-self-signed-certificates). Verification is never disabled.

**The scheduled task didn't run**
It only runs while you're logged on. Check `Get-ScheduledTask -TaskName RouterAutoRestart | Get-ScheduledTaskInfo`.
If the PC was off, it runs at the next opportunity.

**Countdown window appeared at an odd time**
That's a catch-up run after the PC was off or asleep at the scheduled time. Postpone or skip it.

**Restart sent but exit code 3 ("router still answering")**
Some routers accept the request but restart only after a delay, or ignore it. Watch the router's
lights. If it never restarts, its firmware may need a different request, which means a new
adapter. A timed-out request is **not** retried automatically, because the router may already be
restarting.

**"Pin to taskbar" is missing**
Shortcuts to `.py` or `.pyw` files can't be pinned. Run `.\scripts\New-Shortcut.ps1` and pin the
*Router Auto Restart* entry from Start.

**Dashboard says "Watchdog: Not running"**
Click *Start*, or register it with `Register-ScheduledTask.ps1 -WithWatchdog`.

**Wi-Fi clients: a device I blocked still has internet**
Check which SSID it's on. The block applies on each band's main SSID, not on the router's extra
(virtual) SSIDs, which are listed as view-only. Also check the phone or laptop isn't using mobile
data. The rule follows the router's own clock, so a wrong router time can leave a short gap.

**Wi-Fi clients: "the router did not keep the block" / "did not remove the block"**
The router answered but its Parental Control table doesn't show the change. Nothing else was
changed. Open the router's *Parental Control* page to look, then try again. Rules the app made are
named `RC-<mac>`.

**Wi-Fi clients: a network shows "the router reports N devices … that it doesn't list"**
Those devices aren't in the router's DHCP list, usually because they use a fixed IP address. The
router only reports how many there are.

**Test the watchdog pop-up without an outage**
Create the file `data\force_down.flag` while the watchdog runs (the internet then counts as down)
and delete it to end the test. To see the pop-ups only: `.\.venv\Scripts\python.exe src\routerctl.py watchdog --demo`.

## Reporting a problem

Include the router model and firmware, Windows version, the failing command, and the relevant log
lines. **Remove** IP addresses you consider private, and never include passwords, cookies or tokens.
