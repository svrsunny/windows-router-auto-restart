package com.sunny.routerwatch;

import java.io.BufferedReader;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.Proxy;
import java.net.Socket;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Base64;

/** PC-side tests for the plain-Java parts of the app (driven by run_tests.py). */
public final class TestMain {

    static final class JvmNet implements Net {
        @Override
        public HttpURLConnection open(URL url) throws IOException {
            return (HttpURLConnection) url.openConnection(Proxy.NO_PROXY);
        }

        @Override
        public Socket newSocket() {
            return new Socket(Proxy.NO_PROXY);
        }

        @Override
        public InetAddress resolve(String host) throws IOException {
            return InetAddress.getByName(host);
        }
    }

    private static int failures = 0;

    private static void check(boolean ok, String what) {
        System.out.println((ok ? "PASS " : "FAIL ") + what);
        if (!ok) {
            failures++;
        }
    }

    public static void main(String[] args) throws Exception {
        String mode = args[0];
        if ("protocol".equals(mode)) {
            protocol(args[1]);
        } else if ("tracker".equals(mode)) {
            tracker();
        } else if ("client".equals(mode)) {
            client(args[1], args[2], args[3], args[4]);
        } else if ("probe".equals(mode)) {
            System.out.println("PROBE " + Probe.tcpMs(new JvmNet(), args[1], Integer.parseInt(args[2]), 1500));
        }
        System.exit(failures == 0 ? 0 : 1);
    }

    /** Each input line: base64(user) base64(password) base64(captcha) base64(body-for-flag). */
    static void protocol(String file) throws IOException {
        Base64.Decoder d = Base64.getDecoder();
        BufferedReader r = new BufferedReader(new InputStreamReader(new FileInputStream(file), StandardCharsets.UTF_8));
        String line;
        while ((line = r.readLine()) != null) {
            String[] p = line.split(" ", -1);
            String user = new String(d.decode(p[0]), StandardCharsets.UTF_8);
            String pw = new String(d.decode(p[1]), StandardCharsets.UTF_8);
            String cap = new String(d.decode(p[2]), StandardCharsets.UTF_8);
            String body = new String(d.decode(p[3]), StandardCharsets.UTF_8);
            System.out.println(RouterClient.enc(pw) + " " + RouterClient.postSecurityFlag(body) + " "
                    + RouterClient.buildLoginBody(user, pw, cap));
        }
        r.close();
    }

