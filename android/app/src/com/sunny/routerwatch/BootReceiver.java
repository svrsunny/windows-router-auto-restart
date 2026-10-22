package com.sunny.routerwatch;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Restarts the watcher after the phone reboots or the app is updated, if alerts are switched on. */
public final class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        String a = intent == null ? null : intent.getAction();
        if (!Intent.ACTION_BOOT_COMPLETED.equals(a) && !Intent.ACTION_MY_PACKAGE_REPLACED.equals(a)) {
            return;
        }
        if (!Prefs.enabled(context)) {
            return;
        }
        try {
            context.startForegroundService(new Intent(context, WatchService.class).setAction(WatchService.ACTION_START));
        } catch (RuntimeException e) {
            // not allowed right now; it starts again the next time the app is opened
        }
    }
}
