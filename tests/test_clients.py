"""Connected clients and internet blocking - against a simulated GX GPON router whose pages have
the same shape as the real ones (documentation MAC/IP addresses only). Nothing here opens a real
connection to a router."""
import _setup  # noqa: F401  (must come first)

import unittest
from unittest import mock
from urllib.parse import parse_qsl

from routerkit import actions, events
from routerkit.routers import RouterError
from routerkit.routers.base import norm_mac
from routerkit.routers.gx_gpon import (build_clients, form_body, parse_dhcp, parse_parental, parse_radio,
                                       parse_stations, post_security_flag, rule_name)
from test_router_mock import CFG, FAKE_PW, LOGGED_IN, LOGIN_PAGE, FakeSession, Resp, adapter

PHONE, PC, LAPTOP, TABLET = ("00:00:5e:00:53:01", "00:00:5e:00:53:02", "00:00:5e:00:53:03",
                             "00:00:5e:00:53:04")


def wlstatus(band_flag, main, extra, extra_n, main_disabled=0):
    """Same assignments wlstatus.asp writes into its script."""
    return f"""<script>
 var wlan_num = 1;
 wlanMode[0]=0;
\tband[0]=76;
\tssid_drv[0]='{main}';
\tclientnum[0]='2';
\twlanDisabled[0]={main_disabled};
\tmssid_num=4;
\tmssid_ssid_drv[0]='{extra}';
\tmssid_disable[0]=0;
\tmssid_clientnum[0]='{extra_n}';
\tmssid_disable[1]=1;
\tmssid_disable[2]=1;
\tmssid_disable[3]=1;
\tBand2G5GSupport={band_flag};
</script>"""


def wlstatbl(*macs):
    rows = "".join(f"<tr><td>{m}</td><td>18027</td><td>17684</td><td>866</td><td>yes</td><td>300</td></tr>"
                   for m in macs)
    return f'<form action=/boaform/admin/formWirelessTbl method=POST><table><tr><th>MAC Address</th></tr>{rows}</table>'


def dhcp(*rows):
    body = "".join(f"<tr><td>{m}</td><td>{ip}</td><td>{name}</td><td>{band}</td><td>{rssi}</td><td>-1</td></tr>"
                   for m, ip, name, band, rssi in rows)
    return (f"<p>Active DHCP Clients</p><table><tr><th>MAC Address</th></tr>{body}</table>"
            "<p>Active STATIC Clients</p><table><tr><th>MAC Address</th></tr>"
            "<tr><td>NONE</td><td>----</td><td>----</td><td>----</td><td>----</td><td>----</td></tr></table>")


def parental(on, rules):
    """rules: [(name, mac with dashes)] as the router lists them."""
    rows = "".join(
        f'<tr><td align=center><font size="2">{name}</font></td><td align=center><font size="2"></font></td>'
        f'<td align=center><font size="2">{mac}</font></td>'
        + '<td align=center><font size="2">v</font></td>' * 7
        + '<td align=center><font size="2">00:00</font></td><td align=center><font size="2">23:59</font></td>'
        f'<td align=center><input type="checkbox" name="select{i}" value="ON"></td></tr>'
        for i, (name, mac) in enumerate(rules))
    return f"""<form action=/boaform/admin/formParentCtrl method=POST name="formParentCtrl">
   <input type="radio" value="0" name="parental_ctrl_on" {"" if on else "checked"} >Disable&nbsp;&nbsp;
   <input type="radio" value="1" name="parental_ctrl_on" {"checked" if on else ""} >Enable&nbsp;&nbsp;
</form>
<form action=/boaform/admin/formParentCtrl method=POST name="formParentCtrlDel">
 <table>
<tr><td align=center width="12%" bgcolor="#808080"><font size="2"><b>Name</b></font></td></tr>
{rows}
  </table>
</form>"""


