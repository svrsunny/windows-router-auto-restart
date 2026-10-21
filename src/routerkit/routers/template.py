"""Template for a new router adapter. It is NOT registered and does nothing until implemented.

How to work out your router's flow (in your browser, on your own router):
  1. Open the router's web UI, press F12, open the Network tab, tick "Preserve log".
  2. Log in, then restart the router from its menu.
  3. Look at the requests: the login POST (URL, form fields, any token or checksum field), the
     cookie the router sets, and the request sent by the restart button.
  4. Find where any token comes from (a hidden <input>, a cookie, a JavaScript function).
  5. Do NOT post captured passwords, cookies or tokens in issues or commits.

Then:
  - copy this file to routers/<your_model>.py, rename the class, set model_id etc.
  - implement check / login / reboot / logout using self.session, self.timeout, self.verify
  - register the class in routers/__init__.py ADAPTERS
  - add tests with mocked responses (see tests/test_router_mock.py)
  - document it in docs/router-compatibility.md
"""
from __future__ import annotations

from .base import RouterAdapter, RouterError


class ExampleRouter(RouterAdapter):
    model_id = "example-model"            # what users put in config.json "router_model"
    display_name = "YOUR_ROUTER_MODEL"
    firmware = "YOUR_FIRMWARE_VERSION"

    def check(self) -> str:
        # GET the login page and confirm it is the expected model; do not log in here.
        raise RouterError("adapter not implemented")

    def login(self) -> None:
        # GET login page -> extract token(s) -> POST credentials -> confirm a logged-in page.
        # Raise AuthError for rejected credentials, SessionBusyError if another admin is logged in.
        # Set self.logged_in = True on success. Retry at most self.attempts times, only on
        # network errors or rejected logins - never on anything that might have changed settings.
        raise RouterError("adapter not implemented")

    def reboot(self) -> None:
        # Set self.rebooted = True first, then send the restart request ONCE.
        # A dropped connection usually means the router is already going down: do not retry.
        raise RouterError("adapter not implemented")

    def logout(self) -> None:
        # Best effort: free the admin session. Never raise.
        pass
