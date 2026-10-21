"""Router flow, restart safety, recovery checks and redaction - against a simulated router.
Nothing here opens a real connection to a router."""
import _setup  # noqa: F401  (must come first)

import io
import logging
import os
import time
import unittest
from unittest import mock

import requests

from routerkit import actions, events, net
from routerkit.config import parse_config
from routerkit.routers import RouterError, SessionBusyError, get_adapter
from routerkit.routers.base import AuthError

LOGIN_PAGE = '<html><script>var code = "Ab3x";</script><form>...</form></html>'
LOGGED_IN = '<html><script src="/admin/adminMenu.js"></script></html>'
REJECTED = '<html><script>var code = "Zz9q";</script>bad password</html>'
FAKE_PW = "Fake-Passw0rd!"          # test value only


class Resp:
    def __init__(self, text="", status=200):
        self.text, self.status_code = text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class FakeSession:
    """handler(method, path, data) -> Resp, or raises."""

    def __init__(self, handler):
        self.handler, self.headers, self.calls, self.closed = handler, {}, [], False

    def _do(self, method, url, data=None, **kw):
        path = url.split("192.0.2.1", 1)[-1]
        self.calls.append((method, path, data, kw))
        return self.handler(method, path, data)

    def get(self, url, **kw):
        return self._do("GET", url, **kw)

    def post(self, url, data=None, **kw):
        return self._do("POST", url, data, **kw)

    def close(self):
        self.closed = True

    def paths(self):
        return [f"{m} {p}" for m, p, _, _ in self.calls]


def router(login=LOGGED_IN, reboot=lambda: Resp("rebooting"), get_exc=None):
    def handler(method, path, data):
        if method == "GET" and path == "/admin/login.asp":
            if get_exc:
                raise get_exc
            return Resp(LOGIN_PAGE)
        if path == "/boaform/admin/formLogin":
            return Resp(login)
        if path == "/boaform/admin/formReboot":
            return reboot()
        if path == "/boaform/admin/formLogout":
            return Resp("bye")
        return Resp("not found", 404)
    return handler


CFG, _ = parse_config(dict(_setup.TEST_CONFIG))


def adapter(handler):
    s = FakeSession(handler)
    return get_adapter(CFG, FAKE_PW, session=s), s


class AdapterFlow(unittest.TestCase):
    def test_login_success_and_logout_on_exit(self):
        a, s = adapter(router())
        with a:
            a.login()
            self.assertTrue(a.logged_in)
        self.assertEqual(s.paths(), ["GET /admin/login.asp", "POST /boaform/admin/formLogin",
                                     "POST /boaform/admin/formLogout"])
        body = s.calls[1][2]
        self.assertIn("captchaTextBox=Ab3x", body)
        self.assertRegex(body, r"&postSecurityFlag=\d+$")
        self.assertEqual(s.calls[1][3]["verify"], True)          # TLS verification stays on
        self.assertTrue(s.closed)

    def test_wrong_password(self):
        a, s = adapter(router(login=REJECTED))
        with self.assertRaises(AuthError), a:
            a.login()
        self.assertEqual(s.paths().count("POST /boaform/admin/formLogin"), CFG.login_attempts)
        self.assertNotIn("POST /boaform/admin/formLogout", s.paths())

    def test_session_busy_is_not_retried(self):
        a, s = adapter(router(login="you have logined"))
        with self.assertRaises(SessionBusyError), a:
            a.login()
        self.assertEqual(s.paths().count("POST /boaform/admin/formLogin"), 1)

    def test_timeout_bounded_retries(self):
        a, s = adapter(router(get_exc=requests.ConnectTimeout("timed out")))
        with self.assertRaises(RouterError) as cm, a:
            a.login()
        self.assertIn("timed out", str(cm.exception))
        self.assertEqual(len(s.calls), CFG.login_attempts)

    def test_http_error_on_login_page(self):
        a, _ = adapter(lambda m, p, d: Resp("oops", 500))
        with self.assertRaises(RouterError) as cm:
            a.check()
        self.assertIn("HTTP 500", str(cm.exception))

    def test_wrong_model_detected(self):
        a, _ = adapter(lambda m, p, d: Resp("<html>some other router</html>"))
        with self.assertRaises(RouterError) as cm:
            a.check()
        self.assertIn("captcha", str(cm.exception))

    def test_reboot_connection_drop_counts_as_sent_and_no_logout(self):
        def drop():
            raise requests.ConnectionError("connection reset")
        a, s = adapter(router(reboot=drop))
        with a:
            a.login()
            a.reboot()
        self.assertEqual(s.paths().count("POST /boaform/admin/formReboot"), 1)
        self.assertNotIn("POST /boaform/admin/formLogout", s.paths())
        self.assertEqual(s.calls[-1][2], "postSecurityFlag=65535")

    def test_reboot_http_error(self):
        a, s = adapter(router(reboot=lambda: Resp("denied", 403)))
        with self.assertRaises(RouterError), a:
            a.login()
            a.reboot()
        self.assertEqual(s.paths().count("POST /boaform/admin/formReboot"), 1)

    def test_tls_cannot_be_disabled(self):
        from routerkit.routers.gx_gpon import GxGponE4222
        with self.assertRaises(ValueError):
            GxGponE4222("https://192.0.2.1", "u", "p", verify=False, session=FakeSession(router()))


