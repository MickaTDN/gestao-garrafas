"""Real gateway/mTLS/CSRF test; disposable Windows CI only."""

import ipaddress
import json
import os
import socket
import ssl
from pathlib import Path


def main(root, directory):
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Disposable CI only")
    from native_windows.management_wifi import control, setup
    from tests.wifi.certificates import certificates

    address = next(
        a
        for a in socket.gethostbyname_ex(socket.gethostname())[2]
        if ipaddress.ip_address(a).is_private and not ipaddress.ip_address(a).is_loopback
    )
    pki = Path(directory) / "management-pki"
    hostname = "gestao.synthetic.test"
    certificates(pki, hostname)
    (pki / "config.json").write_text(
        json.dumps(
            {
                "it_approved": True,
                "address": address,
                "hostname": hostname,
                "port": 8443,
                "backend_port": 8766,
                "clients": [address + "/32"],
            }
        )
    )
    setup(root, {"configuration": str(pki / "config.json")})
    control(root, {"enable": True, "it_network_ready": True})

    def request(device, path="/entrar/", method="GET"):
        context = ssl.create_default_context(cafile=str(pki / "ca.crt"))
        if device:
            context.load_cert_chain(pki / (device + ".crt"), pki / (device + ".key"))
        with socket.create_connection((address, 8443), timeout=5) as raw:
            with context.wrap_socket(raw, server_hostname=hostname) as stream:
                stream.sendall(
                    f"{method} {path} HTTP/1.1\r\nHost: {hostname}:8443\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()
                )
                return stream.recv(8192)

    assert b"200 OK" in request("device")
    assert b"403 Forbidden" in request("device", method="POST")
    assert b"302 Found" in request("device", path="/stock/")
    for device in (None, "revoked"):
        try:
            reply = request(device)
        except ssl.SSLError:
            continue
        assert b"200 OK" not in reply
    for port in (8766, 8765, 55432):
        try:
            with socket.create_connection((address, port), timeout=2):
                raise AssertionError("Private service exposed")
        except OSError:
            pass
    control(root, {"enable": False})
    assert not (Path(root) / "runtime/wifi/approved").exists()
