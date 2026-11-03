"""Optional device-only receiver. Selectively reuses the reviewed PR #28 gateway lifecycle."""

import json
import re
import secrets
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .loopback_proxy import owns_listener
from .package import UnsafeOperation, refuse_reparse
from .receiver_policy import origin
from .runtime import environment, manage, read_state
from .state import exclusive, write_json
from .windows import SERVICES, administrator, configure, exists, native, protect, stop

TLS_FILES = ("server-chain.crt", "server.key", "device-ca.crt", "device-ca.crl")


def approved(root):
    return (Path(root) / "runtime/receiver/approved").is_file()


def prepare_account(root):
    """Opt-in upgrades may predate this account; add only its exact read grants.

    Never reset parent DACLs or propagate an extra reader to owner/recovery secrets.
    Existing accounts, backup protections and sibling gateway ACLs remain intact.
    """
    root = Path(root)
    for path, access in [
        (root, "RX"),
        (root / "runtime", "RX"),
        (root / "secrets", "RX"),
        (root / "signing", "RX"),
        (root / "installation.json", "R"),
        (root / "secrets/app.json", "R"),
        (root / "signing/signing.pem", "R"),
        (root / "signing/pending-reception.pem", "R"),
    ]:
        native(
            ["icacls.exe", str(path), "/grant:r", f"NT SERVICE\\{SERVICES['receiver']}:{access}"]
        )


