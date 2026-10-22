package com.sunny.routerwatch;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.graphics.drawable.Icon;
import android.os.Build;

import java.util.Arrays;

final class Notifs {
    private Notifs() {
    }

    static final String CH_WATCH = "watch";
    static final String CH_ALERT = "alerts";
    static final String CH_INFO = "info";

    static final int ID_ONGOING = 1;
    static final int ID_ALERT = 2;     // outage alert, then reboot progress / result / "internet is back"

    private static final int RED = 0xFFDC2626;
    private static final int GREEN = 0xFF16A34A;
    private static final int BLUE = 0xFF2563EB;

    static void createChannels(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm == null) {
            return;
        }
        NotificationChannel w = new NotificationChannel(CH_WATCH, "Background check (silent)",
                NotificationManager.IMPORTANCE_LOW);
        w.setDescription("The always-on notification that keeps the internet check running.");
        w.setShowBadge(false);
        NotificationChannel a = new NotificationChannel(CH_ALERT, "Internet outage alerts",
                NotificationManager.IMPORTANCE_HIGH);
        a.setDescription("When the router is reachable but the internet is down.");
        a.enableVibration(true);
        NotificationChannel i = new NotificationChannel(CH_INFO, "Reboot and recovery updates",
                NotificationManager.IMPORTANCE_DEFAULT);
        i.setDescription("Reboot results and \"internet is back\" messages.");
        nm.createNotificationChannels(Arrays.asList(w, a, i));
    }

    static PendingIntent openApp(Context c) {
        Intent i = new Intent(c, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        return PendingIntent.getActivity(c, 0, i, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    static PendingIntent rebootIntent(Context c) {
        Intent i = new Intent(c, WatchService.class)
                .setAction(WatchService.ACTION_REBOOT)
                .putExtra(WatchService.EXTRA_FROM_NOTIFICATION, true);
        return PendingIntent.getForegroundService(c, 2, i,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
    }

    private static Notification.Action rebootAction(Context c, String label) {
        return new Notification.Action.Builder(Icon.createWithResource(c, R.drawable.ic_stat_router), label,
                rebootIntent(c)).build();
    }

    private static Notification.Builder base(Context c, String channel, String title, String text) {
        return new Notification.Builder(c, channel)
                .setSmallIcon(R.drawable.ic_stat_router)
                .setContentTitle(title)
                .setContentText(text)
                .setStyle(new Notification.BigTextStyle().bigText(text))
                .setContentIntent(openApp(c));
    }

    static Notification ongoing(Context c, String title, String text) {
        Notification.Builder b = base(c, CH_WATCH, title, text)
                .setColor(BLUE)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setShowWhen(false)
                .setCategory(Notification.CATEGORY_SERVICE);
        if (Build.VERSION.SDK_INT >= 31) {
            b.setForegroundServiceBehavior(Notification.FOREGROUND_SERVICE_IMMEDIATE);
        }
        return b.build();
    }

    static void updateOngoing(Context c, String title, String text) {
        post(c, ID_ONGOING, ongoing(c, title, text));
    }

    static void alert(Context c, String since, boolean simulated) {
        String text = "Your router is reachable, but the internet has been down since " + since
                + ". Rebooting the router usually fixes it.";
        Notification.Builder b = base(c, CH_ALERT, simulated ? "No internet at home (test)" : "No internet at home", text)
                .setColor(RED)
                .setCategory(Notification.CATEGORY_ERROR)
                .addAction(rebootAction(c, "Reboot router"));
        post(c, ID_ALERT, b.build());
    }

    static void progress(Context c, String title) {
        Notification.Builder b = base(c, CH_INFO, title, "Logging in to the router...")
                .setColor(BLUE)
                .setOnlyAlertOnce(true)
                .setProgress(0, 0, true);
        post(c, ID_ALERT, b.build());
    }

    static void info(Context c, String title, String text) {
        Notification.Builder b = base(c, CH_INFO, title, text)
                .setColor(BLUE)
                .setOnlyAlertOnce(true)
                .setAutoCancel(true)
                .setTimeoutAfter(30 * 60 * 1000L);
        post(c, ID_ALERT, b.build());
    }

    static void rebootFailed(Context c, String msg) {
        Notification.Builder b = base(c, CH_INFO, "Router reboot failed", msg)
                .setColor(RED)
                .setAutoCancel(true)
                .addAction(rebootAction(c, "Try again"));
        post(c, ID_ALERT, b.build());
    }

    static void recovered(Context c, String duration, String from, String to) {
        Notification.Builder b = base(c, CH_INFO, "Internet is back",
                "It was down for " + duration + " (" + from + " - " + to + ").")
                .setColor(GREEN)
                .setAutoCancel(true)
                .setTimeoutAfter(60 * 60 * 1000L);
        post(c, ID_ALERT, b.build());
    }

    static void cancelAlert(Context c) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm != null) {
            nm.cancel(ID_ALERT);
        }
    }

    private static void post(Context c, int id, Notification n) {
        NotificationManager nm = c.getSystemService(NotificationManager.class);
        if (nm == null) {
            return;
        }
        try {
            nm.notify(id, n);
        } catch (SecurityException e) {
            // notification permission not granted
        }
    }
}
