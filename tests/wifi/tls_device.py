"""Disposable loopback TLS device adapter for the Chromium PWA test.

Playwright's client-cert tunnel presents its own certificate, rejected by SW.
This adapter presents the truly trusted test certificate and validates the REAL
deployment proxy upstream using a device cert. No TLS verification is disabled.
Native Android certificate selection/MDM remains a physical acceptance gate.
"""

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
                with (
                    server_tls.wrap_socket(self.request, server_side=True) as browser,
                    socket.create_connection(("127.0.0.1", port), timeout=20) as raw,
                    device_tls.wrap_socket(raw, server_hostname=hostname) as upstream,
                ):
                    browser.settimeout(30)
                    upstream.settimeout(30)

                    def copy(source, target):
                        try:
                            while block := source.recv(65536):
                                target.sendall(block)
                        except OSError:
                            pass
                        finally:
                            try:
                                target.shutdown(socket.SHUT_WR)
                            except OSError:
                                pass

                    send = threading.Thread(target=copy, args=(browser, upstream), daemon=True)
                    send.start()
                    copy(upstream, browser)
                    send.join(timeout=1)
            except OSError:
                pass  # Browser cancellation; never logs request bodies.

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    with Server(("127.0.0.2", port), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield
        finally:
            server.shutdown()
            thread.join(timeout=2)