class Router:
    """Stateful fake: two radios, DHCP table, Parental Control switch and rules."""

    def __init__(self, on=False, rules=None, keep_changes=True):
        self.on, self.rules, self.keep = on, list(rules or []), keep_changes
        self.radio = 0
        self.stations = {0: [PHONE, PC], 1: []}
        self.extras = {0: ("Home-Work-5G", 1), 1: ("Home-Work-2G", 0)}
        self.leases = [(PHONE.upper(), "192.0.2.10", "phone", "5GHz", "-56"),
                       (PC.upper(), "192.0.2.11", "pc", "5GHz", "-47"),
                       (LAPTOP.upper(), "192.0.2.12", "work-laptop", "5GHz", "-60")]
        self.posts = []

    def __call__(self, method, path, data):
        if method == "GET" and path == "/admin/login.asp":
            return Resp(LOGIN_PAGE)
        if path == "/boaform/admin/formLogin":
            return Resp(LOGGED_IN)
        if path == "/boaform/admin/formLogout":
            return Resp("bye")
        if path.startswith("/boaform/formWlanRedirect?redirect-url=/wlstatus.asp&wlan_idx="):
            self.radio = int(path[-1])
            band = 2 if self.radio == 0 else 1
            name, n = self.extras[self.radio]
            return Resp(wlstatus(band, f"Home-{'5G' if band == 2 else '2G'}", name, n))
        if path.startswith("/boaform/admin/formWirelessTbl"):
            return Resp(wlstatbl(*self.stations[self.radio]))     # session's radio, not the query's
        if path == "/status_client_list.asp":
            return Resp(dhcp(*self.leases))
        if path == "/parental-ctrl.asp":
            return Resp(parental(self.on, self.rules))
        if path == "/boaform/admin/formParentCtrl":
            self.posts.append(data)
            if self.keep:
                self.apply(dict(parse_qsl(data)))
            return Resp("Change setting successfully!")
        return Resp("not found", 404)

    def apply(self, f):
        if "parentalCtrlSet" in f:
            self.on = f["parental_ctrl_on"] == "1"
        elif "addfilterMac" in f:
            mac = "-".join(f["mac"][i:i + 2] for i in range(0, 12, 2)).lower()
            self.rules.append((f["usrname"], mac))
        elif "deleteSelFilterMac" in f:
            picked = [int(k[6:]) for k in f if k.startswith("select")]
            self.rules = [r for i, r in enumerate(self.rules) if i not in picked]


def dashed(mac):
    return mac.replace(":", "-")


class Parsing(unittest.TestCase):
    def test_norm_mac(self):
        self.assertEqual(norm_mac("00-00-5E-00-53-01"), PHONE)
        self.assertEqual(norm_mac("00005E005301"), PHONE)
        for bad in ("", "00:00:5e:00:53", "zz:00:5e:00:53:01", "00:00:5e:00:53:01:02"):
            with self.assertRaises(ValueError):
                norm_mac(bad)

    def test_form_body_matches_router_checksum(self):
        body = form_body([("parental_ctrl_on", "1"), ("parentalCtrlSet", "Apply Changes"),
                          ("submit-url", "/parental-ctrl.asp")])
        head = "parental_ctrl_on=1&parentalCtrlSet=Apply+Changes&submit-url=%2Fparental-ctrl.asp&"
        self.assertEqual(body, head + f"postSecurityFlag={post_security_flag(head)}")

    def test_radio_and_tables(self):
        r = parse_radio(wlstatus(2, "Home-5G", "Work-5G", 1))
        self.assertEqual(r, {"band": "5 GHz", "main": "Home-5G", "extras": [("Work-5G", 1)]})
        self.assertEqual(parse_radio(wlstatus(1, "Home-2G", "Work-2G", 0, main_disabled=1))["main"], "")
        with self.assertRaises(RouterError):
            parse_radio("<html>no script</html>")
        self.assertEqual(parse_stations(wlstatbl(PHONE.upper(), PC)), [PHONE, PC])
        rows = parse_dhcp(dhcp((PHONE, "192.0.2.10", "phone", "5GHz", "-56"),
                               (PC, "192.0.2.11", "----", "2.4GHz", "----")))
        self.assertEqual(rows, [{"mac": PHONE, "ip": "192.0.2.10", "name": "phone", "band": "5 GHz", "rssi": "-56"},
                                {"mac": PC, "ip": "192.0.2.11", "name": "", "band": "2.4 GHz", "rssi": ""}])

    def test_parental(self):
        on, rules = parse_parental(parental(True, [("kids-tv", dashed(PHONE)), (rule_name(PC), dashed(PC))]))
        self.assertTrue(on)
        self.assertEqual(rules, [{"select": "select0", "name": "kids-tv", "mac": PHONE},
                                 {"select": "select1", "name": "RC-00005e005302", "mac": PC}])
        self.assertEqual(parse_parental(parental(False, []))[0], False)
        with self.assertRaises(RouterError):
            parse_parental("<html>login</html>")


