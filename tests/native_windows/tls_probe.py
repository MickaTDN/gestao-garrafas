"""Actual Windows NGINX, ephemeral CA, trusted HTTPS/mTLS/CRL. No host trust changes."""

import ipaddress
import json
import os
import shutil
import socket
import ssl
import time
from pathlib import Path


def main(root, directory):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Disposable CI only")
    from native_windows.publisher import configure_publisher, enable
    from tests.wifi.certificates import certificates

    if not shutil.which("openssl"):
        os.environ["PATH"] = r"C:\Program Files\Git\usr\bin" + os.pathsep + os.environ["PATH"]
    addresses = socket.gethostbyname_ex(socket.gethostname())[2]
    private = next(
        value
        for value in addresses
        if any(
            ipaddress.ip_address(value) in ipaddress.ip_network(net)
            for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        )
    )
    pki = Path(directory) / "native-test-pki"
    hostname = "stock.synthetic.test"
    certificates(pki, hostname)
    (pki / "config.json").write_text(
        json.dumps(
            {
                "it_approved": True,
                "address": private,
                "hostname": hostname,
                "port": 8444,
                "clients": [private + "/32"],
            }
        )
    )
    configure_publisher(root, pki / "config.json")
    assert json.loads((Path(root) / "publisher.json").read_text())["enabled"] is False
    enable(root, {"it_network_ready": True})

    def request(device, path="/", method="GET"):
        context = ssl.create_default_context(cafile=str(pki / "ca.crt"))
        if device:
            context.load_cert_chain(pki / (device + ".crt"), pki / (device + ".key"))
        with socket.create_connection((private, 8444), timeout=5) as plain:
            with context.wrap_socket(plain, server_hostname=hostname) as secure:
                secure.sendall(
                    f"{method} {path} HTTP/1.1\r\nHost: {hostname}\r\nConnection: close\r\n\r\n".encode()
                )
                return secure.recv(8192)

    for attempt in range(30):
        try:
            assert b"200 OK" in request("device")
            break
        except (OSError, AssertionError):
            if attempt == 29:
                raise
            time.sleep(0.5)
    for device in (None, "revoked"):
        try:
            response = request(device)
        except ssl.SSLError:
            continue
        assert b"200 OK" not in response
    assert b"403 Forbidden" in request("device", method="POST")
    assert b"404 Not Found" in request("device", path="/secrets/owner.json")
    # The same host's PostgreSQL must refuse its network address, even to a
    # trusted certificate holder. No firewall or global trust exception is added.
    state = json.loads((Path(root) / "installation.json").read_text())
    try:
        with socket.create_connection((private, state["db_port"]), timeout=2):
            raise AssertionError("PostgreSQL exposed on the LAN address")
    except OSError:
        pass
    print(
        "PASS: native trusted HTTPS, device mTLS, revoked/missing certificate rejection, static GET-only, private-data exclusion and PG loopback."
    )
