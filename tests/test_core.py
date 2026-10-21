"""Pure logic: protocol checksum, watchdog decisions, event store, config, scheduler text."""
import _setup  # noqa: F401  (must come first)

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from routerkit import config, events, scheduler
from routerkit.monitor import Monitor
from routerkit.routers import gx_gpon
from routerkit.util import dur, fmt


class Protocol(unittest.TestCase):
    # reference values produced by the original router_reboot.py
    def test_security_flag(self):
        cases = {"": 65535, "a": 40703, "ab": 40605, "abc": 15261, "abcd": 15161, "abcde": 54841,
                 "challenge=&username=admin&password=p%40ss+w%7Erd&captchaTextBox=X7kQ&save=Login"
                 "&submit-url=%2Fadmin%2Flogin.asp&": 26171}
        for body, want in cases.items():
            self.assertEqual(gx_gpon.post_security_flag(body), want, body)

    def test_login_body(self):
        # "p@ss w~rd!*'()" is a made-up test value exercising the URL-encoding rules
        self.assertEqual(
            gx_gpon.build_login_body("admin", "p@ss w~rd!*'()", "X7kQ"),
            "challenge=&username=admin&password=p%40ss+w%7Erd%21*%27%28%29&captchaTextBox=X7kQ"
            "&save=Login&submit-url=%2Fadmin%2Flogin.asp&postSecurityFlag=26329")

    def test_enc(self):
        self.assertEqual(gx_gpon.enc("a b~c*d!'()/@"), "a+b%7Ec*d%21%27%28%29%2F%40")

    def test_captcha_regex(self):
        self.assertEqual(gx_gpon.CAPTCHA_RE.search('var x; code = "Ab12";').group(1), "Ab12")


class MonitorLogic(unittest.TestCase):
    def run_steps(self, mon, steps, lr=None):
        out = []
        for now, router, internet in steps:
            out += mon.step(now, router, internet, (lambda: lr) if lr else None)
        return out

    def test_alert_after_three_fails_then_recover(self):
        evs = self.run_steps(Monitor(), [(1000, True, True), (1005, True, False), (1008, True, False),
                                         (1011, True, False), (1014, True, False), (1020, True, True)])
        self.assertEqual(evs, [("alert", 1005), ("recovered", 1005, 1020)])

    def test_no_alert_while_router_down(self):
        self.assertEqual(self.run_steps(Monitor(), [(t, False, False) for t in range(1000, 1030, 3)]), [])

    def test_quiet_after_own_restart(self):
        steps = [(1000 + i * 3, True, False) for i in range(10)]
        self.assertEqual(self.run_steps(Monitor(), steps, lr=990), [])

    def test_quiet_after_router_was_down(self):
        steps = [(1000, False, False)] + [(1003 + i * 3, True, False) for i in range(10)]
        self.assertEqual(self.run_steps(Monitor(), steps), [])

    def test_sleep_resets_alerted_outage(self):
        m = Monitor()
        evs = self.run_steps(m, [(1000, True, False), (1003, True, False), (1006, True, False), (5000, True, False)])
        self.assertEqual(evs, [("alert", 1000), ("reset", 1000, 1006)])
        self.assertFalse(m.alerted)


class EventStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "events.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_and_partial_line(self):
        events.record("reboot", path=self.path, ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write('{"ts": 12, "kind": "reb')                # another process mid-write
        evs = events.read_events(path=self.path)
        self.assertEqual(len(evs), 1)
        self.assertEqual(events.last_reboot(evs), evs[0]["ts"])

    def test_uptime(self):
        now = 1_000_000.0
        evs = [{"ts": now - 7200, "kind": "outage_start", "since": now - 7300},
               {"ts": now - 7000, "kind": "outage_end", "since": now - 7300, "until": now - 7000},
               {"ts": now - 90000, "kind": "outage_start", "since": now - 90000},       # outside the window
               {"ts": now - 89000, "kind": "outage_end", "since": now - 90000, "until": now - 89000},
               {"ts": now - 60, "kind": "outage_start", "since": now - 60},             # ongoing
               {"ts": now - 3600, "kind": "reboot", "ok": True}]
        s = events.uptime_summary(evs, now)
        self.assertEqual(len(s["outages"]), 2)
        self.assertAlmostEqual(s["down_seconds"], 360)
        self.assertTrue(s["ongoing"])
        self.assertEqual(s["reboots"], [now - 3600])
        s2 = events.uptime_summary(evs, now, ongoing_ok=False)
        self.assertAlmostEqual(s2["down_seconds"], 300)

    def test_log_parse_and_tail(self):
        log = Path(self.tmp.name) / "x.log"
        log.write_text("2026-10-21 15:00:02,268 INFO [reboot] logged in\n"
                       "2026-10-21 15:00:03,000 WARNING [watchdog] something\nplain line\n", encoding="utf-8")
        tail = events.read_log_tail(path=log)
        self.assertEqual(tail[0].message, "plain line")
        self.assertEqual((tail[1].level, tail[1].source), ("WARNING", "watchdog"))
        self.assertEqual(tail[2].time, datetime(2026, 10, 21, 15, 0, 2))


class Config(unittest.TestCase):
    def write(self, data) -> Path:
        d = tempfile.mkdtemp()
        p = Path(d) / "config.json"
        p.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
        return p

    def test_valid(self):
        cfg = config.load_config(self.write({**_setup.TEST_CONFIG, "router_url": "http://192.0.2.1:8080/"}))
        self.assertEqual((cfg.router_url, cfg.router_host, cfg.router_port), ("http://192.0.2.1:8080", "192.0.2.1", 8080))
        self.assertEqual((cfg.interval_days, cfg.restart_time), (3, "04:00"))
        self.assertIs(cfg.tls_verify, True)

    def test_shipped_example_is_valid(self):
        example = _setup.REPO / "config" / "config.example.json"
        cfg, problems = config.parse_config(json.loads(example.read_text(encoding="utf-8")))
        self.assertEqual(problems, [])
        self.assertEqual((cfg.router_url, cfg.username), ("http://192.0.2.1", "YOUR_ROUTER_USERNAME"))

    def test_missing_file(self):
        with self.assertRaises(config.ConfigError) as cm:
            config.load_config(Path(tempfile.mkdtemp()) / "nope.json")
        self.assertIn("Configure.ps1", str(cm.exception))

    def test_bom_is_tolerated(self):
        p = self.write("\ufeff" + json.dumps(_setup.TEST_CONFIG))
        self.assertEqual(config.load_config(p).router_model, "gx-gpon-e4222")

    def test_problems_are_reported(self):
        bad = {"router_url": "http://user:pw@192.0.2.1", "router_model": "no-such-router", "interval_days": 0,
               "restart_time": "4:00", "warn_minutes": "x", "bogus": 1, "_comment": "ignored"}
        cfg, problems = config.parse_config(bad)
        text = "\n".join(problems)
        for needle in ("router_url", "no-such-router", "interval_days", "restart_time", "warn_minutes", "bogus"):
            self.assertIn(needle, text)
        self.assertNotIn("_comment", text)
        with self.assertRaises(config.ConfigError):
            config.load_config(self.write(bad))

    def test_required_fields(self):
        _, problems = config.parse_config({})
        self.assertTrue(any("router_url" in p for p in problems))
        self.assertTrue(any("router_model" in p for p in problems))

    def test_env_override(self):
        with mock.patch.dict(os.environ, {"ROUTER_URL": "https://192.0.2.9", "ROUTER_USER": "someone"}):
            cfg, problems = config.parse_config(dict(_setup.TEST_CONFIG))
        self.assertEqual((problems, cfg.router_url, cfg.username, cfg.router_port), ([], "https://192.0.2.9", "someone", 443))

    def test_ca_bundle_must_exist(self):
        _, problems = config.parse_config({**_setup.TEST_CONFIG, "tls_ca_bundle": "Z:/missing.pem"})
        self.assertTrue(any("tls_ca_bundle" in p for p in problems))


class Scheduler(unittest.TestCase):
    def test_quote(self):
        self.assertEqual(scheduler.q("it's"), "'it''s'")

    def test_parse_query(self):
        out = json.dumps({"state": "Ready", "last": "2026-10-21T14:50:00", "result": 0,
                          "next": "2026-10-24T14:50:00", "missed": 0, "days": 3,
                          "at": "2026-10-18T14:50:00+05:30", "args": '"x.py" reboot --prompt --warn-minutes 7.5'})
        d = scheduler.parse_query(out)
        self.assertEqual(d["next"], datetime(2026, 10, 24, 14, 50))
        self.assertEqual((d["at"], d["days"], d["warn"]), ("14:50", 3, 7.5))
        self.assertEqual(scheduler.parse_query('{"missing":true}'), {"missing": True})

    def test_task_script_contents(self):
        s = scheduler.reboot_task_script("RouterAutoRestart-SelfTest", "04:00", 3, 10)
        self.assertIn("-DaysInterval 3 -At '04:00'", s)
        self.assertIn("-LogonType Interactive -RunLevel Limited", s)
        self.assertIn("reboot --prompt --warn-minutes 10", s)
        self.assertIn("-MultipleInstances IgnoreNew", s)
        self.assertNotIn("RestartCount", s)            # never auto-retried
        self.assertNotIn("password", s.lower())

    def test_bad_inputs(self):
        for args in (("t", "25:00", 3, 10), ("t", "4:00", 3, 10), ("t", "14:50", 0, 10), ("t", "14:50", 3, 500)):
            with self.assertRaises(ValueError):
                scheduler.reboot_task_script(*args)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_task_definitions_build(self):
        """Runs the New-ScheduledTask* part of each script without registering anything."""
        for script in (scheduler.reboot_task_script("RouterAutoRestart-SelfTest", "04:00", 3, 10, register=False),
                       scheduler.watchdog_task_script("RouterAutoRestart-SelfTest", register=False)):
            p = scheduler.ps(script)
            self.assertEqual((p.returncode, p.stdout.strip()), (0, "ok"), p.stderr)

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_query_missing_task(self):
        self.assertEqual(scheduler.query_task("RouterAutoRestart-no-such-task-%d" % time.time()), {"missing": True})


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class Credentials(unittest.TestCase):
    TARGET = "RouterAutoRestart:selftest"

    def test_roundtrip(self):
        from routerkit import credentials as c
        try:
            c.vault_write("pä$$ wörd \u2713", "admin", target=self.TARGET)
            self.assertEqual(c.vault_read(self.TARGET), "pä$$ wörd \u2713")
        finally:
            self.assertTrue(c.vault_delete(self.TARGET))
        self.assertIsNone(c.vault_read(self.TARGET))
        self.assertFalse(c.vault_delete(self.TARGET))


class Util(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(dur(9), "9s")
        self.assertEqual(dur(252), "4m 12s")
        self.assertEqual(dur(3900), "1h 05m")
        self.assertEqual(fmt(datetime(2026, 10, 24, 14, 50)), "Sat 24 Oct, 2:50 PM")


if __name__ == "__main__":
    unittest.main()
