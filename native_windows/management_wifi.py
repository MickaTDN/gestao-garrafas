"""Opt-in management gateway, separate from the offline Stock publisher."""

import json
import secrets
import shutil
import subprocess
import time
from pathlib import Path

from .package import UnsafeOperation, refuse_reparse
from .runtime import environment, read_state
from .state import exclusive, write_json
from .windows import SERVICES, administrator, configure, native, protect, stop


def owns_listener(port, pid):
    """Never send the proxy secret to a different process on a reused local port."""
    import ctypes
    import socket
    import struct

    api = ctypes.WinDLL("iphlpapi").GetExtendedTcpTable
    api.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_int,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    api.restype = ctypes.c_uint32
    size = ctypes.c_uint32()
    if api(None, ctypes.byref(size), True, 2, 3, 0) not in (0, 122):
        raise UnsafeOperation("Não foi possível verificar o processo do backend.")
    buffer = ctypes.create_string_buffer(size.value)
    if api(buffer, ctypes.byref(size), True, 2, 3, 0):
        return False
    count = struct.unpack_from("<I", buffer.raw)[0]
    for index in range(count):
        row = struct.unpack_from("<6I", buffer.raw, 4 + index * 24)
        if row[0] == 2 and socket.ntohs(row[2] & 0xFFFF) == port and row[5] == pid:
            return True
    return False


def approved(root):
    # Runtime approvals are deliberately excluded from backups/restores (PR25).
    return (Path(root) / "runtime/wifi/approved").is_file()


def render(root, release, config):
    # Reuse the reviewed RFC1918/client allowlist checks, without changing Stock.
    from .publisher import render as validate

    validate(release, root, config)
    import re

    if not re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}", config["hostname"]
    ):
        raise UnsafeOperation("Nome DNS inválido.")
    port = config["backend_port"]
    state = read_state(root)
    if (
        type(port) is not int
        or not 1024 <= port <= 65535
        or port in (state["db_port"], state["http_port"], config["port"])
    ):
        raise UnsafeOperation("Portas de gestão inválidas ou sobrepostas.")
    if not re.fullmatch(r"[a-f0-9]{64}", config["proxy_token"]):
        raise UnsafeOperation("Segredo do proxy inválido.")
    runtime = Path(root) / "runtime/wifi"
    tls = Path(root) / "secrets/management-wifi"

    def q(path):
        return '"' + Path(path).as_posix() + '"'

    lines = [
        f"pid {q(runtime / 'nginx.pid')};",
        f"error_log {q(runtime / 'error.log')} warn;",
        "events { worker_connections 128; }",
        "http {",
        "access_log off; server_tokens off;",
        "ssl_protocols TLSv1.2 TLSv1.3; ssl_verify_client on; ssl_verify_depth 2;",
        "ssl_session_tickets off; ssl_session_cache off;",
        f"ssl_certificate {q(tls / 'server-chain.crt')};",
        f"ssl_certificate_key {q(tls / 'server.key')};",
        f"ssl_client_certificate {q(tls / 'device-ca.crt')};",
        f"ssl_crl {q(tls / 'device-ca.crl')};",
    ]
    for kind in ("client_body", "proxy", "fastcgi", "scgi", "uwsgi"):
        lines.append(f"{kind}_temp_path {q(runtime / kind)};")
    listen = f"{config['address']}:{config['port']}"
    lines += [
        f"server {{ listen {listen} ssl default_server; server_name _; return 421; }}",
        f"server {{ listen {listen} ssl; server_name {config['hostname']};",
    ]
    lines += [f"allow {net};" for net in config["clients"]]
    lines += [
        "deny all;",
        "client_max_body_size 12m;",
        'add_header Strict-Transport-Security "max-age=3600" always;',
        "location = /_native_wifi_ready { return 404; }",
        "location / {",
        f"proxy_pass http://127.0.0.1:{port};",
        "proxy_next_upstream off; proxy_cache off;",
        "proxy_connect_timeout 5s; proxy_read_timeout 60s;",
        f'proxy_set_header Host "{config["hostname"]}:{config["port"]}";',
        "proxy_set_header X-Forwarded-Proto https;",
        'proxy_set_header X-Forwarded-For "";',
        'proxy_set_header X-Forwarded-Host "";',
        'proxy_set_header Forwarded "";',
        f"proxy_set_header X-GVA-Proxy {config['proxy_token']};",
        'proxy_set_header Connection "";',
        "}",
        "}",
        "}",
    ]
    return "\n".join(lines)


