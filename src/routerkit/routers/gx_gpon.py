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
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import quote_plus

import requests

from .base import AuthError, RouterAdapter, RouterError, SessionBusyError, short_error

log = logging.getLogger(__name__)

CAPTCHA_RE = re.compile(r'\bcode\s*=\s*"([^"]+)"')


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


def build_login_body(user: str, password: str, captcha: str) -> str:
    body = (
        "challenge=&username=" + enc(user)
        + "&password=" + enc(password)
        + "&captchaTextBox=" + enc(captcha)
        + "&save=Login&submit-url=" + enc("/admin/login.asp") + "&"
    )
    return body + f"postSecurityFlag={post_security_flag(body)}"


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
