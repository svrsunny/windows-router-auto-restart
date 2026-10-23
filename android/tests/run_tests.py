"""Run the PC-side tests: protocol parity with the PC adapter, tracker logic, client vs fake router.

usage: python3 run_tests.py <classes-dir> <reference .py>
<reference .py> is the PC adapter, src/routerkit/routers/gx_gpon.py. It is only read: its
protocol functions (enc, _int32, post_security_flag, build_login_body) are run from its source text.
"""
import ast
import base64
import os
import random
import subprocess
import sys
import tempfile
from urllib.parse import quote_plus

import mock_router

CLASSES, PC_SCRIPT = sys.argv[1], sys.argv[2]
JAVA = ["java", "-cp", CLASSES, "com.sunny.routerwatch.TestMain"]
ENV = dict(os.environ)
ENV.pop("JAVA_TOOL_OPTIONS", None)
fails = 0


def report(ok, what):
    global fails
    print(("PASS " if ok else "FAIL ") + what)
    if not ok:
        fails += 1


# --- reference implementation: the PC adapter's own functions ---
src = open(PC_SCRIPT, encoding="utf-8").read()
tree = ast.parse(src)
ns = {"quote_plus": quote_plus}
wanted = {"enc", "_int32", "post_security_flag", "form_body", "build_login_body"}
code = ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted], type_ignores=[])
exec(compile(code, PC_SCRIPT, "exec"), ns)
assert wanted <= set(ns), "protocol functions not found in " + PC_SCRIPT


def run_java(*args):
    p = subprocess.run(JAVA + list(args), capture_output=True, text=True, env=ENV, timeout=120)
    return p.returncode, p.stdout, p.stderr


# 1. protocol parity
random.seed(7)
alphabet = (" ~*!@#$%^&()_+-=[]{};:'\",.<>/?\\|`" + "abcXYZ0129" + "éß€😀")
cases = [("admin", "p@ss w0rd~*", "Ab3x9", ""), ("admin", "", "", "x"), ("", "~~~", "a b", "ab"),
         ("admin", "pässwörd€", "QQQQ", "abc"), ("admin", "a+b=c&d", "1234", "abcd")]
for _ in range(300):
    pick = lambda n: "".join(random.choice(alphabet) for _ in range(random.randint(0, n)))
    cases.append((pick(12), pick(24), pick(8), pick(60)))
b64 = lambda s: base64.b64encode(s.encode("utf-8")).decode()
with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as f:
    for u, pw, cap, body in cases:
        f.write(" ".join((b64(u), b64(pw), b64(cap), b64(body))) + "\n")
    case_file = f.name
rc, out, err = run_java("protocol", case_file)
lines = out.splitlines()
report(rc == 0 and len(lines) == len(cases), "java ran %d protocol cases" % len(cases))
mism = 0
for (u, pw, cap, body), line in zip(cases, lines):
    # the flag is computed over an encoded (ASCII) body in practice; compare on ASCII-only bodies
    exp_flag = ns["post_security_flag"](body) if all(ord(ch) < 0x10000 for ch in body) else None
    enc_j, flag_j, login_j = line.split(" ", 2)
    ok = enc_j == ns["enc"](pw) and login_j == ns["build_login_body"](u, pw, cap)
    if exp_flag is not None:
        ok = ok and int(flag_j) == exp_flag
    if not ok:
        mism += 1
        if mism < 5:
            print("  mismatch:", repr((u, pw, cap, body)), line)
report(mism == 0, "enc / postSecurityFlag / login body identical to " + os.path.basename(PC_SCRIPT))
report(ns["post_security_flag"]("") == 65535, "empty-body flag is 65535 (reboot request)")

# 2. tracker
rc, out, err = run_java("tracker")
print(out.strip())
report(rc == 0, "tracker scenarios")

