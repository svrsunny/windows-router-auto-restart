package com.sunny.routerwatch;

import android.app.AlarmManager;
import android.app.Notification;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.os.SystemClock;
import android.util.Log;

import java.util.Date;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Foreground service that checks the router and the internet over Wi-Fi every couple of minutes
 * (an alarm wakes it; while the phone is in deep sleep Android stretches that to roughly every 10 min),
 * and runs reboots / login tests. All work runs one job at a time on a background thread.
 */
public final class WatchService extends Service {
    private static final String TAG = "RouterAutoRestart";

    static final String ACTION_START = "com.sunny.routerwatch.START";
    static final String ACTION_CHECK = "com.sunny.routerwatch.CHECK";
    static final String ACTION_REBOOT = "com.sunny.routerwatch.REBOOT";
    static final String ACTION_TEST_LOGIN = "com.sunny.routerwatch.TEST_LOGIN";
    static final String ACTION_STOP = "com.sunny.routerwatch.STOP";
    static final String EXTRA_FROM_NOTIFICATION = "from_notification";

    static final long INTERVAL_MS = 2 * 60 * 1000L;
    private static final int ROUTER_TIMEOUT_MS = 2000;
    private static final int INTERNET_TIMEOUT_MS = 2500;
    private static final long RECHECK_DELAY_MS = 5000;
    /** After the phone joins Wi-Fi, wait this long (address, DNS) before checking. */
    private static final long WIFI_SETTLE_MS = 8000;
    /** A Wi-Fi-triggered check is skipped if a check ran this recently. */
    private static final long WIFI_MIN_GAP_MS = 20000;

    private ExecutorService exec;
    private Handler main;
    private final AtomicInteger pending = new AtomicInteger();
    private ConnectivityManager.NetworkCallback wifiCallback;
    private volatile long lastCheckAt;      // elapsedRealtime of the last check

