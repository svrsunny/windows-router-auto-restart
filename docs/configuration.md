# Configuration

## Interactive setup

```powershell
.\scripts\Configure.ps1
```

Run it again any time to change a value. Press Enter to keep the value shown in brackets. Settings
it doesn't ask about are kept as they are.

Non-interactive (e.g. for scripting; the password step is separate):

```powershell
.\scripts\Configure.ps1 -RouterUrl http://192.0.2.1 -Model gx-gpon-e4222 -Username YOUR_ROUTER_USERNAME `
    -RestartTime 04:00 -IntervalDays 3 -WarnMinutes 10 -NonInteractive -SkipPassword
.\scripts\Configure.ps1 -RouterUrl http://192.0.2.1 -Model gx-gpon-e4222 -NonInteractive   # asks only for the password
```

## Where things are stored

| What | Where | Committed to Git? |
|---|---|---|
| Settings | `config\config.json` | No (git-ignored) |
| Router password | Windows Credential Manager, entry `RouterAutoRestart:router-admin` | No: it's not a file |
| Logs and history | `logs\` | No |
| Skip flag, dashboard cache, restart lock | `data\` | No |

To keep `config`, `data` and `logs` outside the repository, set the user environment variable
`ROUTER_AUTO_RESTART_HOME` to another folder before running anything:

```powershell
[Environment]::SetEnvironmentVariable('ROUTER_AUTO_RESTART_HOME', "$env:LOCALAPPDATA\router-auto-restart", 'User')
```

## Settings reference (`config\config.json`)

| Key | Default | Meaning |
|---|---|---|
| `router_url` | *(required)* | `http://` or `https://` plus the router's address, optionally `:port`. No path, no `user:password@`. Example: `http://192.0.2.1` |
| `router_model` | *(required)* | Adapter id; list them with `.\.venv\Scripts\python.exe src\routerctl.py models` |
| `username` | `admin` | Router admin username |
| `restart_time` | `04:00` | Daily time of the scheduled restart, 24-hour local time (`HH:MM`) |
| `interval_days` | `3` | Days between scheduled restarts (1-365) |
| `warn_minutes` | `10` | Countdown window before a scheduled restart; `0` restarts without asking |
| `postpone_minutes` | `[30, 60]` | Postpone buttons in the countdown window |
| `task_name` | `RouterAutoRestart` | Name of the scheduled task |
| `watchdog_task_name` | `RouterAutoRestart-Watchdog` | Name of the watchdog's logon task |
| `request_timeout` | `10` | Seconds per HTTP request to the router |
| `login_attempts` | `3` | Login tries before giving up (1-10) |
| `retry_delay` | `5` | Seconds between login tries |
| `reboot_cooldown_minutes` | `10` | Refuse a new restart this soon after a successful one (`0` disables) |
| `reboot_wait_seconds` | `300` | How long to wait for the router to come back before reporting "not verified" |
| `tls_ca_bundle` | `""` | For `https` routers with their own certificate: path to a PEM file to trust (see [security.md](security.md)) |
| `probe_targets` | Cloudflare, Google, Quad9 DNS on 443 | Hosts used to decide whether "the internet" is up; it counts as down only if all fail |
| `dns_check_host` | `example.com` | Name resolved by the connection test |
| `theme` | `system` | Dashboard theme: `system`, `light` or `dark` |

Keys starting with `_` are treated as comments. Unknown keys and invalid values are reported by
name. Check the file with:

```powershell
.\.venv\Scripts\python.exe src\routerctl.py check-config
```

## The password

`Configure.ps1` reads it with `Read-Host -AsSecureString`, so it isn't echoed or saved in your
PowerShell history. It's passed to Python on standard input, not on the command line, and stored
with Windows Credential Manager (DPAPI-encrypted for your Windows account).

Change it later:

```powershell
.\scripts\Configure.ps1        # press Enter through the other questions
```

You can also click **Password → Change** in the dashboard.

Limitations:

- The entry belongs to the Windows user who stored it. A scheduled task or another account can only
  read it when running as that same user (the task set up by this project does).
- A SecureString has to be converted to a plain string briefly to hand it to Python. .NET can't
  reliably wipe such strings, so a copy may stay in that PowerShell process's memory until it exits.
- Anything running as your Windows user can read your Credential Manager entries. That's the same
  trust boundary as your browser's saved passwords.

Legacy and not recommended: older setups stored the password with `setx ROUTER_PASS ...`, which
keeps it in plain text in the registry. It's still read as a last resort. Remove it after
running `Configure.ps1`:

```powershell
[Environment]::SetEnvironmentVariable('ROUTER_PASS', $null, 'User')
```

## Overriding for one session

`ROUTER_URL` and `ROUTER_USER` environment variables override the file. `ROUTER_PASS` in the
current process overrides the stored password. Use these for quick tests only.