class RestartSafety(unittest.TestCase):
    def setUp(self):
        for p in (events.EVENTS_FILE, actions.LOCK_FILE):
            p.unlink(missing_ok=True)
        self.pw = mock.patch.object(actions.credentials, "get_password", return_value=(FAKE_PW, "test"))
        self.pw.start()

    def tearDown(self):
        self.pw.stop()
        actions.LOCK_FILE.unlink(missing_ok=True)

    def test_dry_run_never_restarts(self):
        s = FakeSession(router())
        self.assertEqual(actions.run_reboot(CFG, dry_run=True, session=s), actions.OK)
        self.assertNotIn("POST /boaform/admin/formReboot", s.paths())
        self.assertIn("POST /boaform/admin/formLogout", s.paths())

    def test_restart_sends_once_and_records(self):
        s = FakeSession(router())
        with mock.patch.object(actions, "wait_for_return", return_value="recovered") as w:
            self.assertEqual(actions.run_reboot(CFG, session=s), actions.OK)
        w.assert_called_once()
        self.assertEqual(s.paths().count("POST /boaform/admin/formReboot"), 1)
        self.assertIsNotNone(events.last_reboot(events.read_events()))
        self.assertFalse(actions.LOCK_FILE.exists())            # lock released

    def test_unverified_recovery_is_reported(self):
        with mock.patch.object(actions, "wait_for_return", return_value="not_down"):
            self.assertEqual(actions.run_reboot(CFG, session=FakeSession(router())), actions.NOT_VERIFIED)

    def test_cooldown_blocks_second_restart(self):
        events.record("reboot", ok=True)
        s = FakeSession(router())
        self.assertEqual(actions.run_reboot(CFG, wait=False, session=s), actions.BLOCKED)
        self.assertEqual(s.calls, [])                            # router never contacted
        s2 = FakeSession(router())
        self.assertEqual(actions.run_reboot(CFG, wait=False, force=True, session=s2), actions.OK)
        self.assertEqual(s2.paths().count("POST /boaform/admin/formReboot"), 1)

    def test_concurrent_restart_blocked_by_lock(self):
        held = actions.RestartLock()
        self.assertTrue(held.acquire())
        try:
            s = FakeSession(router())
            self.assertEqual(actions.run_reboot(CFG, wait=False, session=s), actions.BLOCKED)
            self.assertEqual(s.calls, [])
        finally:
            held.release()

    def test_stale_lock_is_taken_over(self):
        held = actions.RestartLock()
        self.assertTrue(held.acquire())
        old = time.time() - actions.LOCK_STALE - 60
        os.utime(actions.LOCK_FILE, (old, old))
        self.assertTrue(actions.RestartLock().acquire())

    def test_no_password(self):
        with mock.patch.object(actions.credentials, "get_password", return_value=(None, "not set")):
            s = FakeSession(router())
            self.assertEqual(actions.run_reboot(CFG, session=s), actions.NO_PASSWORD)
            self.assertEqual(s.calls, [])

    def test_auth_failure_returns_failed(self):
        self.assertEqual(actions.run_reboot(CFG, session=FakeSession(router(login=REJECTED))), actions.FAILED)
        self.assertIsNone(events.last_reboot(events.read_events()))


