# Router compatibility

Routers don't share a standard way to log in or restart. Each supported model has an adapter in
`src/routerkit/routers/`, and only flows that were **verified on a real device** are included. The
project never probes for endpoints or tries "common" URLs.

## Supported models

### `gx-gpon-e4222`: GX GPON ONT, firmware E4222-3.0.5-R

Status: **verified on one device.** Login, dry run, restart, and recovery detection were all
checked on real hardware. The router came back after about 1 min 13 s. Other firmware versions are
untested.

How it works:

1. `GET /admin/login.asp`. The page embeds a text captcha in JavaScript (`code = "…"`), which is read from the page.
2. `POST /boaform/admin/formLogin` with `username`, `password`, `captchaTextBox`, a few fixed fields,
   and `postSecurityFlag`. That last value is a 16-bit checksum of the form body, ported from the router's
   `postTableEncrypt()` in `common.js`. Values are URL-encoded as the router's JavaScript does.
3. Success is recognised by the logged-in page loading `adminMenu.js`.
4. Restart: `POST /boaform/admin/formReboot` with `postSecurityFlag=65535` (the checksum of an empty body).
5. Otherwise `POST /boaform/admin/formLogout`, because the router allows only one admin session.

Session handling: the router sets a session cookie, which the HTTP session keeps. There's no
separate CSRF token. If another admin session is open, the router answers "you have logined" and
the attempt stops without retrying.

## Adding a router

You'll need a browser and your own router. **Never share captured passwords, cookies or tokens.**

1. Open the router's web interface, press **F12**, go to **Network** and tick **Preserve log**.
2. Log in, then use the router's own *Restart* button.
3. Note the login request: URL, method, form fields, and where any token or checksum comes from
   (hidden input, cookie, JavaScript). Note how the logged-in page differs from a failed login.
4. Note the restart request: URL, method and body.
5. Copy `src/routerkit/routers/template.py` to a new module, implement `check`, `login`, `reboot`
   and `logout`, and register the class in `routers/__init__.py`.
6. Add tests with simulated responses (see `tests/test_router_mock.py`). Then verify on the real
   device with `Test-Connection.ps1` first, and only then one real restart.
7. Add a section to this file with the model, firmware, status and flow.

Rules for adapters:

- Send the restart request **once**. Set `self.rebooted = True` before sending it. Never retry.
- Bounded login retries only. Don't retry "session busy" or anything that might change settings.
- Don't disable TLS verification.
- Don't log request bodies, cookies or headers.

## Reporting a model that works

Open an issue with the router model, firmware version, ISP (optional), what you tested
(`Test-Connection`, dry run, real restart), and the result. Leave out credentials and anything you
consider private.
