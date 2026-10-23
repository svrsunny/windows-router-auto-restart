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

Wi-Fi clients and internet blocking (checked on the same device):

1. `GET /boaform/formWlanRedirect?redirect-url=/wlstatus.asp&wlan_idx=N` (N = 0 for 5 GHz, 1 for
   2.4 GHz). The script on the page has the main SSID, the extra SSIDs (`mssid_*`) and a client count
   for each. The request also selects radio N for the session.
2. `GET /boaform/admin/formWirelessTbl?submit-url=/admin/wlstatbl.asp`. Stations on the main SSID of
   **the radio selected in step 1**. The router ignores a `wlan_idx` on this request, so step 1 must
   come first for each radio.
3. `GET /status_client_list.asp`. DHCP leases with MAC, IP, host name, band and signal. There's no
   page listing the extra SSIDs' stations. A device on a band that isn't on its main SSID is
   assigned to the extra SSID only when that radio has exactly one extra SSID and the router's
   count for it matches.
4. Block: `POST /boaform/admin/formParentCtrl`, first `parental_ctrl_on=1` (switch on) if needed,
   then a rule `usrname=RC-<mac>&specPC=1&mac=<12 hex>&Sun=on…&Sat=on&starthr=00&startmin=00&endhr=23&endmin=59&addfilterMac=Add`.
   Unblock: `select<N>=ON&deleteSelFilterMac=Delete+Selected` for that rule's row, then
   `parental_ctrl_on=0` when the table is empty. Every body ends with `submit-url=%2Fparental-ctrl.asp`
   and `postSecurityFlag`. `GET /parental-ctrl.asp` gives the switch and rule table.

What was observed on the real router:

- Parental Control cut internet access on the main 5 GHz SSID within seconds, and the device stayed
  on Wi-Fi. Saving rules didn't disconnect other devices. It did **not** cut access on the extra
  (virtual) SSID, so devices there are view-only.
- WLAN Access Control (MAC deny list, `formWlAc`) is **not** used. It applies only to a radio's
  main SSID, and every save restarts that radio, dropping all its devices for about 6.5 s.
- The router's clock runs about 27% fast and its time sync didn't correct it. The all-day rule
  leaves a gap of about a minute between 23:59 and 00:00 router time, whenever that falls.

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
