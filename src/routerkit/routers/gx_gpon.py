"""GX GPON ONT web UI, firmware E4222-3.0.5-R.

Flow (verified on one device):
  1. GET  /admin/login.asp              the page embeds the captcha text as  code = "...."
  2. POST /boaform/admin/formLogin      username, password, captcha, plus postSecurityFlag:
                                        a 16-bit checksum of the form body (port of
                                        postTableEncrypt() in the router's common.js)
  3. POST /boaform/admin/formReboot     body "postSecurityFlag=65535" (checksum of "")
     POST /boaform/admin/formLogout     when not rebooting, to free the single admin session

The session is a cookie set by the router; requests.Session keeps it. There is no CSRF token
beyond the checksum. The router allows one admin session at a time: if a browser tab is logged
in, login fails with "you have logined" and nothing is retried.

Connected clients and internet blocking (verified on one device, see docs/router-compatibility.md):
  GET  /boaform/formWlanRedirect?redirect-url=/wlstatus.asp&wlan_idx=N   radio N's SSIDs and counts;
       also selects radio N for the session
  GET  /boaform/admin/formWirelessTbl?submit-url=/admin/wlstatbl.asp     stations on the selected
       radio's main SSID (the router ignores its wlan_idx and uses the session's radio)
  GET  /status_client_list.asp          DHCP leases: MAC, IP, host name, band, signal
  GET  /parental-ctrl.asp               Parental Control switch and rule table
  POST /boaform/admin/formParentCtrl    switch on/off, add a rule, delete a rule
A block is a Parental Control rule for the MAC address, every day 00:00-23:59, named "RC-<mac>"
so rules made by hand are never touched. It cuts internet access, not Wi-Fi, and saving it does
not restart the radios. It does not apply to the extra (virtual) SSIDs, so those are view-only.
"""
from __future__ import annotations

import html
import logging
import re
import time
from urllib.parse import quote_plus

import requests

from .base import (MAC_RE, AuthError, ClientList, RouterAdapter, RouterError, SessionBusyError, Ssid, WifiClient,
                   norm_mac, short_error)

log = logging.getLogger(__name__)

CAPTCHA_RE = re.compile(r'\bcode\s*=\s*"([^"]+)"')
ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
RADIOS = (0, 1)                      # wlan_idx values the router's menu offers
RULE_PREFIX = "RC-"
DAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
PARENTAL = "/parental-ctrl.asp"


def enc(value: str) -> str:
    """Mirror encodeURIComponent plus the extra replaces in postTableEncrypt()."""
    return quote_plus(value, safe="*").replace("~", "%7E")


def _int32(x: int) -> int:
    """Emulate JavaScript's ToInt32 (used implicitly by & and >>)."""
    return ((x + 2**31) % 2**32) - 2**31


def post_security_flag(body: str) -> int:
    """Port of the checksum at the end of postTableEncrypt() in common.js."""
    csum = 0
    n = len(body)
    i = 0
    while i < n:
        c = [ord(ch) for ch in body[i:i + 4]]
        if i + 4 > n:
            csum += c[0] << 24
            if len(c) > 1:
                csum += c[1] << 16
            if len(c) > 2:
                csum += c[2] << 8
            break
        csum += (c[0] << 24) + (c[1] << 16) + (c[2] << 8) + c[3]
        i += 4
    v = _int32(csum)
    csum = ((v & 0xFFFF) + (v >> 16)) & 0xFFFF
    return (~csum) & 0xFFFF


def form_body(fields: list[tuple[str, str]]) -> str:
    """A form post as the router's pages send it: the enabled fields in page order, then
    postSecurityFlag (the checksum of everything before it, as postTableEncrypt() computes it)."""
    body = "".join(f"{name}={enc(value)}&" for name, value in fields)
    return body + f"postSecurityFlag={post_security_flag(body)}"


def build_login_body(user: str, password: str, captcha: str) -> str:
    return form_body([("challenge", ""), ("username", user), ("password", password),
                      ("captchaTextBox", captcha), ("save", "Login"), ("submit-url", "/admin/login.asp")])


# ---------- page parsing (pure functions, tested against saved page shapes) ----------