# 3. client against the mock router
def scenario(name, router, user, pw, action, expect_result, expect_events):
    srv = mock_router.serve(router)
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    rc, out, err = run_java("client", url, user, pw, action)
    srv.shutdown()
    res = next((l for l in out.splitlines() if l.startswith("RESULT")), "RESULT none " + err[-300:])
    ok = res.startswith("RESULT " + expect_result) and router.events == expect_events
    report(ok, "%s -> %s, events %s" % (name, res[:90], router.events))


flag = ns["post_security_flag"]
scenario("reboot, redirect after login", mock_router.Router(flag), "admin", "p@ss w0rd~*", "reboot", "ok",
         ["login_ok", "reboot"])
scenario("reboot, no redirect", mock_router.Router(flag, redirect=False), "admin", "p@ss w0rd~*", "reboot", "ok",
         ["login_ok", "reboot"])
scenario("login test logs out", mock_router.Router(flag), "admin", "p@ss w0rd~*", "dry", "ok",
         ["login_ok", "logout"])
scenario("wrong password", mock_router.Router(flag), "admin", "nope", "reboot", "error The router rejected",
         ["login_bad", "login_bad", "login_bad"])
scenario("unicode password", mock_router.Router(flag, password="pässwörd€ 1~"), "admin", "pässwörd€ 1~", "reboot",
         "ok", ["login_ok", "reboot"])
scenario("session busy", mock_router.Router(flag, busy=True), "admin", "p@ss w0rd~*", "reboot", "busy", ["busy"])

PHONE, PC, LAPTOP = mock_router.PHONE, mock_router.PC, mock_router.LAPTOP
rule = lambda mac: ("RC-" + mac.replace(":", ""), mac.replace(":", "-"))  # noqa: E731
scenario("block: switch on + all-day rule", mock_router.Router(flag), "admin", "p@ss w0rd~*", "block:" + PHONE.upper(),
         "ok", ["login_ok", "pc_on", "add:RC-00005e005301", "logout"])
scenario("block twice: no second rule", mock_router.Router(flag, parental_on=True, rules=[rule(PHONE)]), "admin",
         "p@ss w0rd~*", "block:" + PHONE, "ok", ["login_ok", "logout"])
scenario("unblock last rule: switch off", mock_router.Router(flag, parental_on=True, rules=[rule(PHONE)]), "admin",
         "p@ss w0rd~*", "unblock:" + PHONE, "ok", ["login_ok", "del:RC-00005e005301", "pc_off", "logout"])
scenario("unblock keeps hand-made rules", mock_router.Router(flag, parental_on=True,
                                                             rules=[("kids-tv", PHONE.replace(":", "-")), rule(PHONE)]),
         "admin", "p@ss w0rd~*", "unblock:" + PHONE, "ok", ["login_ok", "del:RC-00005e005301", "logout"])
scenario("bad MAC refused", mock_router.Router(flag), "admin", "p@ss w0rd~*", "block:nope", "error not a MAC",
         ["login_ok", "logout"])

# 3b. Wi-Fi clients: Java and the PC adapter group the same pages the same way
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(PC_SCRIPT)))))
from routerkit.routers import gx_gpon  # noqa: E402


def py_dump(cl):
    out = []
    row = lambda c: "C|%s|%s|%s|%s|%d" % (c.mac, c.name, c.ip, c.rssi, c.blocked)  # noqa: E731
    for s in cl.ssids:
        out.append("SSID|%s|%s|%d|%d" % (s.name, s.band, s.can_block, s.reported))
        out += [row(c) for c in s.clients]
    out.append("UNKNOWN")
    out += [row(c) for c in cl.unknown]
    out.append("OFFLINE")
    out += [row(c) for c in cl.blocked_offline]
    return "\n".join(out) + "\n"


def py_group(pages):
    radios = [gx_gpon.parse_radio(pages["radio%d" % i]) for i in (0, 1)]
    stations = [gx_gpon.parse_stations(pages["tbl%d" % i]) for i in (0, 1)]
    on, rules = gx_gpon.parse_parental(pages["parental"])
    blocked = {r["mac"] for r in rules if on and r["mac"] and r["name"].startswith("RC-")}
    return py_dump(gx_gpon.build_clients(radios, stations, gx_gpon.parse_dhcp(pages["dhcp"]), blocked))


