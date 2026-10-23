package com.sunny.routerwatch;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.UnsupportedEncodingException;
import java.net.CookieHandler;
import java.net.CookieManager;
import java.net.CookiePolicy;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.Semaphore;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Web-UI client for the GX GPON router (firmware E4222-3.0.5-R).
 * Same flow as the PC adapter (src/routerkit/routers/gx_gpon.py):
 * GET login.asp -> read the captcha text from the page source -> compute postSecurityFlag
 * -> POST formLogin -> POST formReboot (or formLogout).
 * Wi-Fi clients and internet blocking (Parental Control rules) follow the same adapter; see its
 * docstring for the pages used.
 *
 * Only one client exists at a time (the router allows one admin session, and the cookie jar is
 * process-wide): the constructor waits for the previous one to be closed. Always close().
 */
public final class RouterClient implements AutoCloseable {

    private static final Semaphore ONE_SESSION = new Semaphore(1);

    public static class RouterException extends Exception {
        public RouterException(String message) {
            super(message);
        }
    }

    /** The router allows one admin session and another one is open. */
    public static final class BusyException extends RouterException {
        public BusyException(String message) {
            super(message);
        }
    }

    static final String USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            + "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36";
    private static final Pattern CAPTCHA = Pattern.compile("\\bcode\\s*=\\s*\"([^\"]+)\"");

    private final String base;
    private final String username;
    private final String password;
    private final Net net;
    private final int timeoutMs;
    private boolean loggedIn;
    private boolean rebooted;
    private boolean closed;

    public RouterClient(String baseUrl, String username, String password, Net net, int timeoutMs) {
        ONE_SESSION.acquireUninterruptibly();
        String b = baseUrl.trim();
        while (b.endsWith("/")) {
            b = b.substring(0, b.length() - 1);
        }
        this.base = b;
        this.username = username;
        this.password = password;
        this.net = net;
        this.timeoutMs = timeoutMs;
        // fresh cookie jar for every session (HttpURLConnection uses the default CookieHandler)
        CookieHandler.setDefault(new CookieManager(null, CookiePolicy.ACCEPT_ALL));
    }

    // ---------- protocol helpers (ported from the router's common.js, same as the PC scripts) ----------

    /** encodeURIComponent plus the extra replaces in postTableEncrypt(); same output as enc() in gx_gpon.py. */
    public static String enc(String value) {
        try {
            return URLEncoder.encode(value, "UTF-8");
        } catch (UnsupportedEncodingException e) {
            throw new AssertionError(e);
        }
    }

    /** Port of the checksum at the end of postTableEncrypt() in common.js. */
    public static int postSecurityFlag(String body) {
        long csum = 0;
        int n = body.length();
        int i = 0;
        while (i < n) {
            if (i + 4 > n) {
                csum += ((long) body.charAt(i)) << 24;
                if (i + 1 < n) {
                    csum += ((long) body.charAt(i + 1)) << 16;
                }
                if (i + 2 < n) {
                    csum += ((long) body.charAt(i + 2)) << 8;
                }
                break;
            }
            csum += (((long) body.charAt(i)) << 24) + (((long) body.charAt(i + 1)) << 16)
                    + (((long) body.charAt(i + 2)) << 8) + body.charAt(i + 3);
            i += 4;
        }
        int v = (int) csum;                       // JavaScript ToInt32
        int s = ((v & 0xFFFF) + (v >> 16)) & 0xFFFF;
        return (~s) & 0xFFFF;
    }

    /** A form post as the router's pages send it: the fields in page order, then postSecurityFlag. */
    public static String formBody(String[][] fields) {
        StringBuilder b = new StringBuilder();
        for (String[] f : fields) {
            b.append(f[0]).append('=').append(enc(f[1])).append('&');
        }
        String body = b.toString();
        return body + "postSecurityFlag=" + postSecurityFlag(body);
    }

    public static String buildLoginBody(String user, String password, String captcha) {
        return formBody(new String[][]{{"challenge", ""}, {"username", user}, {"password", password},
                {"captchaTextBox", captcha}, {"save", "Login"}, {"submit-url", "/admin/login.asp"}});
    }

    // ---------- HTTP ----------

    private HttpURLConnection connect(String path, int timeout) throws IOException {
        HttpURLConnection c = net.open(new URL(base + path));
        c.setConnectTimeout(timeout);
        c.setReadTimeout(timeout);
        c.setUseCaches(false);
        c.setRequestProperty("User-Agent", USER_AGENT);
        return c;
    }