def setup(root, request):
    administrator()
    root = Path(root)
    with exclusive(root):
        if (root / "maintenance.json").exists():
            raise UnsafeOperation("Há manutenção por concluir.")
        target = root / "secrets/management-wifi"
        if target.exists():
            raise UnsafeOperation(
                "Configuração existente: desative e reveja a rotação com a informática."
            )
        source = Path(request["configuration"])
        refuse_reparse(source)
        config = json.loads(source.read_text())
        if config.get("it_approved") is not True:
            raise UnsafeOperation("Configuração exige aprovação da informática.")
        config["proxy_token"] = secrets.token_hex(32)
        config["enabled"] = False
        release = Path(read_state(root)["release"])
        render(root, release, config)
        for name in ("server-chain.crt", "server.key", "device-ca.crt", "device-ca.crl"):
            refuse_reparse(source.parent / name)
            if not (source.parent / name).is_file():
                raise UnsafeOperation("Certificado/chave/CRL em falta.")
        configure(
            root,
            release,
            create=not __import__("native_windows.windows", fromlist=["exists"]).exists(
                SERVICES["wifi"]
            ),
            only="wifi",
        )
        target.mkdir()
        protect(target, [("wifi", "R"), ("backup", "R")])
        protect(root / "secrets", [("web", "RX"), ("backup", "RX"), ("wifi", "RX")])
        for name in ("server-chain.crt", "server.key", "device-ca.crt", "device-ca.crl"):
            shutil.copyfile(source.parent / name, target / name)
        write_json(target / "config.json", config)
        runtime = root / "runtime/wifi"
        runtime.mkdir(exist_ok=True)
        protect(runtime, [("wifi", "M")])
        for kind in ("client_body", "proxy", "fastcgi", "scgi", "uwsgi"):
            (runtime / kind).mkdir(exist_ok=True)
        # Grant only the existing restricted application credentials, never owner.json.
        protect(root / "secrets/app.json", [("web", "R"), ("backup", "R"), ("wifi", "R")])
        protect(root / "signing", [("web", "R"), ("backup", "R"), ("wifi", "R")])


def control(root, request):
    administrator()
    root = Path(root)
    with exclusive(root):
        marker = root / "runtime/wifi/approved"
        marker.unlink(missing_ok=True)
        stop(SERVICES["wifi"])
        native(["sc.exe", "config", SERVICES["wifi"], "start=", "disabled"])
        if request.get("enable") is not True:
            return
        if request.get("it_network_ready") is not True or (root / "maintenance.json").exists():
            raise UnsafeOperation(
                "Confirme DNS, certificados individuais, CRL e firewall aprovada."
            )
        marker.write_text("approved")
        try:
            native(["sc.exe", "config", SERVICES["wifi"], "start=", "delayed-auto"])
            native(["sc.exe", "start", SERVICES["wifi"]])
            from .windows import service_state

            for _ in range(120):
                status = service_state(SERVICES["wifi"])
                if status == 4:
                    break
                if status == 1:
                    raise UnsafeOperation("O serviço Wi-Fi terminou durante o arranque.")
                time.sleep(0.5)
            else:
                raise UnsafeOperation("O serviço Wi-Fi não ficou disponível.")
        except Exception:
            marker.unlink(missing_ok=True)
            native(["sc.exe", "config", SERVICES["wifi"], "start=", "disabled"])
            raise


def start(root, stop_file):
    root = Path(root)
    if not approved(root):
        raise UnsafeOperation("Wi-Fi desativado; exige aprovação no destino.")
    state = read_state(root)
    release = Path(state["release"])
    config = json.loads((root / "secrets/management-wifi/config.json").read_text())
    runtime = root / "runtime/wifi"
    path = runtime / "nginx.conf"
    path.write_text(render(root, release, config))
    args = [str(release / "nginx/nginx.exe"), "-p", str(runtime) + "/", "-c", str(path)]
    subprocess.run(
        [*args, "-t"], check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    env = environment(root)
    env["DJANGO_SETTINGS_MODULE"] = "config.native_wifi"
    processes = []
    try:
        backend = subprocess.Popen(
            [str(release / "python/python.exe"), "-B", "-m", "native_windows.wifi_backend"],
            env=env,
            cwd=release / "app",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(backend)
        import urllib.request

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(60):
            if backend.poll() is not None:
                raise UnsafeOperation("Backend HTTPS terminou durante o arranque.")
            if not owns_listener(config["backend_port"], backend.pid):
                time.sleep(0.5)
                continue
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{config['backend_port']}/_native_wifi_ready",
                    headers={
                        "Host": f"{config['hostname']}:{config['port']}",
                        "X-Forwarded-Proto": "https",
                        "X-GVA-Proxy": config["proxy_token"],
                    },
                )
                with opener.open(req, timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.5)
        else:
            raise UnsafeOperation("Backend HTTPS indisponível.")
        if backend.poll() is not None or not owns_listener(config["backend_port"], backend.pid):
            raise UnsafeOperation("O listener não pertence ao backend autorizado.")
        proxy = subprocess.Popen(
            [*args, "-g", "daemon off;"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        processes.append(proxy)
        Path(str(stop_file) + ".ready").write_text("ready")
        while not Path(stop_file).exists():
            if any(p.poll() is not None for p in processes):
                raise UnsafeOperation("O acesso Wi-Fi parou.")
            time.sleep(0.5)
    finally:
        try:
            if len(processes) == 2 and processes[1].poll() is None:
                subprocess.run(
                    [*args, "-s", "quit"],
                    timeout=15,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                processes[1].wait(timeout=45)
        finally:
            # Only our HTTP/proxy children, never PostgreSQL. Roll back any
            # interrupted request instead of leaving an old backend orphaned.
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