macs = ["00:00:5e:00:53:%02x" % i for i in range(1, 9)]
names = ["phone", "pc", "----", "Tv &amp; box", "", "work-laptop", "a b", "x"]
mism = 0
for case in range(60):
    r = random.Random(case)
    leased = r.sample(macs, r.randint(0, 6))
    leases = [((m.upper() if r.random() < 0.5 else m), "192.0.2.%d" % (10 + i), r.choice(names),
               r.choice(["5GHz", "2.4GHz", "LAN"]), r.choice(["-56", "----"])) for i, m in enumerate(leased)]
    st0 = r.sample(macs, r.randint(0, 3))
    st1 = r.sample([m for m in macs if m not in st0], r.randint(0, 2))
    on = r.random() < 0.7
    rules = [(("RC-" if r.random() < 0.7 else "hand-") + m.replace(":", ""), m.replace(":", "-"))
             for m in r.sample(macs, r.randint(0, 3))]
    pages = {"radio0": mock_router.wlstatus(2, "Home 5G", "Work-5G", r.randint(0, 3), main_disabled=int(r.random() < 0.1)),
             "radio1": mock_router.wlstatus(1, "Home-2G", "Work-2G", r.randint(0, 2)),
             "tbl0": mock_router.wlstatbl(st0), "tbl1": mock_router.wlstatbl(st1),
             "dhcp": mock_router.dhcp(leases), "parental": mock_router.parental(on, rules)}
    d = tempfile.mkdtemp(prefix="rc-pages-")
    for k, v in pages.items():
        with open(os.path.join(d, k + ".html"), "w", encoding="utf-8") as f:
            f.write(v)
    rc, out, err = run_java("group", d)
    exp = py_group(pages)
    if rc != 0 or out != exp:
        mism += 1
        if mism < 3:
            print("  case %d differs:\n--- java\n%s%s--- pc\n%s" % (case, out, err[-300:], exp))
report(mism == 0, "Wi-Fi client grouping identical to the PC adapter (60 page sets)")

srv = mock_router.serve(mock_router.Router(flag, parental_on=True, rules=[rule(PHONE)]))
rc, out, err = run_java("client", "http://127.0.0.1:%d/" % srv.server_address[1], "admin", "p@ss w0rd~*", "list")
srv.shutdown()
expected = py_group({"radio0": mock_router.wlstatus(2, "Home-5G", "Home-Work-5G", 1),
                     "radio1": mock_router.wlstatus(1, "Home-2G", "Home-Work-2G", 0),
                     "tbl0": mock_router.wlstatbl([PHONE.upper(), PC]), "tbl1": mock_router.wlstatbl([]),
                     "dhcp": mock_router.dhcp(mock_router.Router(flag).leases),
                     "parental": mock_router.parental(True, [rule(PHONE)])})
report(out == expected + "RESULT ok\n", "list over HTTP: radio selected before its station table, phone blocked")
if out != expected + "RESULT ok\n":
    print(out, err[-500:])

# 4. router unreachable
rc, out, err = run_java("client", "http://127.0.0.1:9/", "admin", "x", "reboot")
report("RESULT error Can't reach the router" in out, "unreachable router -> clear error: " + out.strip()[:100])

# 5. probe
srv = mock_router.serve(mock_router.Router(flag))
rc, out, err = run_java("probe", "127.0.0.1", str(srv.server_address[1]))
report(out.startswith("PROBE ") and int(out.split()[1]) >= 0, "probe open port: " + out.strip())
srv.shutdown()
rc, out, err = run_java("probe", "127.0.0.1", "9")
report(out.strip() == "PROBE -1", "probe closed port: " + out.strip())

print("\nALL PASSED" if fails == 0 else "\n%d FAILED" % fails)
sys.exit(1 if fails else 0)
