"""A fake GX router web UI for testing the app's login / reboot code on a PC.

Behaves like the real one as captured for the PC scripts: captcha text in login.asp, a session
cookie, postSecurityFlag checksum on every form post, single admin session, and the connection
dropping on reboot. Each checksum is verified with the PC adapter's own post_security_flag().
"""
import random
import string
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl


class Router:
    def __init__(self, flag_fn, username="admin", password="p@ss w0rd~*", busy=False, redirect=True):
        self.flag_fn = flag_fn
        self.username, self.password = username, password
        self.busy, self.redirect = busy, redirect
        self.captcha = None
        self.sessions = set()
        self.logged_in = set()
        self.events = []        # ("login_ok"|"login_bad"|"bad_flag"|"reboot"|"logout"|...)
        self.lock = threading.Lock()


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
                self._send(404, "not found")

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
            self._send(404, "not found")

    return H


def serve(router: Router):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(router))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
