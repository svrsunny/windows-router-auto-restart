package com.sunny.routerwatch;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Wi-Fi devices grouped by SSID, parsed from the router's pages. Same rules as the PC adapter
 * (parse_* and build_clients in src/routerkit/routers/gx_gpon.py); run_tests.py checks both give
 * the same result. Plain Java so it can be tested on a PC.
 */
final class Clients {

    static final String RULE_PREFIX = "RC-";

    static final class Client {
        final String mac;
        String name = "";
        String ip = "";
        String rssi = "";
        boolean blocked;

        Client(String mac) {
            this.mac = mac;
        }
    }

    static final class Ssid {
        final String name;
        final String band;
        final boolean canBlock;       // the router's block applies to devices on this SSID
        final List<Client> clients = new ArrayList<>();
        int reported;                 // devices the router counts here (may be more than it lists)

        Ssid(String name, String band, boolean canBlock) {
            this.name = name;
            this.band = band;
            this.canBlock = canBlock;
        }
    }

    static final class Radio {
        String band;
        String main;                  // "" when the radio is off
        final List<String> extraNames = new ArrayList<>();
        final List<Integer> extraCounts = new ArrayList<>();
    }

    static final class Lease {
        String mac;
        String ip;
        String name;
        String band;
        String rssi;
    }

    static final class Rule {
        String select;                // the delete checkbox name, e.g. select0
        String name;
        String mac;
    }

    final List<Ssid> ssids = new ArrayList<>();
    final List<Client> unknown = new ArrayList<>();          // on Wi-Fi, SSID not known
    final List<Client> blockedOffline = new ArrayList<>();   // blocked by this app, not connected now

    // ---------- parsing ----------

    private static final Pattern MAC = Pattern.compile("^(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$");
    private static final Pattern MAC12 = Pattern.compile("^[0-9a-fA-F]{12}$");
    private static final Pattern ROW = Pattern.compile("<tr[^>]*>(.*?)</tr>", Pattern.DOTALL | Pattern.CASE_INSENSITIVE);
    private static final Pattern CELL = Pattern.compile("<td[^>]*>(.*?)</td>", Pattern.DOTALL | Pattern.CASE_INSENSITIVE);
    private static final Pattern TAG = Pattern.compile("<[^>]+>");
    private static final Pattern BAND = Pattern.compile("\\bBand2G5GSupport\\s*=\\s*(\\d+)");
    private static final Pattern SELECT = Pattern.compile("name=\"?(select\\d+)\"?");
    private static final Pattern PC_ON = Pattern.compile("value=\"1\"\\s+name=\"parental_ctrl_on\"\\s*checked");

    static boolean isMac(String s) {
        return MAC.matcher(s).matches();
    }