    static void tracker() {
        long M = 60_000L;
        long T0 = 1_700_000_000_000L;

        // 1. outage while the router answers -> one alert, then recovery with the right duration
        Tracker t = new Tracker();
        check(t.step(T0, true, true, true) == Tracker.NONE, "healthy check: no event");
        check(t.step(T0 + 2 * M, true, true, false) == Tracker.ALERT, "router up + internet down: alert");
        check(t.alerted && t.outageStart == T0 + 2 * M, "outage start recorded");
        check(t.step(T0 + 4 * M, true, true, false) == Tracker.NONE, "still down: no second alert");
        check(t.step(T0 + 30 * M, true, true, true) == Tracker.RECOVERED, "internet back: recovered");
        check(t.eventEnd - t.eventStart == 28 * M, "recovered duration 28 min");
        check(!t.alerted && t.outageStart == 0, "state cleared after recovery");
        check(t.step(T0 + 32 * M, true, true, true) == Tracker.NONE, "healthy again: no event");

        // 2. router unreachable (restarting / power cut) -> no alert, and grace afterwards
        t = new Tracker();
        check(t.step(T0, true, false, false) == Tracker.NONE, "router down: no alert");
        check(t.step(T0 + 2 * M, true, true, false) == Tracker.NONE, "router just came back, internet down: grace");
        check(t.step(T0 + 4 * M, true, true, false) == Tracker.NONE, "still inside 5-min router grace");
        check(t.step(T0 + 5 * M, true, true, false) == Tracker.ALERT, "grace over: alert");
        check(t.outageStart == T0, "outage counted from the first failed check");

        // 3. reboot sent during an outage -> no alert in the reboot grace, then recovered message
        t = new Tracker();
        t.step(T0, true, true, false);
        check(t.alerted, "alerted before reboot");
        t.onRebootSent(T0 + M);
        check(!t.alerted && t.awaitingRecovery, "reboot sent: awaiting recovery");
        check(t.step(T0 + 2 * M, false, false, false) == Tracker.NONE, "router rebooting, phone off Wi-Fi: nothing");
        check(t.step(T0 + 3 * M, true, false, false) == Tracker.NONE, "back on Wi-Fi, router still booting: nothing");
        check(t.step(T0 + 4 * M, true, true, true) == Tracker.RECOVERED, "internet back after reboot: recovered");

        // 4. reboot did not help -> alert again once both graces are over
        t = new Tracker();
        t.step(T0, true, true, false);
        t.onRebootSent(T0 + M);
        check(t.step(T0 + 3 * M, true, false, false) == Tracker.NONE, "router booting");
        check(t.step(T0 + 6 * M, true, true, false) == Tracker.NONE, "router grace (3+5 min) still running");
        check(t.step(T0 + 8 * M, true, true, false) == Tracker.ALERT, "reboot didn't help: alert again");

        // 5. manual reboot while the internet is fine -> no notifications at all
        t = new Tracker();
        t.step(T0, true, true, true);
        t.onRebootSent(T0 + M);
        check(!t.awaitingRecovery, "manual reboot while healthy: not awaiting");
        check(t.step(T0 + 2 * M, true, false, false) == Tracker.NONE, "router down after manual reboot");
        check(t.step(T0 + 4 * M, true, true, false) == Tracker.NONE, "internet not back yet: grace");
        check(t.step(T0 + 5 * M, true, true, true) == Tracker.NONE, "internet back: no 'recovered' noise");

        // 6. alert, then the phone leaves home Wi-Fi for > 15 min -> alert cleared
        t = new Tracker();
        t.step(T0, true, true, false);
        check(t.step(T0 + M, false, false, false) == Tracker.NONE, "left Wi-Fi: nothing yet");
        check(t.step(T0 + 10 * M, false, false, false) == Tracker.NONE, "10 min away: still nothing");
        check(t.step(T0 + 16 * M, false, false, false) == Tracker.CLEARED, "15+ min away: cleared");
        check(!t.alerted && t.outageStart == 0, "state reset after clearing");
        check(t.step(T0 + 60 * M, true, true, true) == Tracker.NONE, "home again, internet OK: no event");

        // 7. off Wi-Fi only briefly during an alert -> still alerted, recovery later
        t = new Tracker();
        t.step(T0, true, true, false);
        t.step(T0 + M, false, false, false);
        check(t.step(T0 + 3 * M, true, true, false) == Tracker.NONE && t.alerted, "brief Wi-Fi drop keeps the alert");
        check(t.step(T0 + 5 * M, true, true, true) == Tracker.RECOVERED, "recovered after brief drop");

        // 8. clock went backwards -> grace not stuck on
        t = new Tracker();
        t.lastReboot = T0 + 60 * M;
        check(!t.inGrace(T0), "future reboot timestamp does not create grace");

        // 9. reboot cooldown: a second reboot is refused for 10 minutes
        t = new Tracker();
        check(t.cooldownLeft(T0) == 0, "no reboot yet: allowed");
        t.onRebootSent(T0);
        check(t.cooldownLeft(T0 + 3 * M) == 7 * M, "3 min after a reboot: 7 min left");
        check(t.cooldownLeft(T0 + 10 * M) == 0, "10 min after a reboot: allowed again");

        check("less than a minute".equals(Tracker.duration(30_000)), "duration <1 min");
        check("12 min".equals(Tracker.duration(12 * M + 5000)), "duration 12 min");
        check("1h 05m".equals(Tracker.duration(65 * M)), "duration 1h 05m");
    }

    static void client(String url, String user, String pw, String action) {
        RouterClient rc = new RouterClient(url, user, pw, new JvmNet(), 3000);
        try {
            rc.login(3, 200);
            if ("reboot".equals(action)) {
                rc.reboot();
            }
            System.out.println("RESULT ok");
        } catch (RouterClient.BusyException e) {
            System.out.println("RESULT busy " + e.getMessage());
        } catch (RouterClient.RouterException e) {
            System.out.println("RESULT error " + e.getMessage());
        } catch (InterruptedException e) {
            System.out.println("RESULT interrupted");
        } finally {
            rc.close();
        }
    }
}
