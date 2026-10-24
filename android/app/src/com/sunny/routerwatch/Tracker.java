package com.sunny.routerwatch;

/**
 * Turns a stream of checks into ALERT / RECOVERED / CLEARED events. No Android, no network: easy to test.
 *
 * Alert only when the phone is on Wi-Fi, the router answers and the internet doesn't, outside the
 * grace periods after a reboot we sent or after the router itself was unreachable (it was restarting
 * or lost power; the fiber link needs a few minutes after that).
 */
public final class Tracker {
    public static final long REBOOT_GRACE_MS = 5 * 60 * 1000L;
    public static final long ROUTER_GRACE_MS = 5 * 60 * 1000L;
    public static final long NO_WIFI_RESET_MS = 15 * 60 * 1000L;
    /** A second reboot is refused this long after one was sent (same default as the PC app). */
    public static final long REBOOT_COOLDOWN_MS = 10 * 60 * 1000L;

    public static final int NONE = 0;
    public static final int ALERT = 1;
    public static final int RECOVERED = 2;
    public static final int CLEARED = 3;

    public boolean alerted;
    /** A reboot was sent during an outage: tell the user when the internet is back. */
    public boolean awaitingRecovery;
    public long outageStart;
    public long lastRouterDown;
    public long lastReboot;
    public long noWifiSince;
    /** The app already restarted the router by itself during this outage (at most once per outage). */
    public boolean autoRebooted;

    /** Outage start / end for the last RECOVERED event. */
    public long eventStart;
    public long eventEnd;

    private static boolean within(long now, long since, long window) {
        return since > 0 && now - since >= 0 && now - since < window;
    }

    public boolean inGrace(long now) {
        return within(now, lastReboot, REBOOT_GRACE_MS) || within(now, lastRouterDown, ROUTER_GRACE_MS);
    }

    public int step(long now, boolean onWifi, boolean routerUp, boolean internetUp) {
        if (!onWifi) {
            if (noWifiSince == 0) {
                noWifiSince = now;
            }
            boolean active = alerted || awaitingRecovery || outageStart != 0;
            // away from home Wi-Fi for a while (and not because of our own reboot): forget the outage
            if (active && now - noWifiSince >= NO_WIFI_RESET_MS && !within(now, lastReboot, NO_WIFI_RESET_MS)) {
                boolean wasNotifying = alerted || awaitingRecovery;
                reset();
                return wasNotifying ? CLEARED : NONE;
            }
            return NONE;
        }
        noWifiSince = 0;
        if (!routerUp) {
            lastRouterDown = now;
        }
        if (internetUp) {
            int ev = (alerted || awaitingRecovery) && outageStart != 0 ? RECOVERED : NONE;
            eventStart = outageStart;
            eventEnd = now;
            outageStart = 0;
            alerted = false;
            awaitingRecovery = false;
            autoRebooted = false;
            return ev;
        }
        if (outageStart == 0) {
            outageStart = now;
        }
        if (routerUp && !alerted && !inGrace(now)) {
            alerted = true;
            awaitingRecovery = false;
            return ALERT;
        }
        return NONE;
    }

    /**
     * After an ALERT: should the app restart the router by itself? Only once per outage and outside the
     * reboot cooldown; if that restart didn't help, the next ALERT is left to the user.
     */
    public boolean autoRebootAllowed(int event, long now) {
        return event == ALERT && !autoRebooted && cooldownLeft(now) == 0;
    }

    /** Milliseconds until another reboot is allowed, 0 if it is allowed now. */
    public long cooldownLeft(long now) {
        return within(now, lastReboot, REBOOT_COOLDOWN_MS) ? REBOOT_COOLDOWN_MS - (now - lastReboot) : 0;
    }

    public void onRebootSent(long now) {
        lastReboot = now;
        if (alerted || outageStart != 0) {
            awaitingRecovery = true;
        }
        alerted = false;
    }

    public void reset() {
        alerted = false;
        awaitingRecovery = false;
        outageStart = 0;
        noWifiSince = 0;
        autoRebooted = false;
    }

    /** "less than a minute", "12 min", "1h 05m". */
    public static String duration(long ms) {
        long min = Math.max(0, ms) / 60000L;
        if (min < 1) {
            return "less than a minute";
        }
        if (min < 60) {
            return min + " min";
        }
        long h = min / 60;
        long m = min % 60;
        return h + "h " + (m < 10 ? "0" : "") + m + "m";
    }
}