def _cells(row: str) -> list[str]:
    return [html.unescape(TAG_RE.sub("", c)).strip() for c in CELL_RE.findall(row)]


def _js(page: str, name: str) -> dict[int, str]:
    """Values of name[i]=... assignments in the page's script, quotes stripped."""
    out = {}
    for i, v in re.findall(rf"\b{re.escape(name)}\[(\d+)\]\s*=\s*('[^']*'|-?\d+)\s*;", page):
        out[int(i)] = v[1:-1] if v.startswith("'") else v
    return out


def parse_radio(page: str) -> dict:
    """wlstatus.asp -> band, main SSID name/count and the enabled extra SSIDs [(name, count)]."""
    band_flag = re.search(r"\bBand2G5GSupport\s*=\s*(\d+)", page)
    if not band_flag or band_flag.group(1) not in ("1", "2"):
        raise RouterError("Wi-Fi status page looks different than expected (band not found)")
    main = _js(page, "ssid_drv").get(0, "")
    disabled = _js(page, "wlanDisabled").get(0, "0") != "0"
    extra_names, extra_off, extra_n = _js(page, "mssid_ssid_drv"), _js(page, "mssid_disable"), \
        _js(page, "mssid_clientnum")
    extras = [(extra_names[i], int(extra_n.get(i, "0") or 0)) for i in sorted(extra_names)
              if extra_off.get(i, "1") == "0" and extra_names[i]]
    return {"band": "2.4 GHz" if band_flag.group(1) == "1" else "5 GHz",
            "main": "" if disabled else main, "extras": extras}


def parse_stations(page: str) -> list[str]:
    """wlstatbl.asp -> MACs on the selected radio's main SSID."""
    return [norm_mac(c[0]) for c in map(_cells, ROW_RE.findall(page)) if c and MAC_RE.match(c[0])]


def parse_dhcp(page: str) -> list[dict]:
    """status_client_list.asp -> [{mac, ip, name, band, rssi}] (DHCP and static tables)."""
    out = []
    for c in map(_cells, ROW_RE.findall(page)):
        if len(c) >= 5 and MAC_RE.match(c[0]):
            band = {"5GHz": "5 GHz", "2.4GHz": "2.4 GHz"}.get(c[3].replace(" ", ""), "")
            out.append({"mac": norm_mac(c[0]), "ip": c[1], "name": "" if c[2] in ("", "----") else c[2],
                        "band": band, "rssi": "" if c[4] in ("", "----") else c[4]})
    return out


def parse_parental(page: str) -> tuple[bool, list[dict]]:
    """parental-ctrl.asp -> (switch on?, [{select, name, mac}]) - select is the delete checkbox name."""
    if "formParentCtrlDel" not in page:
        raise RouterError("Parental Control page looks different than expected")
    on = re.search(r'value="1"\s+name="parental_ctrl_on"\s*checked', page) is not None
    table = page[page.index("formParentCtrlDel"):]
    rules = []
    for row in ROW_RE.findall(table):
        box = re.search(r'name="?(select\d+)"?', row)
        if not box:
            continue
        cells = _cells(row)
        mac = next((x for x in cells if MAC_RE.match(x)), "")
        rules.append({"select": box.group(1), "name": cells[0] if cells else "",
                      "mac": norm_mac(mac) if mac else ""})
    return on, rules


def rule_name(mac: str) -> str:
    return RULE_PREFIX + norm_mac(mac).replace(":", "")


