"""Common adapter interface."""
from __future__ import annotations

import re

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


def short_error(e: Exception) -> str:
    """requests' connection errors are very long; keep the useful part."""
    text = str(e)
    m = re.search(r"\[WinError \d+\][^'\")]*|Read timed out|timed out|Name or service not known|"
                  r"getaddrinfo failed|CERTIFICATE_VERIFY_FAILED[^'\")]*", text)
    return m.group(0).strip() if m else text[:200]
