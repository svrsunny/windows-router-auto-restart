"""Common adapter interface."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)


class RouterError(RuntimeError):
    pass


class AuthError(RouterError):
    """The router rejected the username or password."""


class SessionBusyError(RouterError):
    """The router allows one admin session and another one is open."""


MAC_RE = re.compile(r"^(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$")


def norm_mac(mac: str) -> str:
    """'00-00-5E-00-53-01' / '00005e005301' -> '00:00:5e:00:53:01'; raises ValueError if it isn't one."""
    mac = (mac or "").strip()
    if not (MAC_RE.match(mac) or re.fullmatch(r"[0-9a-fA-F]{12}", mac)):
        raise ValueError(f"not a MAC address: {mac!r}")
    hexes = re.sub(r"[^0-9a-fA-F]", "", mac)
    return ":".join(hexes[i:i + 2] for i in range(0, 12, 2)).lower()


@dataclass
class WifiClient:
    mac: str                 # aa:bb:cc:dd:ee:ff, lower case
    name: str = ""           # host name from the router's DHCP table ("" if unknown)
    ip: str = ""
    rssi: str = ""
    blocked: bool = False    # this app's internet block is on for the device


@dataclass
class Ssid:
    name: str
    band: str                # "2.4 GHz" or "5 GHz"
    can_block: bool          # the router's block applies to devices on this SSID
    clients: list = field(default_factory=list)
    reported: int = 0        # devices the router counts on this SSID (may be more than it lists)


@dataclass
class ClientList:
    ssids: list              # [Ssid]
    unknown: list            # [WifiClient] on Wi-Fi, but the SSID could not be told apart
    blocked_offline: list    # [WifiClient] blocked by this app and not connected right now


class RouterAdapter:
    """Use as a context manager: an open admin session is always released on exit,
    except after a restart request (the restart ends the session by itself)."""

    model_id = ""            # value of router_model in config.json
    display_name = ""
    firmware = ""            # firmware the flow was verified on

    def __init__(self, base_url: str, username: str, password: str, timeout: float = 10, verify=True,
                 attempts: int = 3, retry_delay: float = 5, session: requests.Session | None = None):
        if verify is False:
            raise ValueError("TLS verification cannot be disabled")
        self.base = base_url.rstrip("/")
        self.username, self.password = username, password
        self.timeout, self.verify = timeout, verify
        self.attempts, self.retry_delay = attempts, retry_delay
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.logged_in = False
        self.rebooted = False

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self.logged_in and not self.rebooted:
                self.logout()
        finally:
            self.session.close()

    # ---- to implement per model ----
    def check(self) -> str:
        """Fetch the login page without logging in; return a short description or raise RouterError."""
        raise NotImplementedError

    def login(self) -> None:
        raise NotImplementedError

    def reboot(self) -> None:
        """Send the restart request exactly once. Must never retry it."""
        raise NotImplementedError

    def logout(self) -> None:
        raise NotImplementedError

    # ---- optional: connected clients and internet blocking (call after login) ----
    def list_clients(self) -> ClientList:
        raise RouterError(f"{self.display_name}: listing clients is not supported")

    def set_blocked(self, mac: str, blocked: bool) -> None:
        """Block or unblock the device's internet access. Raises RouterError if the router did not
        take the change."""
        raise RouterError(f"{self.display_name}: blocking clients is not supported")


def short_error(e: Exception) -> str:
    """requests' connection errors are very long; keep the useful part."""
    text = str(e)
    m = re.search(r"\[WinError \d+\][^'\")]*|Read timed out|timed out|Name or service not known|"
                  r"getaddrinfo failed|CERTIFICATE_VERIFY_FAILED[^'\")]*", text)
    return m.group(0).strip() if m else text[:200]
