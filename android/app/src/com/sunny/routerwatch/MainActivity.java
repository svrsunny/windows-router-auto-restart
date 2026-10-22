package com.sunny.routerwatch;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.NotificationManager;
import android.content.ActivityNotFoundException;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.InputType;
import android.util.TypedValue;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.CompoundButton;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

/** One screen: status, the reboot button, the alert switch and the router login. */
public final class MainActivity extends Activity {

    private TextView statusLine;
    private TextView statusDetail;
    private TextView actionText;
    private Switch watchSwitch;
    private Switch simSwitch;
    private EditText urlEdit;
    private EditText userEdit;
    private EditText passEdit;
    private TextView notifText;
    private Button notifButton;
    private TextView batteryText;
    private Button batteryButton;

    private final SharedPreferences.OnSharedPreferenceChangeListener prefsListener =
            new SharedPreferences.OnSharedPreferenceChangeListener() {
                @Override
                public void onSharedPreferenceChanged(SharedPreferences p, String key) {
                    refresh();
                }
            };

    private final CompoundButton.OnCheckedChangeListener watchListener = new CompoundButton.OnCheckedChangeListener() {
        @Override
        public void onCheckedChanged(CompoundButton b, boolean on) {
            Prefs.setEnabled(MainActivity.this, on);
            if (on) {
                Prefs.setStatus(MainActivity.this, "warn", "Checking...", "");
                WatchService.send(MainActivity.this, WatchService.ACTION_START);
            } else {
                WatchService.send(MainActivity.this, WatchService.ACTION_STOP);
            }
        }
    };

    private final CompoundButton.OnCheckedChangeListener simListener = new CompoundButton.OnCheckedChangeListener() {
        @Override
        public void onCheckedChanged(CompoundButton b, boolean on) {
            Prefs.setSimulate(MainActivity.this, on);
            if (Prefs.enabled(MainActivity.this)) {
                WatchService.send(MainActivity.this, WatchService.ACTION_CHECK);
            }
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        if (Build.VERSION.SDK_INT >= 29) {
            setTheme(android.R.style.Theme_DeviceDefault_DayNight);
        }
        super.onCreate(savedInstanceState);
        setContentView(buildUi());
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        Prefs.sp(this).registerOnSharedPreferenceChangeListener(prefsListener);
        refresh();
        if (Prefs.enabled(this)) {
            // make sure the watcher is running (e.g. after the app was force-stopped) and show fresh status
            WatchService.send(this, WatchService.ACTION_CHECK);
        }
    }

    @Override
    protected void onPause() {
        Prefs.sp(this).unregisterOnSharedPreferenceChangeListener(prefsListener);
        super.onPause();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        refresh();
    }

    // ---------- UI ----------

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private TextView text(String s, float sp, boolean bold) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        if (bold) {
            t.setTypeface(Typeface.DEFAULT_BOLD);
        }
        return t;
    }

    private Button button(String label, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setOnClickListener(l);
        return b;
    }