class Recovery(unittest.TestCase):
    """wait_for_return with a simulated clock; it only observes, never sends anything."""

    def run_scenario(self, router_states, internet_up=True):
        t = {"now": 1000.0}
        states = iter(router_states)
        last = {"v": True}

        def router_up(_cfg, _timeout=1.0):
            last["v"] = next(states, last["v"])
            return last["v"]

        def sleep(s):
            t["now"] += s

        with mock.patch.object(net, "router_up", router_up), \
                mock.patch.object(net, "probe", lambda cfg: net.Probe(1.0, 20.0 if internet_up else None)):
            return actions.wait_for_return(CFG, 1000.0, sleep=sleep, clock=lambda: t["now"])

    def test_recovered(self):
        self.assertEqual(self.run_scenario([True, True, False, False, False, True]), "recovered")

    def test_router_never_went_down(self):
        self.assertEqual(self.run_scenario([True] * 100), "not_down")

    def test_router_not_back(self):
        self.assertEqual(self.run_scenario([False] * 10000), "router_not_back")

    def test_internet_not_back(self):
        self.assertEqual(self.run_scenario([False, True], internet_up=False), "internet_not_back")


class Diagnostics(unittest.TestCase):
    def run_test(self, ping, session, login=True, pw=(FAKE_PW, "test")):
        out = []
        with mock.patch.object(net, "tcp_ping", return_value=ping), \
                mock.patch.object(net, "probe", return_value=net.Probe(2.0, 15.0)), \
                mock.patch.object(actions.socket, "getaddrinfo", return_value=[]), \
                mock.patch.object(actions.credentials, "get_password", return_value=pw):
            rc = actions.test_connection(CFG, login=login, out=out.append, session=session)
        return rc, "\n".join(out)

    def test_unreachable(self):
        rc, text = self.run_test(None, FakeSession(router()))
        self.assertEqual(rc, actions.FAILED)
        self.assertIn("[FAIL] Router reachable", text)

    def test_all_good_and_never_restarts(self):
        s = FakeSession(router())
        rc, text = self.run_test(3.0, s)
        self.assertEqual(rc, actions.OK, text)
        self.assertNotIn("POST /boaform/admin/formReboot", s.paths())
        self.assertIn("does not prove a restart will work", text)

    def test_skip_login(self):
        s = FakeSession(router())
        rc, text = self.run_test(3.0, s, login=False)
        self.assertEqual(rc, actions.OK)
        self.assertEqual(s.paths(), ["GET /admin/login.asp"])
        self.assertIn("[SKIP] Login test", text)

    def test_bad_password_reported(self):
        rc, text = self.run_test(3.0, FakeSession(router(login=REJECTED)))
        self.assertEqual(rc, actions.FAILED)
        self.assertIn("[FAIL] Login and logout", text)


class Redaction(unittest.TestCase):
    def test_password_never_reaches_log_output(self):
        buf = io.StringIO()
        h = logging.StreamHandler(buf)
        h.addFilter(events.REDACT)
        lg = logging.getLogger("redaction-test")
        lg.addHandler(h)
        lg.propagate = False
        try:
            events.protect(FAKE_PW)
            lg.warning("leak %s and %s", FAKE_PW, "Fake-Passw0rd%21")
            try:
                raise RuntimeError(f"boom {FAKE_PW}")
            except RuntimeError:
                lg.exception("failed")
        finally:
            lg.removeHandler(h)
        text = buf.getvalue()
        self.assertNotIn(FAKE_PW, text)
        self.assertNotIn("Fake-Passw0rd%21", text)
        self.assertIn("***", text)

    def test_login_body_not_logged_on_failure(self):
        buf = io.StringIO()
        h = logging.StreamHandler(buf)
        root = logging.getLogger()
        root.addHandler(h)
        try:
            a, _ = adapter(router(login=REJECTED))
            with self.assertRaises(AuthError), a:
                a.login()
        finally:
            root.removeHandler(h)
        self.assertNotIn(FAKE_PW, buf.getvalue())     # even without the filter, nothing logs it
        self.assertNotIn("Passw0rd", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
