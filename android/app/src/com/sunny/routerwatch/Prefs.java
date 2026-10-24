package com.sunny.routerwatch;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.Key;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Settings and small shared state. The router password is encrypted with a key held in the Android Keystore. */
final class Prefs {
    private Prefs() {
    }

    static final String FILE = "routerwatch";
    static final String DEFAULT_USER = "admin";
    private static final String KEY_ALIAS = "routerwatch_password_key";

    static SharedPreferences sp(Context c) {
        return c.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    // ---------- router settings ----------

    /** The configured router address, or "" until the user saves one (there is no built-in address). */
    static String routerUrl(Context c) {
        return sp(c).getString("router_url", "");
    }

    static String username(Context c) {
        return sp(c).getString("username", DEFAULT_USER);
    }

    static void setRouter(Context c, String url, String user) {
        sp(c).edit().putString("router_url", url).putString("username", user).apply();
    }

    /** "192.0.2.1" -> "http://192.0.2.1"; null if it isn't a usable http(s) address. */
    static String normalizeUrl(String raw) {
        if (raw == null) {
            return null;
        }
        String s = raw.trim();
        if (s.isEmpty()) {
            return null;
        }
        if (!s.contains("://")) {
            s = "http://" + s;
        }
        try {
            URL u = new URL(s);
            String proto = u.getProtocol();
            if (!"http".equals(proto) && !"https".equals(proto)) {
                return null;
            }
            if (u.getUserInfo() != null) {
                return null;                     // never accept user:password@ in the address
            }
            String host = u.getHost();
            if (host == null || host.isEmpty() || host.contains(" ")) {
                return null;
            }
            return proto + "://" + host + (u.getPort() != -1 ? ":" + u.getPort() : "");
        } catch (Exception e) {
            return null;
        }
    }

    static String hostOf(String url) {
        try {
            return new URL(url).getHost();
        } catch (Exception e) {
            return "";
        }
    }

    static int portOf(String url) {
        try {
            URL u = new URL(url);
            return u.getPort() != -1 ? u.getPort() : u.getDefaultPort();
        } catch (Exception e) {
            return 80;
        }
    }

    // ---------- password (Android Keystore, AES-GCM) ----------

    private static SecretKey key() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
        ks.load(null);
        Key k = ks.getKey(KEY_ALIAS, null);
        if (k instanceof SecretKey) {
            return (SecretKey) k;
        }
        KeyGenerator kg = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        kg.init(new KeyGenParameterSpec.Builder(KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build());
        return kg.generateKey();
    }

    static void setPassword(Context c, String password) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        byte[] iv = cipher.getIV();
        byte[] ct = cipher.doFinal(password.getBytes(StandardCharsets.UTF_8));
        String v = Base64.encodeToString(iv, Base64.NO_WRAP) + ":" + Base64.encodeToString(ct, Base64.NO_WRAP);
        sp(c).edit().putString("password_enc", v).apply();
    }

    static boolean hasPassword(Context c) {
        return sp(c).getString("password_enc", null) != null;
    }

    /** The saved password, or null if none is saved or it can no longer be decrypted. */
    static String password(Context c) {
        String v = sp(c).getString("password_enc", null);
        if (v == null) {
            return null;
        }
        try {
            int i = v.indexOf(':');
            byte[] iv = Base64.decode(v.substring(0, i), Base64.NO_WRAP);
            byte[] ct = Base64.decode(v.substring(i + 1), Base64.NO_WRAP);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
            return new String(cipher.doFinal(ct), StandardCharsets.UTF_8);
        } catch (Exception e) {
            return null;
        }
    }

    // ---------- switches ----------

    static boolean enabled(Context c) {
        return sp(c).getBoolean("enabled", false);
    }

    static void setEnabled(Context c, boolean on) {
        sp(c).edit().putBoolean("enabled", on).apply();
    }

    static boolean simulate(Context c) {
        return sp(c).getBoolean("simulate", false);
    }

    static void setSimulate(Context c, boolean on) {
        sp(c).edit().putBoolean("simulate", on).apply();
    }

    /** Restart the router by itself when an outage is confirmed (off unless the user turns it on). */
    static boolean autoFix(Context c) {
        return sp(c).getBoolean("auto_fix", false);
    }

    static void setAutoFix(Context c, boolean on) {
        sp(c).edit().putBoolean("auto_fix", on).apply();
    }

    // ---------- tracker state (survives the app being killed) ----------

    static Tracker loadTracker(Context c) {
        SharedPreferences p = sp(c);
        Tracker t = new Tracker();
        t.alerted = p.getBoolean("t_alerted", false);
        t.awaitingRecovery = p.getBoolean("t_awaiting", false);
        t.outageStart = p.getLong("t_outage_start", 0);
        t.lastRouterDown = p.getLong("t_router_down", 0);
        t.lastReboot = p.getLong("t_reboot", 0);
        t.noWifiSince = p.getLong("t_no_wifi", 0);
        t.autoRebooted = p.getBoolean("t_auto_rebooted", false);
        return t;
    }

    static void saveTracker(Context c, Tracker t) {
        sp(c).edit()
                .putBoolean("t_alerted", t.alerted)
                .putBoolean("t_awaiting", t.awaitingRecovery)
                .putLong("t_outage_start", t.outageStart)
                .putLong("t_router_down", t.lastRouterDown)
                .putLong("t_reboot", t.lastReboot)
                .putLong("t_no_wifi", t.noWifiSince)
                .putBoolean("t_auto_rebooted", t.autoRebooted)
                .apply();
    }

    // ---------- status shown in the app and the ongoing notification ----------

    /** kind: ok | down | warn | off */
    static void setStatus(Context c, String kind, String line, String detail) {
        sp(c).edit().putString("st_kind", kind).putString("st_line", line).putString("st_detail", detail).apply();
    }

    static String statusKind(Context c) {
        return sp(c).getString("st_kind", "off");
    }

    static String statusLine(Context c) {
        return sp(c).getString("st_line", "Not checked yet");
    }

    static String statusDetail(Context c) {
        return sp(c).getString("st_detail", "");
    }

    static void setAction(Context c, String msg) {
        sp(c).edit().putString("action_msg", msg).apply();
    }

    static String action(Context c) {
        return sp(c).getString("action_msg", "");
    }
}