class Grouping(unittest.TestCase):
    RADIO5 = {"band": "5 GHz", "main": "Home-5G", "extras": [("Work-5G", 1)]}
    RADIO2 = {"band": "2.4 GHz", "main": "Home-2G", "extras": [("Work-2G", 0)]}
    LEASES = [{"mac": PHONE, "ip": "192.0.2.10", "name": "phone", "band": "5 GHz", "rssi": "-56"},
              {"mac": LAPTOP, "ip": "192.0.2.12", "name": "laptop", "band": "5 GHz", "rssi": "-60"}]

    def test_extra_ssid_assigned_when_count_matches(self):
        cl = build_clients([self.RADIO5, self.RADIO2], [[PHONE], []], self.LEASES, {PHONE, TABLET})
        self.assertEqual([(s.name, s.can_block, [c.mac for c in s.clients]) for s in cl.ssids],
                         [("Home-5G", True, [PHONE]), ("Work-5G", False, [LAPTOP]),
                          ("Home-2G", True, []), ("Work-2G", False, [])])
        self.assertTrue(cl.ssids[0].clients[0].blocked)
        self.assertEqual(cl.ssids[0].clients[0].name, "phone")
        self.assertEqual(cl.unknown, [])
        self.assertEqual([(c.mac, c.blocked) for c in cl.blocked_offline], [(TABLET, True)])

    def test_count_mismatch_is_not_guessed(self):
        radio = dict(self.RADIO5, extras=[("Work-5G", 2)])          # router says 2, only 1 left over
        cl = build_clients([radio], [[PHONE]], self.LEASES, set())
        self.assertEqual([(s.name, s.clients) for s in cl.ssids], [("Home-5G", cl.ssids[0].clients), ("Work-5G", [])])
        self.assertEqual([c.mac for c in cl.unknown], [LAPTOP])
        self.assertEqual([s.reported for s in cl.ssids], [1, 2])     # the router's count is kept

    def test_counted_but_unlisted_device(self):
        # the real router: the work SSID counts 1 device that has no DHCP lease (fixed IP / own DHCP)
        cl = build_clients([self.RADIO5], [[PHONE]], self.LEASES[:1], set())
        work = cl.ssids[1]
        self.assertEqual((work.name, work.clients, work.reported), ("Work-5G", [], 1))
        self.assertEqual(cl.unknown, [])

    def test_station_without_lease_still_listed(self):
        cl = build_clients([dict(self.RADIO5, extras=[])], [[PC]], [], set())
        self.assertEqual([(c.mac, c.name) for c in cl.ssids[0].clients], [(PC, "")])


