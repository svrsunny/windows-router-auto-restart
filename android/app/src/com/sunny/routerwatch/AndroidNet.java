package com.sunny.routerwatch;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.Socket;
import java.net.URL;

/**
 * Everything goes through the Wi-Fi network explicitly. When Wi-Fi has no internet, Android moves
 * normal app traffic to mobile data; without this binding the router would look unreachable and the
 * internet would look fine (over mobile data), so the outage would never be detected.
 */
final class AndroidNet implements Net {
    private final Network network;

    AndroidNet(Network network) {
        this.network = network;
    }

    @Override
    public HttpURLConnection open(URL url) throws IOException {
        return (HttpURLConnection) network.openConnection(url);
    }

    @Override
    public Socket newSocket() throws IOException {
        return network.getSocketFactory().createSocket();
    }

    @Override
    public InetAddress resolve(String host) throws IOException {
        return network.getByName(host);
    }

    /** The connected Wi-Fi network (validated or not), or null when the phone isn't on Wi-Fi. */
    @SuppressWarnings("deprecation")
    static Network findWifi(Context context) {
        ConnectivityManager cm = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
        if (cm == null) {
            return null;
        }
        for (Network n : cm.getAllNetworks()) {
            NetworkCapabilities c = cm.getNetworkCapabilities(n);
            if (c != null && c.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                    && !c.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) {
                return n;
            }
        }
        return null;
    }
}