    private static String readBody(HttpURLConnection c) throws IOException {
        int code = c.getResponseCode();
        InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
        if (in == null) {
            return "";
        }
        try {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int r;
            while ((r = in.read(buf)) != -1) {
                out.write(buf, 0, r);
            }
            return new String(out.toByteArray(), StandardCharsets.ISO_8859_1);
        } finally {
            in.close();
        }
    }

    private String get(String path) throws IOException {
        HttpURLConnection c = connect(path, timeoutMs);
        try {
            return readBody(c);
        } finally {
            c.disconnect();
        }
    }

    /**
     * streamed = true sends the body unbuffered, which stops HttpURLConnection from silently re-sending
     * the request if the router drops the connection (it does on reboot). Buffered posts can follow a
     * redirect, which the login may answer with.
     */
    private String post(String path, String body, String referer, int timeout, boolean streamed) throws IOException {
        HttpURLConnection c = connect(path, timeout);
        try {
            byte[] data = body.getBytes(StandardCharsets.ISO_8859_1);
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            if (streamed) {
                c.setFixedLengthStreamingMode(data.length);
                c.setInstanceFollowRedirects(false);   // a streamed body can't be re-sent to the new location
            }
            c.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
            c.setRequestProperty("Origin", base);
            c.setRequestProperty("Referer", base + referer);
            OutputStream os = c.getOutputStream();
            try {
                os.write(data);
            } finally {
                os.close();
            }
            return readBody(c);
        } finally {
            c.disconnect();
        }
    }

    // ---------- actions ----------

    public void login(int attempts, long retryDelayMs) throws RouterException, InterruptedException {
        String problem = null;
        boolean rejected = false;
        for (int n = 1; n <= attempts; n++) {
            try {
                String page = get("/admin/login.asp");
                Matcher m = CAPTCHA.matcher(page);
                if (!m.find()) {
                    throw new RouterException("The router's login page looks different than expected "
                            + "(captcha not found). Is the router address right?");
                }
                String r = post("/boaform/admin/formLogin", buildLoginBody(username, password, m.group(1)),
                        "/admin/login.asp", timeoutMs, false);
                if (r.contains("you have logined")) {
                    throw new BusyException("The router already has an admin session open (the PC app, "
                            + "a browser tab or an earlier run). Log out there and try again.");
                }
                // The logged-in landing page loads adminMenu.js; the login form does not.
                if (r.contains("adminMenu")) {
                    loggedIn = true;
                    return;
                }
                rejected = true;
                problem = "login rejected";
            } catch (IOException e) {
                problem = shortError(e);
            }
            if (n < attempts) {
                Thread.sleep(retryDelayMs);
            }
        }
        if (rejected) {
            throw new RouterException("The router rejected the login. Check the username and password.");
        }
        throw new RouterException("Can't reach the router (" + problem + ").");
    }

    /** Sends the reboot request. The connection usually drops while the router restarts; that is expected. */
    public void reboot() {
        rebooted = true;  // a reboot ends the session by itself
        try {
            post("/boaform/admin/formReboot", "postSecurityFlag=" + postSecurityFlag(""), "/reboot.asp", 15000, true);
        } catch (IOException e) {
            // connection dropped after the reboot request - the router is restarting
        }
    }

    /** Best effort, so the router's single admin session is freed. */
    public void logout() {
        try {
            post("/boaform/admin/formLogout", "save=Logout&submit-url=%2Fadmin%2Flogin.asp", "/", timeoutMs, true);
            loggedIn = false;
        } catch (IOException e) {
            // ignore
        }
    }

    // ---------- Wi-Fi clients and internet blocking (call after login) ----------