def build_clients(radios: list[dict], stations: list[list[str]], dhcp: list[dict],
                  blocked: set[str]) -> ClientList:
    """Group devices by SSID. Main-SSID devices come from the router's station table. A device the
    DHCP table puts on a radio's band but that is not on its main SSID is on an extra SSID; that is
    only assigned when the radio has exactly one extra SSID and the router's count for it matches.
    Anything else goes to `unknown` rather than being guessed."""
    by_mac = {d["mac"]: d for d in dhcp}
    seen: set[str] = set()

    def client(mac: str) -> WifiClient:
        d = by_mac.get(mac, {})
        seen.add(mac)
        return WifiClient(mac, d.get("name", ""), d.get("ip", ""), d.get("rssi", ""), mac in blocked)

    ssids, unknown = [], []
    for radio, main_macs in zip(radios, stations):
        if radio["main"]:
            ssids.append(Ssid(radio["main"], radio["band"], True, [client(m) for m in main_macs], len(main_macs)))
        rest = [d["mac"] for d in dhcp if d["band"] == radio["band"] and d["mac"] not in main_macs
                and d["mac"] not in seen]
        extras = radio["extras"]
        if len(extras) == 1 and extras[0][1] == len(rest):
            ssids.append(Ssid(extras[0][0], radio["band"], False, [client(m) for m in rest], extras[0][1]))
        else:
            # e.g. devices with a fixed IP or their own DHCP are counted by the router but never listed
            ssids.extend(Ssid(name, radio["band"], False, [], n) for name, n in extras)
            unknown.extend(client(m) for m in rest)
    offline = [WifiClient(m, by_mac.get(m, {}).get("name", ""), blocked=True) for m in sorted(blocked - seen)]
    return ClientList(ssids, unknown, offline)


