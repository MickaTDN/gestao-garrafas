"""Real loopback TLS relay: one owner per SSL socket, without Docker or databases."""

import socket
import socketserver
import ssl
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.wifi.certificates import certificates
from tests.wifi.tls_device import tls_device

HOST = "synthetic-relay.test"
PAYLOAD = b"synthetic duplex payload\n" * 4096


class TLSDeviceRelayTests(unittest.TestCase):
    def test_verified_roundtrip_and_single_thread_per_ssl_socket(self):
        with tempfile.TemporaryDirectory() as temp:
            tls = Path(temp) / "tls"
            certificates(tls, HOST)
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.minimum_version = ssl.TLSVersion.TLSv1_2
            server_context.load_cert_chain(tls / "server-chain.crt", tls / "server.key")
            server_context.verify_mode = ssl.CERT_REQUIRED
            server_context.load_verify_locations(tls / "ca.crt")
            client_context = ssl.create_default_context(cafile=str(tls / "ca.crt"))
            client_context.minimum_version = ssl.TLSVersion.TLSv1_2
            owners = {}
            lock = threading.Lock()

            def record(method):
                def tracked(stream, *args, **kwargs):
                    with lock:
                        owners.setdefault(stream, set()).add(threading.get_ident())
                    return method(stream, *args, **kwargs)
                return tracked

            class Handler(socketserver.BaseRequestHandler):
                def handle(self):
                    self.request.settimeout(5)
                    with server_context.wrap_socket(self.request, server_side=True) as stream:
                        received = bytearray()
                        while len(received) < len(PAYLOAD):
                            block = stream.recv(min(16384, len(PAYLOAD) - len(received)))
                            if not block:
                                return
                            received.extend(block)
                            stream.sendall(block)
                        self.server.received = bytes(received)

            class Server(socketserver.ThreadingTCPServer):
                allow_reuse_address = True
                daemon_threads = True

            with (
                patch.object(ssl.SSLSocket, "recv", record(ssl.SSLSocket.recv)),
                patch.object(ssl.SSLSocket, "sendall", record(ssl.SSLSocket.sendall)),
                patch.object(ssl.SSLObject, "read", record(ssl.SSLObject.read)),
                patch.object(ssl.SSLObject, "write", record(ssl.SSLObject.write)),
                Server(("127.0.0.1", 0), Handler) as server,
            ):
                port = server.server_address[1]
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with tls_device(tls, HOST, port):
                        with (
                            socket.create_connection(("127.0.0.2", port), timeout=5) as raw,
                            client_context.wrap_socket(raw, server_hostname=HOST) as client,
                        ):
                            client.settimeout(5)
                            # TLS 1.3 session tickets can precede application data.
                            # The relay must not block waiting for a response before
                            # the client sends its first request.
                            time.sleep(0.1)
                            client.sendall(PAYLOAD)
                            received = bytearray()
                            while len(received) < len(PAYLOAD):
                                block = client.recv(min(16384, len(PAYLOAD) - len(received)))
                                self.assertTrue(block)
                                received.extend(block)
                            self.assertEqual(bytes(received), PAYLOAD)
                        self.assertEqual(server.received, PAYLOAD)
                    self.assertGreaterEqual(len(owners), 4)
                    self.assertTrue(
                        all(len(threads) == 1 for threads in owners.values()),
                        "An SSL socket was accessed from multiple I/O threads",
                    )
                finally:
                    server.shutdown()
                    thread.join(timeout=5)

    def test_upstream_hostname_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            tls = Path(temp) / "tls"
            certificates(tls, HOST)
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.load_cert_chain(tls / "server-chain.crt", tls / "server.key")
            client_context = ssl.create_default_context(cafile=str(tls / "ca.crt"))
            observed = []

            class Handler(socketserver.BaseRequestHandler):
                def handle(self):
                    self.request.settimeout(5)
                    try:
                        with server_context.wrap_socket(self.request, server_side=True) as stream:
                            observed.append(stream.recv(1024))
                    except OSError:
                        pass  # Expected rejection by the adapter's hostname check.

            class Server(socketserver.ThreadingTCPServer):
                daemon_threads = True
                allow_reuse_address = True

            with Server(("127.0.0.1", 0), Handler) as server:
                port = server.server_address[1]
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    with tls_device(tls, "wrong.synthetic.test", port):
                        with (
                            socket.create_connection(("127.0.0.2", port), timeout=5) as raw,
                            client_context.wrap_socket(raw, server_hostname=HOST) as client,
                        ):
                            client.settimeout(5)
                            try:
                                client.sendall(b"SYNTHETIC MUST NOT REACH UPSTREAM")
                                received = client.recv(1024)
                            except ssl.SSLError:
                                received = b""
                            self.assertEqual(received, b"")
                    self.assertFalse(any(observed))
                finally:
                    server.shutdown()
                    thread.join(timeout=5)
