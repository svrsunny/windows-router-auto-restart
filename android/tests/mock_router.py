"""A fake GX router web UI for testing the app's login / reboot code on a PC.

Behaves like the real one as captured for the PC scripts: captcha text in login.asp, a session
cookie, postSecurityFlag checksum on every form post, single admin session, and the connection
dropping on reboot. Each checksum is verified with the PC adapter's own post_security_flag().
Also serves the Wi-Fi status / station / DHCP / Parental Control pages in the real pages' shape
(documentation MAC and IP addresses only).
"""
import random
import string
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl

PHONE, PC, LAPTOP = "00:00:5e:00:53:01", "00:00:5e:00:53:02", "00:00:5e:00:53:03"


# ---------- page shapes (same as the real router's) ----------

def wlstatus(band_flag, main, extra, extra_n, main_disabled=0):
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


def wlstatbl(macs):
    rows = "".join(f"<tr><td>{m}</td><td>18027</td><td>17684</td><td>866</td><td>yes</td><td>300</td></tr>"
                   for m in macs)
    return f"<form action=/boaform/admin/formWirelessTbl method=POST><table><tr><th>MAC Address</th></tr>{rows}</table>"


def dhcp(rows):
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
    def __init__(self, flag_fn, username="admin", password="p@ss w0rd~*", busy=False, redirect=True,
                 parental_on=False, rules=None):
        self.flag_fn = flag_fn
        self.username, self.password = username, password
        self.busy, self.redirect = busy, redirect
        self.captcha = None
        self.sessions = set()
        self.logged_in = set()
        self.events = []        # ("login_ok"|"login_bad"|"bad_flag"|"reboot"|"logout"|"pc_on"|"add:..."|...)
        self.lock = threading.Lock()
        self.radio = {}         # session -> wlan_idx selected by formWlanRedirect
        self.stations = {0: [PHONE.upper(), PC], 1: []}
        self.extras = {0: ("Home-Work-5G", 1), 1: ("Home-Work-2G", 0)}
        self.leases = [(PHONE.upper(), "192.0.2.10", "phone", "5GHz", "-56"),
                       (PC.upper(), "192.0.2.11", "pc", "5GHz", "-47"),
                       (LAPTOP.upper(), "192.0.2.12", "work-laptop", "5GHz", "-60")]
        self.parental_on, self.rules = parental_on, list(rules or [])

    def page(self, sid, path):
        if path.startswith("/boaform/formWlanRedirect?redirect-url=/wlstatus.asp&wlan_idx="):
            idx = int(path.rsplit("=", 1)[1])
            self.radio[sid] = idx
            name, n = self.extras[idx]
            return wlstatus(2 if idx == 0 else 1, "Home-5G" if idx == 0 else "Home-2G", name, n)
        if path.startswith("/boaform/admin/formWirelessTbl?"):
            return wlstatbl(self.stations[self.radio.get(sid, 0)])     # the session's radio, like the real one
        if path == "/status_client_list.asp":
            return dhcp(self.leases)
        if path == "/parental-ctrl.asp":
            return parental(self.parental_on, self.rules)
        return None

    def parental_post(self, f):
        if "parentalCtrlSet" in f:
            self.parental_on = f.get("parental_ctrl_on") == "1"
            self.events.append("pc_on" if self.parental_on else "pc_off")
        elif "addfilterMac" in f:
            mac = "-".join(f["mac"][i:i + 2] for i in range(0, 12, 2)).lower()
            days = all(f.get(d) == "on" for d in ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"))
            hours = (f.get("starthr"), f.get("startmin"), f.get("endhr"), f.get("endmin")) == ("00", "00", "23", "59")
            ok = f.get("specPC") == "1" and days and hours and f.get("submit-url") == "/parental-ctrl.asp"
            if ok:
                self.rules.append((f["usrname"], mac))
            self.events.append(("add:" if ok else "add_rejected:") + f.get("usrname", ""))
        elif "deleteSelFilterMac" in f:
            picked = [int(k[6:]) for k in f if k.startswith("select")]
            for i in picked:
                self.events.append("del:" + self.rules[i][0])
            self.rules = [r for i, r in enumerate(self.rules) if i not in picked]
        else:
            self.events.append("pc_unknown")


def make_handler(router: Router):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _cookie(self):
            c = self.headers.get("Cookie") or ""
            for part in c.split(";"):
                k, _, v = part.strip().partition("=")
                if k == "SESSIONID":
                    return v
            return None

        def _send(self, code, body, headers=()):
            data = body.encode("latin-1")
            self.send_response(code)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _login_page(self, extra_headers=()):
            router.captcha = "".join(random.choice(string.ascii_letters + string.digits) for _ in range(5))
            self._send(200, '<html><script>var code = "%s";</script><form name="login"></form></html>'
                       % router.captcha, extra_headers)

        def do_GET(self):
            if self.path == "/admin/login.asp":
                sid = self._cookie()
                hdrs = ()
                if sid is None:
                    sid = "%08x" % random.getrandbits(32)
                    router.sessions.add(sid)
                    hdrs = (("Set-Cookie", "SESSIONID=%s; Path=/" % sid),)
                self._login_page(hdrs)
            elif self.path == "/admin/index.asp":
                if self._cookie() in router.logged_in:
                    self._send(200, '<html><script src="/admin/adminMenu.js"></script></html>')
                else:
                    self._login_page()
            else:
                sid = self._cookie()
                page = router.page(sid, self.path)
                if page is None:
                    self._send(404, "not found")
                elif sid in router.logged_in:
                    self._send(200, page)
                else:
                    router.events.append("page_without_login")
                    self._login_page()

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n).decode("latin-1")

        def _flag_ok(self, body):
            prefix, sep, flag = body.rpartition("postSecurityFlag=")
            return sep and flag.isdigit() and int(flag) == router.flag_fn(prefix)

        def do_POST(self):
            body = self._body()
            sid = self._cookie()
            if self.path == "/boaform/admin/formLogin":
                if not self._flag_ok(body):
                    router.events.append("bad_flag")
                    return self._login_page()
                f = dict(parse_qsl(body, keep_blank_values=True))
                if router.busy:
                    router.events.append("busy")
                    return self._send(200, "<script>alert('you have logined');</script>")
                if (sid in router.sessions and f.get("username") == router.username
                        and f.get("password") == router.password and f.get("captchaTextBox") == router.captcha
                        and f.get("save") == "Login" and f.get("submit-url") == "/admin/login.asp"):
                    router.logged_in.add(sid)
                    router.events.append("login_ok")
                    if router.redirect:
                        return self._send(302, "", (("Location", "/admin/index.asp"),))
                    return self._send(200, '<html><script src="/admin/adminMenu.js"></script></html>')
                router.events.append("login_bad")
                return self._login_page()
            if self.path == "/boaform/admin/formReboot":
                if sid in router.logged_in and body == "postSecurityFlag=65535" and self._flag_ok(body):
                    router.events.append("reboot")
                    router.logged_in.discard(sid)
                    self.close_connection = True          # the real router drops the connection
                    return
                router.events.append("reboot_rejected")
                return self._send(200, "denied")
            if self.path == "/boaform/admin/formLogout":
                if sid in router.logged_in and body == "save=Logout&submit-url=%2Fadmin%2Flogin.asp":
                    router.logged_in.discard(sid)
                    router.events.append("logout")
                else:
                    router.events.append("logout_rejected")
                return self._send(200, "bye")
            if self.path == "/boaform/admin/formParentCtrl":
                if sid not in router.logged_in:
                    router.events.append("pc_without_login")
                    return self._login_page()
                if not self._flag_ok(body):
                    router.events.append("bad_flag")
                    return self._send(200, "denied")
                router.parental_post(dict(parse_qsl(body, keep_blank_values=True)))
                # the real router answers Add / Delete with a redirect back to the page
                return self._send(302, "", (("Location", "/parental-ctrl.asp"),))
            self._send(404, "not found")

    return H


def serve(router: Router):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(router))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