class GxGponE4222(RouterAdapter):
    model_id = "gx-gpon-e4222"
    display_name = "GX GPON ONT"
    firmware = "E4222-3.0.5-R"

    def _headers(self, referer: str) -> dict:
        return {"Content-Type": "application/x-www-form-urlencoded", "Origin": self.base,
                "Referer": f"{self.base}{referer}"}

    def _login_page(self) -> str:
        r = self.session.get(f"{self.base}/admin/login.asp", timeout=self.timeout, verify=self.verify)
        r.raise_for_status()
        return r.text

    def check(self) -> str:
        try:
            page = self._login_page()
        except requests.HTTPError as e:
            raise RouterError(f"login page returned HTTP {e.response.status_code}") from None
        except requests.RequestException as e:
            raise RouterError(f"could not load the login page: {short_error(e)}") from None
        if not CAPTCHA_RE.search(page):
            raise RouterError("the login page does not look like a GX GPON E4222 page "
                              "(captcha field not found) - wrong model or firmware?")
        return "login page found (captcha present)"

    def login(self) -> None:
        for n in range(1, self.attempts + 1):
            try:
                page = self._login_page()
                m = CAPTCHA_RE.search(page)
                if not m:
                    raise RouterError("captcha text not found in login.asp (firmware changed?)")
                r = self.session.post(
                    f"{self.base}/boaform/admin/formLogin",
                    data=build_login_body(self.username, self.password, m.group(1)),
                    headers=self._headers("/admin/login.asp"), timeout=self.timeout, verify=self.verify,
                )
                if "you have logined" in r.text:
                    raise SessionBusyError(
                        "router already has an admin session open (browser tab or an earlier run); "
                        "log out there and try again"
                    )
                # The logged-in landing page loads adminMenu.js; the login form does not.
                if "adminMenu" in r.text:
                    self.logged_in = True
                    return
                log.warning("login attempt %d rejected (HTTP %s) - wrong username or password?", n, r.status_code)
                if n == self.attempts:
                    raise AuthError(f"login rejected {self.attempts} times - check the username and password")
            except requests.RequestException as e:
                log.warning("login attempt %d failed: %s", n, short_error(e))
                if n == self.attempts:
                    raise RouterError(f"login failed after {self.attempts} attempts: {short_error(e)}") from None
            time.sleep(self.retry_delay)
        raise RouterError("login failed")          # not reached

    def reboot(self) -> None:
        body = f"postSecurityFlag={post_security_flag('')}"  # == 65535, same as the browser sends
        self.rebooted = True        # set first: the request is never repeated, whatever happens
        try:
            r = self.session.post(f"{self.base}/boaform/admin/formReboot", data=body,
                                  headers=self._headers("/reboot.asp"), timeout=15, verify=self.verify)
            log.info("restart request sent: HTTP %s, %d bytes", r.status_code, len(r.text))
            if r.status_code >= 400:
                raise RouterError(f"restart request returned HTTP {r.status_code}")
        except (requests.ConnectionError, requests.ReadTimeout):
            # The router often drops the connection as it goes down. Whether it is restarting is
            # decided afterwards by watching it go offline, not by sending the request again.
            log.info("connection dropped after the restart request - the router is probably restarting")

    def logout(self) -> None:
        try:
            self.session.post(f"{self.base}/boaform/admin/formLogout",
                              data="save=Logout&submit-url=%2Fadmin%2Flogin.asp",
                              headers=self._headers("/"), timeout=self.timeout, verify=self.verify)
            self.logged_in = False
            log.info("logged out")
        except requests.RequestException as e:
            log.warning("logout failed: %s", short_error(e))

    # ---------- connected clients and internet blocking ----------
    def _page(self, path: str) -> str:
        try:
            r = self.session.get(f"{self.base}{path}", timeout=self.timeout, verify=self.verify)
            r.raise_for_status()
        except requests.HTTPError as e:
            raise RouterError(f"{path.split('?')[0]} returned HTTP {e.response.status_code}") from None
        except requests.RequestException as e:
            raise RouterError(f"could not load {path.split('?')[0]}: {short_error(e)}") from None
        if CAPTCHA_RE.search(r.text) and "formLogin" in r.text:
            raise RouterError("the router ended the admin session")
        return r.text

    def _post_parental(self, fields: list[tuple[str, str]]) -> None:
        try:
            r = self.session.post(f"{self.base}/boaform/admin/formParentCtrl", data=form_body(fields),
                                  headers=self._headers(PARENTAL), timeout=self.timeout, verify=self.verify)
        except requests.RequestException as e:
            raise RouterError(f"Parental Control request failed: {short_error(e)}") from None
        if r.status_code >= 400:
            raise RouterError(f"Parental Control request returned HTTP {r.status_code}")

    def _parental(self) -> tuple[bool, list[dict]]:
        return parse_parental(self._page(PARENTAL))

    def list_clients(self) -> ClientList:
        radios, stations = [], []
        for idx in RADIOS:
            # the station table answers for the radio the redirect selected, so keep this order
            radios.append(parse_radio(self._page(f"/boaform/formWlanRedirect?redirect-url=/wlstatus.asp&wlan_idx={idx}")))
            stations.append(parse_stations(
                self._page(f"/boaform/admin/formWirelessTbl?submit-url=/admin/wlstatbl.asp&wlan_idx={idx}")))
        dhcp = parse_dhcp(self._page("/status_client_list.asp"))
        on, rules = self._parental()
        blocked = {r["mac"] for r in rules if on and r["mac"] and r["name"].startswith(RULE_PREFIX)}
        return build_clients(radios, stations, dhcp, blocked)

    def set_blocked(self, mac: str, blocked: bool) -> None:
        mac = norm_mac(mac)
        mine = lambda rules: [r for r in rules if r["mac"] == mac and r["name"].startswith(RULE_PREFIX)]  # noqa: E731
        on, rules = self._parental()
        if blocked:
            if not on:
                self._post_parental([("parental_ctrl_on", "1"), ("parentalCtrlSet", "Apply Changes"),
                                     ("submit-url", PARENTAL)])
            if not mine(rules):
                self._post_parental([("usrname", rule_name(mac)), ("specPC", "1"),
                                     ("mac", mac.replace(":", "").upper()), *[(d, "on") for d in DAYS],
                                     ("starthr", "00"), ("startmin", "00"), ("endhr", "23"), ("endmin", "59"),
                                     ("addfilterMac", "Add"), ("submit-url", PARENTAL)])
            on, rules = self._parental()
            if not (on and mine(rules)):
                raise RouterError("the router did not keep the block - nothing changed")
            log.info("internet blocked for %s", mac)
            return
        for _ in range(len(mine(rules))):          # one at a time: deleting renumbers the checkboxes
            self._post_parental([(mine(rules)[0]["select"], "ON"), ("deleteSelFilterMac", "Delete Selected"),
                                 ("submit-url", PARENTAL)])
            on, rules = self._parental()
            if not mine(rules):
                break
        if mine(rules):
            raise RouterError("the router did not remove the block")
        if on and not rules:                       # nothing else uses Parental Control: switch it back off
            self._post_parental([("parental_ctrl_on", "0"), ("parentalCtrlSet", "Apply Changes"),
                                 ("submit-url", PARENTAL)])
        log.info("internet unblocked for %s", mac)