    private EditText edit(String hint, int inputType) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setInputType(inputType);
        e.setSingleLine(true);
        return e;
    }

    private void add(LinearLayout root, View v, int topMarginDp) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(topMarginDp);
        root.addView(v, lp);
    }

    private View buildUi() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(16), dp(20), dp(32));
        scroll.addView(root);

        statusLine = text("", 26, true);
        add(root, statusLine, 0);
        statusDetail = text("", 14, false);
        add(root, statusDetail, 4);

        Button reboot = button("Reboot router", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                confirmReboot();
            }
        });
        reboot.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        reboot.setMinHeight(dp(72));
        add(root, reboot, 20);
        actionText = text("", 14, false);
        add(root, actionText, 6);

        watchSwitch = new Switch(this);
        watchSwitch.setText("Alert me when the router is up but the internet is down");
        watchSwitch.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        add(root, watchSwitch, 24);

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams half = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        row.addView(button("Check now", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (!Prefs.enabled(MainActivity.this)) {
                    toast("Turn on the alert switch first.");
                    return;
                }
                WatchService.send(MainActivity.this, WatchService.ACTION_CHECK);
            }
        }), half);
        row.addView(button("Test login", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                if (!Prefs.hasPassword(MainActivity.this)) {
                    toast("Save the router password below first.");
                    return;
                }
                Prefs.setAction(MainActivity.this, "Testing the login...");
                WatchService.send(MainActivity.this, WatchService.ACTION_TEST_LOGIN);
            }
        }), new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        add(root, row, 8);

        add(root, text("Router login", 18, true), 28);
        urlEdit = edit("Router address, e.g. http://192.168.1.1",
                InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        add(root, urlEdit, 4);
        userEdit = edit("Username", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        add(root, userEdit, 4);
        passEdit = edit("Password", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        add(root, passEdit, 4);
        add(root, button("Save", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                save();
            }
        }), 4);
        urlEdit.setText(Prefs.routerUrl(this));
        userEdit.setText(Prefs.username(this));

        add(root, text("Keep it running", 18, true), 28);
        notifText = text("", 14, false);
        add(root, notifText, 4);
        notifButton = button("Allow notifications", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                openNotificationSettings();
            }
        });
        add(root, notifButton, 4);
        batteryText = text("", 14, false);
        add(root, batteryText, 8);
        batteryButton = button("Allow unrestricted battery use", new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                requestBatteryExemption();
            }
        });
        add(root, batteryButton, 4);

        simSwitch = new Switch(this);
        simSwitch.setText("Simulate an outage (to test the alert)");
        simSwitch.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        add(root, simSwitch, 20);

        TextView note = text("Works while the phone is connected to your home Wi-Fi. Checks run every 2 minutes; "
                + "when the phone is idle (e.g. at night) Android spaces them out to about every 10 minutes.", 13, false);
        note.setAlpha(0.7f);
        add(root, note, 20);
        return scroll;
    }

    private void refresh() {
        boolean enabled = Prefs.enabled(this);
        String kind = enabled ? Prefs.statusKind(this) : "off";
        statusLine.setText(enabled ? Prefs.statusLine(this) : "Alerts are off");
        statusDetail.setText(enabled ? Prefs.statusDetail(this)
                : "Turn on the switch below to get a notification when the internet goes down.");
        int color;
        if ("ok".equals(kind)) {
            color = 0xFF16A34A;
        } else if ("down".equals(kind)) {
            color = 0xFFDC2626;
        } else if ("warn".equals(kind)) {
            color = 0xFFD97706;
        } else {
            color = 0xFF6B7280;
        }
        statusLine.setTextColor(color);
        actionText.setText(Prefs.action(this));

        watchSwitch.setOnCheckedChangeListener(null);
        watchSwitch.setChecked(enabled);
        watchSwitch.setOnCheckedChangeListener(watchListener);
        simSwitch.setOnCheckedChangeListener(null);
        simSwitch.setChecked(Prefs.simulate(this));
        simSwitch.setOnCheckedChangeListener(simListener);

        passEdit.setHint(Prefs.hasPassword(this) ? "Password (saved - type to change)" : "Password");

        NotificationManager nm = getSystemService(NotificationManager.class);
        boolean notifOk = nm == null || nm.areNotificationsEnabled();
        notifText.setText(notifOk ? "Notifications: allowed" : "Notifications are blocked, so alerts can't be shown.");
        notifButton.setVisibility(notifOk ? View.GONE : View.VISIBLE);

        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        boolean unrestricted = pm != null && pm.isIgnoringBatteryOptimizations(getPackageName());
        batteryText.setText(unrestricted ? "Battery: unrestricted"
                : "Battery: optimized. Allow unrestricted use so the phone doesn't stop the checks.");
        batteryButton.setVisibility(unrestricted ? View.GONE : View.VISIBLE);
    }

    // ---------- actions ----------

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_LONG).show();
    }

    private void confirmReboot() {
        if (!Prefs.hasPassword(this)) {
            toast("Save the router password below first.");
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("Reboot the router?")
                .setMessage("The internet and Wi-Fi will drop for about 2-3 minutes.")
                .setPositiveButton("Reboot", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int which) {
                        Prefs.setAction(MainActivity.this, "Rebooting the router...");
                        WatchService.send(MainActivity.this, WatchService.ACTION_REBOOT);
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void save() {
        String url = Prefs.normalizeUrl(urlEdit.getText().toString());
        if (url == null) {
            toast("That router address doesn't look right. Example: http://192.168.1.1");
            return;
        }
        String user = userEdit.getText().toString().trim();
        if (user.isEmpty()) {
            toast("Enter the router username (usually admin).");
            return;
        }
        Prefs.setRouter(this, url, user);
        urlEdit.setText(url);
        String pw = passEdit.getText().toString();
        if (!pw.isEmpty()) {
            try {
                Prefs.setPassword(this, pw);
            } catch (Exception e) {
                toast("Couldn't save the password securely: " + e.getMessage());
                return;
            }
            passEdit.setText("");
        } else if (!Prefs.hasPassword(this)) {
            toast("Saved, but no password yet: the reboot button needs it.");
            refresh();
            return;
        }
        toast("Saved. Tap \"Test login\" to check the password.");
        refresh();
    }

    private void openNotificationSettings() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
                && shouldShowRequestPermissionRationale(Manifest.permission.POST_NOTIFICATIONS)) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
            return;
        }
        Intent i = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName());
        try {
            startActivity(i);
        } catch (ActivityNotFoundException e) {
            toast("Open Settings > Apps > Router Auto Restart > Notifications.");
        }
    }

    private void requestBatteryExemption() {
        Intent i = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                Uri.parse("package:" + getPackageName()));
        try {
            startActivity(i);
        } catch (ActivityNotFoundException e) {
            try {
                startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
            } catch (ActivityNotFoundException e2) {
                toast("Open Settings > Apps > Router Auto Restart > Battery and choose Unrestricted.");
            }
        }
    }
}