    /**
     * Check soon after the phone joins Wi-Fi instead of waiting for the next alarm, so an outage
     * found when you turn Wi-Fi on in the morning is handled within seconds.
     */
    private void watchWifi() {
        ConnectivityManager cm = getSystemService(ConnectivityManager.class);
        if (cm == null) {
            return;
        }
        wifiCallback = new ConnectivityManager.NetworkCallback() {
            @Override
            public void onAvailable(Network network) {
                main.postDelayed(new Runnable() {
                    @Override
                    public void run() {
                        if (Prefs.enabled(WatchService.this)
                                && SystemClock.elapsedRealtime() - lastCheckAt >= WIFI_MIN_GAP_MS) {
                            submit(new Runnable() {
                                @Override
                                public void run() {
                                    check();
                                }
                            });
                        }
                    }
                }, WIFI_SETTLE_MS);
            }
        };
        try {
            cm.registerNetworkCallback(new NetworkRequest.Builder()
                    .addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), wifiCallback);
        } catch (RuntimeException e) {
            Log.w(TAG, "can't watch Wi-Fi: " + e);
            wifiCallback = null;
        }
    }

    /** Used by the app screen (which is in the foreground, so starting a foreground service is allowed). */
    static void send(Context c, String action) {
        c.startForegroundService(new Intent(c, WatchService.class).setAction(action));
    }

    @Override
    public void onCreate() {
        super.onCreate();
        exec = Executors.newSingleThreadExecutor();
        main = new Handler(Looper.getMainLooper());
        Notifs.createChannels(this);
        watchWifi();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        if (wifiCallback != null) {
            try {
                getSystemService(ConnectivityManager.class).unregisterNetworkCallback(wifiCallback);
            } catch (RuntimeException e) {
                // already gone
            }
        }
        main.removeCallbacksAndMessages(null);
        exec.shutdown();
        super.onDestroy();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent != null && intent.getAction() != null ? intent.getAction() : ACTION_START;
        if (ACTION_STOP.equals(action)) {
            goForeground();   // keeps the startForegroundService() contract; removed again right below
            cancelAlarm(this);
            Tracker t = Prefs.loadTracker(this);
            t.reset();
            Prefs.saveTracker(this, t);
            Notifs.cancelAlert(this);
            Prefs.setStatus(this, "off", "Alerts are off", "");
            stopIfIdle();
            return START_NOT_STICKY;
        }
        goForeground();
        final boolean fromNotification = intent != null && intent.getBooleanExtra(EXTRA_FROM_NOTIFICATION, false);
        if (ACTION_REBOOT.equals(action)) {
            submit(new Runnable() {
                @Override
                public void run() {
                    routerAction(false, fromNotification, false);
                }
            });
        } else if (ACTION_TEST_LOGIN.equals(action)) {
            submit(new Runnable() {
                @Override
                public void run() {
                    routerAction(true, false, false);
                }
            });
        } else if (Prefs.enabled(this)) {          // START or CHECK
            submit(new Runnable() {
                @Override
                public void run() {
                    check();
                }
            });
        } else {
            stopIfIdle();
        }
        return START_STICKY;
    }

    private void goForeground() {
        String title = Prefs.enabled(this) ? Prefs.statusLine(this) : "Router Auto Restart";
        String text = Prefs.enabled(this) ? Prefs.statusDetail(this) : "Working...";
        Notification n = Notifs.ongoing(this, title, text);
        try {
            if (Build.VERSION.SDK_INT >= 34) {
                startForeground(Notifs.ID_ONGOING, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
            } else {
                startForeground(Notifs.ID_ONGOING, n);
            }
        } catch (RuntimeException e) {
            // Android refused a foreground start from the background (e.g. restarted by an alarm after
            // the app was killed). The check still runs; the next start from the app restores it.
            Log.w(TAG, "startForeground refused: " + e);
        }
    }

    private void stopIfIdle() {
        main.post(new Runnable() {
            @Override
            public void run() {
                if (!Prefs.enabled(WatchService.this) && pending.get() == 0) {
                    cancelAlarm(WatchService.this);
                    stopForeground(STOP_FOREGROUND_REMOVE);
                    stopSelf();
                }
            }
        });
    }

    private void submit(final Runnable job) {
        pending.incrementAndGet();
        exec.execute(new Runnable() {
            @Override
            public void run() {
                PowerManager pm = (PowerManager) getSystemService(Context.POWER_SERVICE);
                PowerManager.WakeLock wl = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "RouterAutoRestart:job");
                wl.setReferenceCounted(false);
                wl.acquire(2 * 60 * 1000L);
                try {
                    job.run();
                } catch (Throwable t) {
                    Log.e(TAG, "job failed", t);
                } finally {
                    if (wl.isHeld()) {
                        wl.release();
                    }
                    pending.decrementAndGet();
                    stopIfIdle();
                }
            }
        });
    }

    // ---------- scheduling ----------

    private static PendingIntent alarmIntent(Context c) {
        Intent i = new Intent(c, WatchService.class).setAction(ACTION_CHECK);
        return PendingIntent.getService(c, 1, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private static void scheduleNext(Context c, long delayMs) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        if (am == null) {
            return;
        }
        PendingIntent pi = alarmIntent(c);
        long at = SystemClock.elapsedRealtime() + delayMs;
        boolean exact = Build.VERSION.SDK_INT < 31 || am.canScheduleExactAlarms();
        try {
            if (exact) {
                am.setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, at, pi);
            } else {
                am.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, at, pi);
            }
        } catch (SecurityException e) {
            am.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, at, pi);
        }
    }

    private static void cancelAlarm(Context c) {
        AlarmManager am = (AlarmManager) c.getSystemService(Context.ALARM_SERVICE);
        if (am != null) {
            am.cancel(alarmIntent(c));
        }
    }

    // ---------- the check ----------

    private String time(long epochMs) {
        return android.text.format.DateFormat.getTimeFormat(this).format(new Date(epochMs));
    }

    private static boolean sleep(long ms) {
        try {
            Thread.sleep(ms);
            return true;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        }
    }

    private void check() {
        if (!Prefs.enabled(this)) {
            return;
        }
        lastCheckAt = SystemClock.elapsedRealtime();
        try {
            doCheck();
        } finally {
            if (Prefs.enabled(this)) {
                scheduleNext(this, INTERVAL_MS);
            }
        }
    }

    private void doCheck() {
        boolean sim = Prefs.simulate(this);
        Tracker t = Prefs.loadTracker(this);
        String url = Prefs.routerUrl(this);
        if (url.isEmpty()) {
            Prefs.setStatus(this, "warn", "Router address not set",
                    "Open Router Auto Restart and save the router's address under Router login.");
            Notifs.updateOngoing(this, Prefs.statusLine(this), Prefs.statusDetail(this));
            return;
        }
        String host = Prefs.hostOf(url);
        int port = Prefs.portOf(url);
        Network wifi = AndroidNet.findWifi(this);

        int ev;
        String kind;
        String line;
        String detail;
        long now;
        if (wifi == null) {
            now = System.currentTimeMillis();
            ev = t.step(now, false, false, false);
            kind = "warn";
            line = "Not on Wi-Fi";
            detail = "Checks run while the phone is connected to your home Wi-Fi.";
        } else {
            Net net = new AndroidNet(wifi);
            long routerMs = Probe.tcpMs(net, host, port, ROUTER_TIMEOUT_MS);
            long netMs = sim ? -1 : Probe.internetMs(net, INTERNET_TIMEOUT_MS);
            now = System.currentTimeMillis();
            if (routerMs >= 0 && netMs < 0 && !t.alerted && !t.inGrace(now)) {
                // make sure it isn't a blip before alerting
                for (int k = 0; k < 2 && netMs < 0; k++) {
                    if (!sleep(RECHECK_DELAY_MS)) {
                        break;
                    }
                    netMs = sim ? -1 : Probe.internetMs(net, INTERNET_TIMEOUT_MS);
                }
                now = System.currentTimeMillis();
            }
            boolean routerUp = routerMs >= 0;
            boolean internetUp = netMs >= 0;
            ev = t.step(now, true, routerUp, internetUp);
            String checked = "checked " + time(now);
            if (internetUp) {
                kind = "ok";
                line = "Internet OK";
                detail = (routerUp ? "Router " + routerMs + " ms" : "Router not answering")
                        + " · internet " + netMs + " ms · " + checked;
            } else if (!routerUp) {
                kind = "warn";
                line = "Router not reachable";
                detail = "On Wi-Fi, but " + host + " doesn't answer (the router is restarting, "
                        + "or this isn't your home Wi-Fi) · " + checked;
            } else if (t.alerted) {
                kind = "down";
                line = "No internet";
                detail = "Router is reachable, internet down since " + time(t.outageStart) + " · " + checked;
            } else {
                kind = "down";
                line = "Internet down";
                detail = "Waiting a few minutes: the router restarted recently · " + checked;
            }
            if (sim) {
                line = line + " (simulated)";
            }
        }
        // "Fix automatically": restart the router once for this outage instead of only alerting.
        // Never during "Simulate an outage": that switch must stay safe to play with.
        boolean autoReboot = Prefs.autoFix(this) && !sim && t.autoRebootAllowed(ev, now);
        if (autoReboot) {
            t.autoRebooted = true;
        }
        Prefs.saveTracker(this, t);
        Prefs.setStatus(this, kind, line, detail);
        if (autoReboot) {
            if (!routerAction(false, false, true)) {
                // couldn't restart it (e.g. a browser holds the router's one admin session): alert instead;
                // the reason is shown in the app
                Notifs.alert(this, time(t.outageStart), false);
            }
        } else if (ev == Tracker.ALERT) {
            Notifs.alert(this, time(t.outageStart), sim);
            if (sim && Prefs.autoFix(this)) {
                Prefs.setAction(this, "Test outage: with Fix automatically on, a real outage would restart the "
                        + "router now. Nothing was restarted.");
            }
        } else if (ev == Tracker.RECOVERED) {
            Notifs.recovered(this, Tracker.duration(t.eventEnd - t.eventStart), time(t.eventStart), time(t.eventEnd));
        } else if (ev == Tracker.CLEARED) {
            Notifs.cancelAlert(this);
        }
        if (Prefs.enabled(this)) {
            Notifs.updateOngoing(this, line, detail);
        }
    }

    // ---------- reboot / login test ----------

    /**
     * automatic: the app restarts the router by itself after a confirmed outage ("Fix automatically").
     * It reports like a restart from the notification, so a failure shows up there too.
     */
    private boolean routerAction(boolean dryRun, boolean fromNotification, boolean automatic) {
        fromNotification = fromNotification || automatic;
        String what = dryRun ? "Login test" : automatic ? "Automatic reboot" : "Reboot";
        String url = Prefs.routerUrl(this);
        if (url.isEmpty()) {
            fail(what, "No router address saved. Open Router Auto Restart and save it first.", fromNotification);
            return false;
        }
        if (!dryRun) {
            Tracker t = Prefs.loadTracker(this);
            long left = t.cooldownLeft(System.currentTimeMillis());
            if (left > 0) {
                // the reboot request is never repeated within the cooldown (same rule as the PC app)
                fail(what, "A reboot was already sent at " + time(t.lastReboot) + ". Try again after "
                        + time(t.lastReboot + Tracker.REBOOT_COOLDOWN_MS) + ".", fromNotification);
                return false;
            }
        }
        String password = Prefs.password(this);
        if (password == null) {
            fail(what, "No router password saved. Open Router Auto Restart and save it first.", fromNotification);
            return false;
        }
        Network wifi = AndroidNet.findWifi(this);
        if (wifi == null) {
            fail(what, "The phone isn't on Wi-Fi. Connect to your home Wi-Fi and try again.", fromNotification);
            return false;
        }
        Prefs.setAction(this, dryRun ? "Testing the login..." : "Rebooting the router...");
        if (fromNotification) {
            Notifs.progress(this, "Rebooting the router...");
        }
        RouterClient rc = new RouterClient(url, Prefs.username(this), password,
                new AndroidNet(wifi), 10000);
        try {
            rc.login(3, 3000);
            if (dryRun) {
                Prefs.setAction(this, "Login OK at " + time(System.currentTimeMillis())
                        + ". The saved password works.");
                return true;
            }
            rc.reboot();
            long now = System.currentTimeMillis();
            Tracker t = Prefs.loadTracker(this);
            t.onRebootSent(now);
            Prefs.saveTracker(this, t);
            boolean willNotify = Prefs.enabled(this) && t.awaitingRecovery;
            String msg = (automatic ? "The internet was down since " + time(t.outageStart) + ", so the app restarted "
                    + "the router at " + time(now) + "." : "Reboot sent at " + time(now) + ".")
                    + " The internet should be back in 2-3 minutes"
                    + (willNotify ? "; you'll get a notification when it is." : ".");
            Prefs.setAction(this, msg);
            if (fromNotification || t.awaitingRecovery) {
                Notifs.info(this, automatic ? "Router restarted automatically" : "Router is rebooting", msg);
            }
            return true;
        } catch (RouterClient.RouterException e) {
            fail(what, e.getMessage(), fromNotification);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            fail(what, "Interrupted.", fromNotification);
        } finally {
            rc.close();
        }
        return false;
    }

    private void fail(String what, String msg, boolean fromNotification) {
        Prefs.setAction(this, what + " failed: " + msg);
        if (fromNotification) {
            Notifs.rebootFailed(this, msg);
        }
    }
}
