package com.sunny.routerwatch;

import java.io.IOException;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.Socket;
import java.net.URL;

/**
 * The network that router and internet checks go through.
 * On the phone this is bound to the Wi-Fi network (see AndroidNet), so the checks never
 * leak out over mobile data. Plain Java so the logic can be tested on a PC.
 */
public interface Net {
    HttpURLConnection open(URL url) throws IOException;

    /** An unconnected socket on this network. */
    Socket newSocket() throws IOException;

    InetAddress resolve(String host) throws IOException;
}
