package com.sunny.routerwatch;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.graphics.Typeface;
import android.net.Network;
import android.os.Build;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Wi-Fi devices by SSID, with Block / Unblock (internet access) on the SSIDs the router can block on. */
public final class ClientsActivity extends Activity {

    private static final String VIEW_ONLY = "This router can't block devices on this network.";

    private final ExecutorService exec = Executors.newSingleThreadExecutor();
    private TextView status;
    private LinearLayout list;
    private Button refreshButton;
    private boolean busy;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        if (Build.VERSION.SDK_INT >= 29) {
            setTheme(android.R.style.Theme_DeviceDefault_DayNight);
        }
        super.onCreate(savedInstanceState);
        setTitle("Wi-Fi clients");
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(16), dp(20), dp(32));
        scroll.addView(root);

        refreshButton = new Button(this);
        refreshButton.setText("Refresh");
        refreshButton.setAllCaps(false);
        refreshButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                refresh();
            }
        });
        add(root, refreshButton, 0);
        status = text("", 14, false);
        add(root, status, 8);
        TextView note = text("Block cuts the device's internet access; it stays connected to Wi-Fi. The router's "
                + "clock decides when its all-day rule runs, so expect about a minute a day without the block.", 13, false);
        note.setAlpha(0.7f);
        add(root, note, 6);
        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        add(root, list, 8);
        setContentView(scroll);
        refresh();
    }

    @Override
    protected void onDestroy() {
        exec.shutdown();
        super.onDestroy();
    }

    // ---------- UI helpers ----------

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

    private void add(LinearLayout parent, View v, int topMarginDp) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(topMarginDp);
        parent.addView(v, lp);
    }

    // ---------- router work ----------

    private interface Job {
        Object run(RouterClient rc) throws RouterClient.RouterException;
    }

    private interface Done {
        void ok(Object result);
    }

    /** Logs in on the Wi-Fi network, runs the job, logs out; reports back on the UI thread. */
    private void run(String working, final Job job, final Done done) {
        if (busy) {
            return;
        }
        final String url = Prefs.routerUrl(this);
        final String password = Prefs.password(this);
        if (url.isEmpty() || password == null) {
            status.setText("Save the router address and password on the main screen first.");
            return;
        }
        final Network wifi = AndroidNet.findWifi(this);
        if (wifi == null) {
            status.setText("The phone isn't on Wi-Fi. Connect to your home Wi-Fi and try again.");
            return;
        }
        busy = true;
        setButtons(false);
        status.setText(working);
        final String user = Prefs.username(this);
        exec.execute(new Runnable() {
            @Override
            public void run() {
                Object result;
                String error = null;
                RouterClient rc = new RouterClient(url, user, password, new AndroidNet(wifi), 10000);
                try {
                    rc.login(2, 2000);
                    result = job.run(rc);
                } catch (RouterClient.RouterException e) {
                    result = null;
                    error = e.getMessage();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    result = null;
                    error = "Interrupted.";
                } catch (RuntimeException e) {
                    result = null;
                    error = e.getClass().getSimpleName();
                } finally {
                    rc.close();
                }
                final Object res = result;
                final String err = error;
                runOnUiThread(new Runnable() {
                    @Override
                    public void run() {
                        if (isFinishing() || isDestroyed()) {
                            return;
                        }
                        busy = false;
                        setButtons(true);
                        if (err != null) {
                            status.setText(err);
                        } else {
                            done.ok(res);
                        }
                    }
                });
            }
        });
    }

    private void setButtons(boolean on) {
        refreshButton.setEnabled(on);
        for (int i = 0; i < list.getChildCount(); i++) {
            enable(list.getChildAt(i), on);
        }
    }

    private static void enable(View v, boolean on) {
        if (v instanceof Button) {
            v.setEnabled(on);
        } else if (v instanceof ViewGroup) {
            ViewGroup g = (ViewGroup) v;
            for (int i = 0; i < g.getChildCount(); i++) {
                enable(g.getChildAt(i), on);
            }
        }
    }

    private void refresh() {
        run("Reading the router...", new Job() {
            @Override
            public Object run(RouterClient rc) throws RouterClient.RouterException {
                return rc.listClients();
            }
        }, new Done() {
            @Override
            public void ok(Object result) {
                show((Clients) result);
            }
        });
    }

    private void confirmToggle(final Clients.Client c) {
        final boolean block = !c.blocked;
        final String who = c.name.isEmpty() ? c.mac : c.name;
        new AlertDialog.Builder(this)
                .setTitle((block ? "Block " : "Unblock ") + who + "?")
                .setMessage(block ? c.mac + " loses internet access until you unblock it. It stays on Wi-Fi."
                        : c.mac + " gets its internet access back.")
                .setPositiveButton(block ? "Block" : "Unblock", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int which) {
                        run((block ? "Blocking " : "Unblocking ") + who + "...", new Job() {
                            @Override
                            public Object run(RouterClient rc) throws RouterClient.RouterException {
                                rc.setBlocked(c.mac, block);
                                return rc.listClients();
                            }
                        }, new Done() {
                            @Override
                            public void ok(Object result) {
                                show((Clients) result);
                                status.setText(who + ": internet " + (block ? "blocked." : "unblocked."));
                            }
                        });
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    // ---------- rendering ----------

    private void show(Clients cl) {
        list.removeAllViews();
        int n = cl.unknown.size();
        for (Clients.Ssid s : cl.ssids) {
            n += Math.max(s.reported, s.clients.size());
            section(s.name + "  ·  " + s.band, s.clients, s.canBlock, s.canBlock ? "" : VIEW_ONLY,
                    s.reported - s.clients.size());
        }
        if (!cl.unknown.isEmpty()) {
            section("On Wi-Fi, network not known", cl.unknown, false,
                    "The router didn't say which network these are on, so they can't be blocked here.", 0);
        }
        if (!cl.blockedOffline.isEmpty()) {
            section("Blocked, not connected now", cl.blockedOffline, true, "", 0);
        }
        status.setText(n + (n == 1 ? " device" : " devices") + " on Wi-Fi.");
    }

    /** hidden: devices the router counts on this SSID but doesn't list. */
    private void section(String title, List<Clients.Client> clients, boolean canBlock, String note, int hidden) {
        add(list, text(title + "  ·  " + (clients.size() + Math.max(hidden, 0)), 17, true), 22);
        if (!note.isEmpty()) {
            TextView t = text(note, 13, false);
            t.setAlpha(0.7f);
            add(list, t, 2);
        }
        if (hidden > 0) {
            add(list, text("The router reports " + hidden + (hidden == 1 ? " device" : " devices")
                    + " here that it doesn't list by name (fixed IP address, or an address it didn't hand out).",
                    14, false), 6);
        } else if (clients.isEmpty()) {
            TextView t = text("No devices.", 14, false);
            t.setAlpha(0.7f);
            add(list, t, 6);
        }
        for (final Clients.Client c : clients) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            LinearLayout texts = new LinearLayout(this);
            texts.setOrientation(LinearLayout.VERTICAL);
            texts.addView(text((c.name.isEmpty() ? "(no name)" : c.name) + (c.blocked ? "  ·  BLOCKED" : ""), 16, true));
            StringBuilder d = new StringBuilder(c.mac);
            if (!c.ip.isEmpty()) {
                d.append("  ·  ").append(c.ip);
            }
            if (!c.rssi.isEmpty()) {
                d.append("  ·  ").append(c.rssi).append(" dBm");
            }
            TextView detail = text(d.toString(), 13, false);
            detail.setAlpha(0.7f);
            texts.addView(detail);
            row.addView(texts, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            if (canBlock || c.blocked) {
                Button b = new Button(this);
                b.setText(c.blocked ? "Unblock" : "Block");
                b.setAllCaps(false);
                b.setOnClickListener(new View.OnClickListener() {
                    @Override
                    public void onClick(View v) {
                        confirmToggle(c);
                    }
                });
                row.addView(b);
            }
            add(list, row, 10);
        }
    }
}