def render(root, release, config):
    from .publisher import validate_network

    validate_network(release, root, config)
    receiver = origin(f"https://{config['hostname']}:{config['port']}")
    stock = origin(config["stock_origin"])
    state = read_state(root)
    ports = (config["port"], config["backend_port"])
    if (
        any(type(p) is not int or not 1024 <= p <= 65535 for p in ports)
        or len(set(ports)) != 2
        or any(
            p in (state["db_port"], state["http_port"], urlsplit(stock).port or 443) for p in ports
        )
        or receiver == stock
        or not re.fullmatch(r"[a-f0-9]{64}", config["proxy_token"])
    ):
        raise UnsafeOperation("Portas/origens de receção inválidas ou sobrepostas.")
    management = Path(root) / "secrets/management-wifi/config.json"
    if management.exists():
        cfg = json.loads(management.read_text())
        if set(ports) & {cfg["port"], cfg["backend_port"]}:
            raise UnsafeOperation(
                "A receção não pode partilhar as portas da gestão administrativa."
            )
    devices = config["devices"]
    if not isinstance(devices, dict) or not 1 <= len(devices) <= 256:
        raise UnsafeOperation("Configure certificados individuais explicitamente autorizados.")
    for fingerprint, device in devices.items():
        if not re.fullmatch(r"[a-f0-9]{64}", fingerprint) or str(uuid.UUID(device)) != device:
            raise UnsafeOperation("Associação certificado/dispositivo inválida.")
    runtime, tls = Path(root) / "runtime/receiver", Path(root) / "secrets/sheet-receiver"

    def q(path):
        return '"' + path.as_posix() + '"'

    lines = [
        f"pid {q(runtime / 'nginx.pid')};",
        f"error_log {q(runtime / 'error.log')} warn;",
        "events { worker_connections 128; }",
        "http { access_log off; server_tokens off;",
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
        "deny all; client_max_body_size 1m;",
        'add_header Strict-Transport-Security "max-age=3600" always;',
        "location = /v1/pending-sheets {",
        "limit_except POST OPTIONS { deny all; }",
        f"proxy_pass http://127.0.0.1:{config['backend_port']};",
        "proxy_next_upstream off; proxy_cache off; proxy_connect_timeout 5s; proxy_read_timeout 60s;",
        f'proxy_set_header Host "{config["hostname"]}:{config["port"]}";',
        "proxy_set_header X-Forwarded-Proto https;",
        'proxy_set_header X-Forwarded-For "";',
        'proxy_set_header X-Forwarded-Host "";',
        'proxy_set_header Forwarded "";',
        f"proxy_set_header X-GVA-Proxy {config['proxy_token']};",
        "proxy_set_header X-GVA-Cert $ssl_client_escaped_cert;",
        "proxy_set_header X-GVA-Verified $ssl_client_verify;",
        'proxy_set_header Cookie "";',
        'proxy_set_header Authorization "";',
        'proxy_set_header Connection "";',
        "}",
        "location / { return 404; }",
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
        target = root / "secrets/sheet-receiver"
        if target.exists():
            raise UnsafeOperation(
                "Configuração existente: desative e solicite rotação/revisão à informática."
            )
        source = Path(request["configuration"])
        refuse_reparse(source)
        config = json.loads(source.read_text())
        if config.get("it_approved") is not True:
            raise UnsafeOperation("Exige aprovação explícita da informática.")
        config.update(proxy_token=secrets.token_hex(32), enabled=False)
        config["origin"] = f"https://{config['hostname']}:{config['port']}"
        release = Path(read_state(root)["release"])
        render(root, release, config)
        for name in TLS_FILES:
            refuse_reparse(source.parent / name)
            if not (source.parent / name).is_file():
                raise UnsafeOperation("Certificados/CRL em falta.")
        configure(root, release, create=not exists(SERVICES["receiver"]), only="receiver")
        prepare_account(root)
        target.mkdir()
        protect(target, [("receiver", "R"), ("backup", "R")])
        for name in TLS_FILES:
            shutil.copyfile(source.parent / name, target / name)
        write_json(target / "config.json", config)
        runtime = root / "runtime/receiver"
        runtime.mkdir(exist_ok=True)
        protect(runtime, [("receiver", "M")])
        for kind in ("client_body", "proxy", "fastcgi", "scgi", "uwsgi", "tmp"):
            (runtime / kind).mkdir(exist_ok=True)
        manage(
            root,
            "sheet_transport_policy",
            "--receiver-origin",
            config["origin"],
            "--stock-origin",
            config["stock_origin"],
            "--output",
            str(root / "tls/sheet-transport.public.json"),
        )


def control(root, request):
    administrator()
    root = Path(root)
    with exclusive(root):
        marker = root / "runtime/receiver/approved"
        marker.unlink(missing_ok=True)
        stop(SERVICES["receiver"])
        native(["sc.exe", "config", SERVICES["receiver"], "start=", "disabled"])
        if request.get("enable") is not True:
            return
        if request.get("it_network_ready") is not True or (root / "maintenance.json").exists():
            raise UnsafeOperation(
                "Confirme DNS, certificados individuais, CRL e firewall restrita aprovados."
            )
        marker.write_text("approved")
        try:
            native(["sc.exe", "config", SERVICES["receiver"], "start=", "delayed-auto"])
            native(["sc.exe", "start", SERVICES["receiver"]])
            from .windows import service_state

            for _ in range(120):
                status = service_state(SERVICES["receiver"])
                if status == 4:
                    break
                if status == 1:
                    raise UnsafeOperation("O serviço de receção terminou durante o arranque.")
                time.sleep(0.5)
            else:
                raise UnsafeOperation("A receção não ficou disponível.")
        except Exception:
            marker.unlink(missing_ok=True)
            native(["sc.exe", "config", SERVICES["receiver"], "start=", "disabled"])
            raise


def start(root, stop_file):
    root = Path(root)
    if not approved(root):
        raise UnsafeOperation("Receção Wi-Fi desativada; exige aprovação no destino.")
    release = Path(read_state(root)["release"])
    config = json.loads((root / "secrets/sheet-receiver/config.json").read_text())
    runtime = root / "runtime/receiver"

    def phase(value):
        write_json(runtime / "startup.json", {"phase": value})

    phase("render")
    path = runtime / "nginx.conf"
    path.write_text(render(root, release, config))
    args = [str(release / "nginx/nginx.exe"), "-p", str(runtime) + "/", "-c", str(path)]
    phase("nginx_validation")
    subprocess.run(
        [*args, "-t"], check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    env = environment(root)
    env.update(
        DJANGO_SETTINGS_MODULE="config.native_sheet_receiver",
        TMP=str(runtime / "tmp"),
        TEMP=str(runtime / "tmp"),
    )
    processes = []
    try:
        phase("backend_start")
        backend = subprocess.Popen(
            [str(release / "python/python.exe"), "-B", "-m", "native_windows.receiver_backend"],
            env=env,
            cwd=release / "app",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(backend)
        import urllib.request

        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        phase("backend_readiness")
        for _ in range(60):
            if backend.poll() is not None:
                raise UnsafeOperation("Backend de receção terminou.")
            if owns_listener(config["backend_port"], backend.pid):
                try:
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{config['backend_port']}/_sheet_receiver_ready",
                        headers={
                            "Host": config["origin"].removeprefix("https://"),
                            "X-Forwarded-Proto": "https",
                            "X-GVA-Proxy": config["proxy_token"],
                        },
                    )
                    with opener.open(req, timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
            time.sleep(0.5)
        else:
            raise UnsafeOperation("Backend de receção indisponível.")
        if backend.poll() is not None or not owns_listener(config["backend_port"], backend.pid):
            raise UnsafeOperation("Listener não pertence ao backend autorizado.")
        phase("proxy_start")
        proxy = subprocess.Popen(
            [*args, "-g", "daemon off;"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        processes.append(proxy)
        phase("running")
        Path(str(stop_file) + ".ready").write_text("ready")
        while not Path(stop_file).exists():
            if any(p.poll() is not None for p in processes):
                raise UnsafeOperation("A receção Wi-Fi parou.")
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
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
