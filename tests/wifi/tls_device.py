"""Disposable loopback TLS device adapter for the Chromium PWA test.

Playwright's client-cert tunnel presents its own certificate, rejected by SW.
This adapter presents the truly trusted test certificate and validates the REAL
deployment proxy upstream using a device cert. No TLS verification is disabled.
Native Android certificate selection/MDM remains a physical acceptance gate.
"""

import select
import socket
import socketserver
import ssl
import threading
from contextlib import contextmanager


@contextmanager
def tls_device(tls, hostname, port):
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_tls.minimum_version = ssl.TLSVersion.TLSv1_2
    server_tls.load_cert_chain(tls / "server-chain.crt", tls / "server.key")
    device_tls = ssl.create_default_context(cafile=str(tls / "ca.crt"))
    device_tls.load_cert_chain(tls / "device.crt", tls / "device.key")

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                self.request.settimeout(30)
                with (
                    server_tls.wrap_socket(self.request, server_side=True) as browser,
                    socket.create_connection(("127.0.0.1", port), timeout=20) as raw,
                    device_tls.wrap_socket(raw, server_hostname=hostname) as upstream,
                ):
                    browser.settimeout(30)
                    upstream.settimeout(30)

                    # SSL objects must have a single I/O owner. Concurrent recv
                    # and sendall on the same OpenSSL object can stall/corrupt
                    # the relay. Multiplex both directions in this handler;
                    # each separate browser connection still has its own thread.
                    peers = {browser: upstream, upstream: browser}
                    readable = [browser, upstream]
                    while readable:
                        ready = [stream for stream in readable if stream.pending()]
                        if not ready:
                            ready, _, _ = select.select(readable, [], [], 30)
                        if not ready:
                            break
                        for source in ready:
                            target = peers[source]
                            block = source.recv(65536)
                            if block:
                                target.sendall(block)
                            else:
                                readable.remove(source)
                                try:
                                    target.shutdown(socket.SHUT_WR)
                                except OSError:
                                    pass
            except OSError:
                pass  # Browser cancellation; never logs request bodies.

    class Server(socketserver.ThreadingTCPServer):
        # server_close waits for handler-owned TLS sockets, preventing SSL
        # worker threads from outliving this test context.
        daemon_threads = False
        allow_reuse_address = True

    with Server(("127.0.0.2", port), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield
        finally:
            server.shutdown()
            thread.join(timeout=2)