    private static final String PARENTAL = "/parental-ctrl.asp";
    private static final String[] DAYS = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};

    private String page(String path) throws RouterException {
        String what = path.split("\\?")[0];
        String r;
        try {
            r = get(path);
        } catch (IOException e) {
            throw new RouterException("Couldn't load " + what + " (" + shortError(e) + ").");
        }
        if (CAPTCHA.matcher(r).find() && r.contains("formLogin")) {
            throw new RouterException("The router ended the admin session.");
        }
        return r;
    }

    private void postParental(String[][] fields) throws RouterException {
        try {
            // streamed: never silently re-sent - a repeated delete would hit the renumbered row
            post("/boaform/admin/formParentCtrl", formBody(fields), PARENTAL, timeoutMs, true);
        } catch (IOException e) {
            throw new RouterException("The Parental Control request failed (" + shortError(e) + ").");
        }
    }

    public Clients listClients() throws RouterException {
        List<Clients.Radio> radios = new ArrayList<>();
        List<List<String>> stations = new ArrayList<>();
        for (int idx = 0; idx <= 1; idx++) {
            // the station table answers for the radio the redirect selected, so keep this order
            radios.add(Clients.parseRadio(page("/boaform/formWlanRedirect?redirect-url=/wlstatus.asp&wlan_idx=" + idx)));
            stations.add(Clients.parseStations(
                    page("/boaform/admin/formWirelessTbl?submit-url=/admin/wlstatbl.asp&wlan_idx=" + idx)));
        }
        List<Clients.Lease> dhcp = Clients.parseDhcp(page("/status_client_list.asp"));
        String pc = page(PARENTAL);
        Set<String> blocked = new HashSet<>();
        if (Clients.parentalOn(pc)) {
            for (Clients.Rule r : Clients.parseRules(pc)) {
                if (!r.mac.isEmpty() && r.name.startsWith(Clients.RULE_PREFIX)) {
                    blocked.add(r.mac);
                }
            }
        }
        return Clients.build(radios, stations, dhcp, blocked);
    }

    private static List<Clients.Rule> mine(List<Clients.Rule> rules, String mac) {
        List<Clients.Rule> out = new ArrayList<>();
        for (Clients.Rule r : rules) {
            if (r.mac.equals(mac) && r.name.startsWith(Clients.RULE_PREFIX)) {
                out.add(r);
            }
        }
        return out;
    }

    /** Block or unblock the device's internet access; checks the router kept the change. */
    public void setBlocked(String rawMac, boolean blocked) throws RouterException {
        String mac;
        try {
            mac = Clients.normMac(rawMac);
        } catch (IllegalArgumentException e) {
            throw new RouterException(e.getMessage());
        }
        String pc = page(PARENTAL);
        boolean on = Clients.parentalOn(pc);
        List<Clients.Rule> rules = Clients.parseRules(pc);
        if (blocked) {
            if (!on) {
                postParental(new String[][]{{"parental_ctrl_on", "1"}, {"parentalCtrlSet", "Apply Changes"},
                        {"submit-url", PARENTAL}});
            }
            if (mine(rules, mac).isEmpty()) {
                List<String[]> f = new ArrayList<>();
                f.add(new String[]{"usrname", Clients.ruleName(mac)});
                f.add(new String[]{"specPC", "1"});
                f.add(new String[]{"mac", mac.replace(":", "").toUpperCase(Locale.ROOT)});
                for (String d : DAYS) {
                    f.add(new String[]{d, "on"});
                }
                f.add(new String[]{"starthr", "00"});
                f.add(new String[]{"startmin", "00"});
                f.add(new String[]{"endhr", "23"});
                f.add(new String[]{"endmin", "59"});
                f.add(new String[]{"addfilterMac", "Add"});
                f.add(new String[]{"submit-url", PARENTAL});
                postParental(f.toArray(new String[0][]));
            }
            pc = page(PARENTAL);
            if (!Clients.parentalOn(pc) || mine(Clients.parseRules(pc), mac).isEmpty()) {
                throw new RouterException("The router did not keep the block. Nothing changed.");
            }
            return;
        }
        int tries = mine(rules, mac).size();
        for (int i = 0; i < tries && !mine(rules, mac).isEmpty(); i++) {
            // one at a time: deleting renumbers the checkboxes
            postParental(new String[][]{{mine(rules, mac).get(0).select, "ON"},
                    {"deleteSelFilterMac", "Delete Selected"}, {"submit-url", PARENTAL}});
            pc = page(PARENTAL);
            on = Clients.parentalOn(pc);
            rules = Clients.parseRules(pc);
        }
        if (!mine(rules, mac).isEmpty()) {
            throw new RouterException("The router did not remove the block.");
        }
        if (on && rules.isEmpty()) {
            // nothing else uses Parental Control: switch it back off
            postParental(new String[][]{{"parental_ctrl_on", "0"}, {"parentalCtrlSet", "Apply Changes"},
                    {"submit-url", PARENTAL}});
        }
    }

    @Override
    public void close() {
        if (closed) {
            return;
        }
        closed = true;
        try {
            if (loggedIn && !rebooted) {
                logout();
            }
        } finally {
            ONE_SESSION.release();
        }
    }

    static String shortError(IOException e) {
        String m = e.getMessage();
        String name = e.getClass().getSimpleName();
        if (m == null || m.isEmpty()) {
            return name;
        }
        if (m.length() > 120) {
            m = m.substring(0, 120);
        }
        return name + ": " + m;
    }
}