    /** "00-00-5E-00-53-01" / "00005e005301" -> "00:00:5e:00:53:01". */
    static String normMac(String mac) {
        String m = mac == null ? "" : mac.trim();
        if (!MAC.matcher(m).matches() && !MAC12.matcher(m).matches()) {
            throw new IllegalArgumentException("not a MAC address: " + m);
        }
        String hex = m.replaceAll("[^0-9a-fA-F]", "").toLowerCase(Locale.ROOT);
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < 12; i += 2) {
            if (i > 0) {
                b.append(':');
            }
            b.append(hex, i, i + 2);
        }
        return b.toString();
    }

    static String ruleName(String mac) {
        return RULE_PREFIX + normMac(mac).replace(":", "");
    }

    private static String unescape(String s) {
        Matcher m = Pattern.compile("&#(\\d+);").matcher(s);
        StringBuffer b = new StringBuffer();
        while (m.find()) {
            m.appendReplacement(b, Matcher.quoteReplacement(new String(Character.toChars(Integer.parseInt(m.group(1))))));
        }
        m.appendTail(b);
        return b.toString().replace("&nbsp;", "\u00a0").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", "\"").replace("&#x27;", "'").replace("&amp;", "&");
    }

    static List<String> cells(String row) {
        List<String> out = new ArrayList<>();
        Matcher m = CELL.matcher(row);
        while (m.find()) {
            // strip like Python's str.strip(), which also removes the no-break space from &nbsp;
            out.add(unescape(TAG.matcher(m.group(1)).replaceAll("")).replaceAll("^[\\s\\u00a0]+|[\\s\\u00a0]+$", ""));
        }
        return out;
    }

    private static List<String> rows(String page) {
        List<String> out = new ArrayList<>();
        Matcher m = ROW.matcher(page);
        while (m.find()) {
            out.add(m.group(1));
        }
        return out;
    }

    /** Values of name[i]=... assignments in the page's script, quotes stripped. */
    static Map<Integer, String> js(String page, String name) {
        Map<Integer, String> out = new LinkedHashMap<>();
        Matcher m = Pattern.compile("\\b" + Pattern.quote(name) + "\\[(\\d+)\\]\\s*=\\s*('[^']*'|-?\\d+)\\s*;").matcher(page);
        while (m.find()) {
            String v = m.group(2);
            out.put(Integer.parseInt(m.group(1)), v.startsWith("'") ? v.substring(1, v.length() - 1) : v);
        }
        return out;
    }

    private static String get(Map<Integer, String> m, int i, String dflt) {
        String v = m.get(i);
        return v == null ? dflt : v;
    }

    /** wlstatus.asp -> band, main SSID name and the enabled extra SSIDs with their counts. */
    static Radio parseRadio(String page) throws RouterClient.RouterException {
        Matcher bm = BAND.matcher(page);
        if (!bm.find() || !("1".equals(bm.group(1)) || "2".equals(bm.group(1)))) {
            throw new RouterClient.RouterException("The router's Wi-Fi status page looks different than expected.");
        }
        Radio r = new Radio();
        r.band = "1".equals(bm.group(1)) ? "2.4 GHz" : "5 GHz";
        boolean off = !"0".equals(get(js(page, "wlanDisabled"), 0, "0"));
        r.main = off ? "" : get(js(page, "ssid_drv"), 0, "");
        Map<Integer, String> names = js(page, "mssid_ssid_drv");
        Map<Integer, String> disabled = js(page, "mssid_disable");
        Map<Integer, String> counts = js(page, "mssid_clientnum");
        for (Integer i : new TreeSet<>(names.keySet())) {
            String n = names.get(i);
            if ("0".equals(get(disabled, i, "1")) && !n.isEmpty()) {
                String c = get(counts, i, "0");
                r.extraNames.add(n);
                r.extraCounts.add(c.isEmpty() ? 0 : Integer.parseInt(c));
            }
        }
        return r;
    }

    /** wlstatbl.asp -> MACs on the selected radio's main SSID. */
    static List<String> parseStations(String page) {
        List<String> out = new ArrayList<>();
        for (String row : rows(page)) {
            List<String> c = cells(row);
            if (!c.isEmpty() && isMac(c.get(0))) {
                out.add(normMac(c.get(0)));
            }
        }
        return out;
    }

    /** status_client_list.asp -> DHCP and static leases. */
    static List<Lease> parseDhcp(String page) {
        List<Lease> out = new ArrayList<>();
        for (String row : rows(page)) {
            List<String> c = cells(row);
            if (c.size() >= 5 && isMac(c.get(0))) {
                Lease l = new Lease();
                l.mac = normMac(c.get(0));
                l.ip = c.get(1);
                l.name = c.get(2).isEmpty() || "----".equals(c.get(2)) ? "" : c.get(2);
                String band = c.get(3).replace(" ", "");
                l.band = "5GHz".equals(band) ? "5 GHz" : "2.4GHz".equals(band) ? "2.4 GHz" : "";
                l.rssi = c.get(4).isEmpty() || "----".equals(c.get(4)) ? "" : c.get(4);
                out.add(l);
            }
        }
        return out;
    }

    static boolean parentalOn(String page) {
        return PC_ON.matcher(page).find();
    }

    /** parental-ctrl.asp -> the rule table. */
    static List<Rule> parseRules(String page) throws RouterClient.RouterException {
        int at = page.indexOf("formParentCtrlDel");
        if (at < 0) {
            throw new RouterClient.RouterException("The router's Parental Control page looks different than expected.");
        }
        List<Rule> out = new ArrayList<>();
        for (String row : rows(page.substring(at))) {
            Matcher box = SELECT.matcher(row);
            if (!box.find()) {
                continue;
            }
            List<String> c = cells(row);
            Rule r = new Rule();
            r.select = box.group(1);
            r.name = c.isEmpty() ? "" : c.get(0);
            r.mac = "";
            for (String x : c) {
                if (isMac(x)) {
                    r.mac = normMac(x);
                    break;
                }
            }
            out.add(r);
        }
        return out;
    }

    // ---------- grouping ----------

    /**
     * Main-SSID devices come from the router's station table. A device the DHCP table puts on a
     * radio's band but that is not on its main SSID is on an extra SSID; it is only assigned when
     * the radio has exactly one extra SSID and the router's count for it matches. Otherwise it goes
     * to `unknown` rather than being guessed.
     */
    static Clients build(List<Radio> radios, List<List<String>> stations, List<Lease> dhcp, Set<String> blocked) {
        Map<String, Lease> byMac = new LinkedHashMap<>();
        for (Lease l : dhcp) {
            byMac.put(l.mac, l);
        }
        Clients out = new Clients();
        Set<String> seen = new TreeSet<>();
        for (int r = 0; r < radios.size() && r < stations.size(); r++) {
            Radio radio = radios.get(r);
            List<String> main = stations.get(r);
            if (!radio.main.isEmpty()) {
                Ssid s = new Ssid(radio.main, radio.band, true);
                for (String mac : main) {
                    s.clients.add(client(mac, byMac, blocked, seen));
                }
                s.reported = main.size();
                out.ssids.add(s);
            }
            List<String> rest = new ArrayList<>();
            for (Lease l : dhcp) {
                if (l.band.equals(radio.band) && !main.contains(l.mac) && !seen.contains(l.mac)) {
                    rest.add(l.mac);
                }
            }
            if (radio.extraNames.size() == 1 && radio.extraCounts.get(0) == rest.size()) {
                Ssid s = new Ssid(radio.extraNames.get(0), radio.band, false);
                for (String mac : rest) {
                    s.clients.add(client(mac, byMac, blocked, seen));
                }
                s.reported = radio.extraCounts.get(0);
                out.ssids.add(s);
            } else {
                // e.g. devices with a fixed IP or their own DHCP are counted by the router but never listed
                for (int i = 0; i < radio.extraNames.size(); i++) {
                    Ssid s = new Ssid(radio.extraNames.get(i), radio.band, false);
                    s.reported = radio.extraCounts.get(i);
                    out.ssids.add(s);
                }
                for (String mac : rest) {
                    out.unknown.add(client(mac, byMac, blocked, seen));
                }
            }
        }
        for (String mac : new TreeSet<>(blocked)) {
            if (!seen.contains(mac)) {
                Client c = new Client(mac);
                Lease l = byMac.get(mac);
                c.name = l == null ? "" : l.name;
                c.blocked = true;
                out.blockedOffline.add(c);
            }
        }
        return out;
    }

    private static Client client(String mac, Map<String, Lease> byMac, Set<String> blocked, Set<String> seen) {
        Client c = new Client(mac);
        Lease l = byMac.get(mac);
        if (l != null) {
            c.name = l.name;
            c.ip = l.ip;
            c.rssi = l.rssi;
        }
        c.blocked = blocked.contains(mac);
        seen.add(mac);
        return c;
    }
}
