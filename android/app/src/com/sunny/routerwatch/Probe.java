package com.sunny.routerwatch;

import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;

/** TCP reachability checks (no DNS for the internet probes: they use IP literals). */
public final class Probe {
    private Probe() {
    }

    /** Internet is "up" if any of these answers. Same defaults as the PC app's probe_targets. */
    static final String[][] INTERNET_TARGETS = {{"1.1.1.1", "443"}, {"8.8.8.8", "443"}, {"9.9.9.9", "443"}};

    /** Milliseconds to open a TCP connection, or -1 if it failed. */
    public static long tcpMs(Net net, String host, int port, int timeoutMs) {
        Socket s = null;
        try {
            InetAddress addr = net.resolve(host);
            s = net.newSocket();
            long t0 = System.nanoTime();
            s.connect(new InetSocketAddress(addr, port), timeoutMs);
            return Math.max(0, (System.nanoTime() - t0) / 1000000L);
        } catch (IOException e) {
            return -1;
        } catch (RuntimeException e) {
            return -1;
        } finally {
            if (s != null) {
                try {
                    s.close();
                } catch (IOException ignored) {
                    // ignore
                }
            }
        }
    }

    /** Milliseconds for the first internet target that answers, or -1 if none did. */
    public static long internetMs(Net net, int timeoutMs) {
        for (String[] t : INTERNET_TARGETS) {
            long ms = tcpMs(net, t[0], Integer.parseInt(t[1]), timeoutMs);
            if (ms >= 0) {
                return ms;
            }
        }
        return -1;
    }
}