class AdapterClients(unittest.TestCase):
    def run_on(self, fake, fn):
        a, s = adapter(fake)
        with a:
            a.login()
            out = fn(a)
        return out, s

    def test_list_reads_each_radio_before_its_table_and_logs_out(self):
        fake = Router(on=True, rules=[(rule_name(PHONE), dashed(PHONE))])
        cl, s = self.run_on(fake, lambda a: a.list_clients())
        self.assertEqual(s.paths()[2:], [
            "GET /boaform/formWlanRedirect?redirect-url=/wlstatus.asp&wlan_idx=0",
            "GET /boaform/admin/formWirelessTbl?submit-url=/admin/wlstatbl.asp&wlan_idx=0",
            "GET /boaform/formWlanRedirect?redirect-url=/wlstatus.asp&wlan_idx=1",
            "GET /boaform/admin/formWirelessTbl?submit-url=/admin/wlstatbl.asp&wlan_idx=1",
            "GET /status_client_list.asp", "GET /parental-ctrl.asp", "POST /boaform/admin/formLogout"])
        self.assertEqual([c.mac for c in cl.ssids[0].clients], [PHONE, PC])
        self.assertTrue(cl.ssids[0].clients[0].blocked)
        self.assertEqual([(s.name, [c.mac for c in s.clients]) for s in cl.ssids[1:2]], [("Home-Work-5G", [LAPTOP])])
        self.assertEqual(fake.posts, [])                           # listing never changes anything

    def test_rule_with_switch_off_is_not_shown_as_blocked(self):
        cl, _ = self.run_on(Router(on=False, rules=[(rule_name(PHONE), dashed(PHONE))]), lambda a: a.list_clients())
        self.assertFalse(cl.ssids[0].clients[0].blocked)

    def test_block_turns_switch_on_and_adds_all_day_rule(self):
        fake = Router(on=False)
        self.run_on(fake, lambda a: a.set_blocked(PHONE, True))
        self.assertTrue(fake.on)
        self.assertEqual(fake.rules, [("RC-00005e005301", dashed(PHONE))])
        on_body, add_body = fake.posts
        self.assertTrue(on_body.startswith("parental_ctrl_on=1&parentalCtrlSet=Apply+Changes&submit-url=%2Fparental-ctrl.asp&postSecurityFlag="))
        self.assertTrue(add_body.startswith(
            "usrname=RC-00005e005301&specPC=1&mac=00005E005301&Sun=on&Mon=on&Tue=on&Wed=on&Thu=on&Fri=on&Sat=on"
            "&starthr=00&startmin=00&endhr=23&endmin=59&addfilterMac=Add&submit-url=%2Fparental-ctrl.asp&postSecurityFlag="))
        for body in fake.posts:
            head, flag = body.rsplit("postSecurityFlag=", 1)
            self.assertEqual(int(flag), post_security_flag(head))
            self.assertNotIn("ipstart", body)

    def test_block_twice_adds_one_rule(self):
        fake = Router(on=True, rules=[(rule_name(PHONE), dashed(PHONE))])
        self.run_on(fake, lambda a: a.set_blocked(PHONE, True))
        self.assertEqual(fake.posts, [])
        self.assertEqual(len(fake.rules), 1)

    def test_block_not_kept_raises(self):
        with self.assertRaises(RouterError):
            self.run_on(Router(on=True, keep_changes=False), lambda a: a.set_blocked(PHONE, True))

    def test_unblock_last_rule_switches_off(self):
        fake = Router(on=True, rules=[(rule_name(PHONE), dashed(PHONE))])
        self.run_on(fake, lambda a: a.set_blocked(PHONE, False))
        self.assertEqual(fake.rules, [])
        self.assertFalse(fake.on)
        self.assertTrue(fake.posts[0].startswith("select0=ON&deleteSelFilterMac=Delete+Selected&submit-url=%2Fparental-ctrl.asp&"))

    def test_unblock_leaves_hand_made_rules_and_switch(self):
        hand = ("kids-tv", dashed(PHONE))                     # same device, rule made in the router's page
        fake = Router(on=True, rules=[hand, ("other", dashed(PC)), (rule_name(PHONE), dashed(PHONE))])
        self.run_on(fake, lambda a: a.set_blocked(PHONE, False))
        self.assertEqual(fake.rules, [hand, ("other", dashed(PC))])
        self.assertTrue(fake.on)
        self.assertTrue(fake.posts[0].startswith("select2=ON&"))

    def test_unblock_not_kept_raises(self):
        with self.assertRaises(RouterError):
            self.run_on(Router(on=True, rules=[(rule_name(PHONE), dashed(PHONE))], keep_changes=False),
                        lambda a: a.set_blocked(PHONE, False))

    def test_unblock_when_not_blocked_changes_nothing(self):
        fake = Router(on=False)
        self.run_on(fake, lambda a: a.set_blocked(PHONE, False))
        self.assertEqual(fake.posts, [])

    def test_session_ended_is_an_error(self):
        def handler(method, path, data):
            if path == "/boaform/admin/formLogin":
                return Resp(LOGGED_IN)
            if path in ("/admin/login.asp", "/parental-ctrl.asp"):
                return Resp(LOGIN_PAGE.replace("<form>", '<form action="/boaform/admin/formLogin">'))
            return Resp("bye")
        with self.assertRaises(RouterError) as cm:
            self.run_on(handler, lambda a: a.set_blocked(PHONE, True))
        self.assertIn("ended the admin session", str(cm.exception))


class Actions(unittest.TestCase):
    def setUp(self):
        p = mock.patch("routerkit.credentials.get_password", return_value=(FAKE_PW, "test"))
        p.start()
        self.addCleanup(p.stop)

    def test_bad_mac_never_reaches_the_router(self):
        s = FakeSession(Router())
        rc, err = actions.set_blocked(CFG, "not-a-mac", True, session=s)
        self.assertEqual(rc, actions.FAILED)
        self.assertIn("not a MAC", err)
        self.assertEqual(s.calls, [])

    def test_block_records_event(self):
        fake = Router()
        rc, _ = actions.set_blocked(CFG, PHONE.upper(), True, session=FakeSession(fake))
        self.assertEqual(rc, actions.OK)
        ev = [e for e in events.read_events() if e["kind"] == "block"][-1]
        self.assertEqual((ev["ok"], ev["mac"]), (True, PHONE))

    def test_busy_session_message(self):
        def busy(method, path, data):
            return Resp(LOGIN_PAGE) if path == "/admin/login.asp" else Resp("you have logined")
        rc, err = actions.list_clients(CFG, session=FakeSession(busy))
        self.assertEqual(rc, actions.FAILED)
        self.assertIn("admin session open", err)

    def test_no_password(self):
        with mock.patch("routerkit.credentials.get_password", return_value=(None, "not set")):
            self.assertEqual(actions.list_clients(CFG)[0], actions.NO_PASSWORD)


if __name__ == "__main__":
    unittest.main()
