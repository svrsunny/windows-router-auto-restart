# Security

## Credentials

- The router password is stored only in **Windows Credential Manager** (generic credential
  `RouterAutoRestart:router-admin`), encrypted with DPAPI for your Windows account.
- It's never written to `config.json`, logs, the event history, scheduled-task arguments, command
  lines or URLs. URLs containing `user:password@` are rejected.
- `Configure.ps1` reads it with `Read-Host -AsSecureString` and passes it to Python on standard input.
- As a safety net, every log line passes through a redaction filter that replaces the password,
  and its URL-encoded forms, with `***`.
- It's sent only to the router, inside the router's own login form, the same way the browser sends it.

**Limits to be aware of:** any program running as your Windows user can read your Credential Manager
entries. Converting a SecureString for Python leaves a plain copy in that PowerShell process's
memory until it exits. Over plain `http` the login travels unencrypted on your local network, which
is how the router's own web page works too.

View or remove the stored password:

```powershell
cmdkey /list:RouterAutoRestart:router-admin
cmdkey /delete:RouterAutoRestart:router-admin
```

## HTTPS routers and self-signed certificates

Certificate verification is **always on** and can't be turned off in the configuration. If your
router uses HTTPS with a self-signed certificate:

1. Export the router's certificate. In the browser, click the padlock, open the certificate details
   and export it as Base-64 `.cer` or `.pem`.
2. Save it outside the repository, e.g. `%LOCALAPPDATA%\router-auto-restart\router.pem`.
3. Set `"tls_ca_bundle": "C:\\Users\\YOU\\AppData\\Local\\router-auto-restart\\router.pem"` in `config.json`.

The certificate's name must match the address in `router_url`. If the router's certificate lists no
usable name, use `http` on your LAN instead of weakening verification.

## Network behaviour

The program only talks to:

- your router, at the configured address;
- the `probe_targets`, by opening a TCP connection and closing it immediately, to tell whether the
  internet is up (defaults: Cloudflare `1.1.1.1`, Google `8.8.8.8` and Quad9 `9.9.9.9`, port 443);
- `dns_check_host`, a DNS lookup during `Test-Connection.ps1` only;
- the dashboard's public-IP display: `checkip.amazonaws.com`, falling back to `api.ipify.org` and `icanhazip.com`.

There's no telemetry and no update check.

## Restart safety

- The restart request is sent at most once per run and is never retried, including after a timeout.
- A cross-process lock prevents the dashboard and the scheduled task from restarting at the same time.
- A cooldown (`reboot_cooldown_minutes`, default 10) refuses a second restart right after a successful one.
- Login attempts are bounded (`login_attempts`, default 3). An "admin session already open" response is never retried.
- `Test-Connection.ps1` and `reboot --dry-run` log in and out but never restart.

## Before publishing a fork or sharing logs

`config\config.json`, `data\` and `logs\` are git-ignored. Logs contain timestamps and messages
but no secrets. They may still include your router's address. Check before sharing them.

Found a vulnerability? See [SECURITY.md](../SECURITY.md).
