"""Native adaptation of the reviewed static HTTPS/mTLS publisher, disabled by default."""

import ipaddress
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from .package import UnsafeOperation
from .runtime import read_state
from .state import write_json
from .windows import SERVICES, configure, native

TLS_FILES = ("server-chain.crt", "server.key", "device-ca.crt", "device-ca.crl")


def render(release, root, config):
    address = ipaddress.IPv4Address(config["address"])
    allowed_private = any(
        address in ipaddress.ip_network(net)
        for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    )
    if (
        not allowed_private
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", config["hostname"])
        or "." not in config["hostname"]
    ):
        raise UnsafeOperation("Use um endereço RFC1918 e DNS interno aprovados pela informática.")
    clients = [ipaddress.ip_network(item, strict=True) for item in config["clients"]]
    if not clients or any(
        net.version != 4
        or not any(
            net.subnet_of(ipaddress.ip_network(base))
            for base in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
        )
        for net in clients
    ):
        raise UnsafeOperation(
            "A lista autorizada deve conter apenas redes/dispositivos RFC1918 explícitos."
        )
    port = config.get("port", 8444)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise UnsafeOperation("Porta HTTPS inválida.")
    paths = [Path(root), Path(release)]
    if any(any(char in str(path) for char in ('"', "$", "\n", "\r", ";")) for path in paths):
        raise UnsafeOperation("Caminho do publicador contém caracteres não suportados.")

    def quote(path):
        return '"' + Path(path).as_posix() + '"'

    runtime = Path(root) / "runtime/publisher"
    template = (Path(release) / "app/deploy/vertente/nginx.conf.template").read_text()
    template = template.replace("__HOST__", config["hostname"])
    template = template.replace("/dev/stderr", quote(runtime / "error.log"))
    template = template.replace("/tmp/nginx.pid", quote(runtime / "nginx.pid"))
    template = template.replace(
        "include /etc/nginx/mime.types", "include " + quote(Path(release) / "nginx/conf/mime.types")
    )
    template = template.replace(
        "include /etc/nginx/clients.conf;", "\n".join(f"allow {net};" for net in clients)
    )
    template = template.replace("/srv/vertente", quote(Path(release) / "app/vertente"))
    for name in TLS_FILES:
        template = template.replace("/run/tls/" + name, quote(Path(root) / "tls" / name))
    for name in ("client", "proxy", "fastcgi", "scgi", "uwsgi"):
        template = template.replace("/tmp/" + name, quote(runtime / name))
    template = template.replace("listen 8444 ssl", f"listen {address}:{port} ssl")
    return template


def configure_publisher(root, config_file):
    config_file = Path(config_file)
    config = json.loads(config_file.read_text())
    if config.get("it_approved") is not True:
        raise UnsafeOperation(
            "A configuração de rede/certificados exige aprovação explícita da informática."
        )
    root = Path(root)
    release = Path(read_state(root)["release"])
    text = render(release, root, config)
    if (root / "publisher.json").exists():
        raise UnsafeOperation(
            "O publicador já existe; pare-o e reveja a rotação com a informática."
        )
    for name in TLS_FILES:
        source = config_file.parent / name
        if not source.is_file() or source.is_symlink() or (root / "tls" / name).exists():
            raise UnsafeOperation("Certificados/CRL em falta ou destino existente.")
    for name in TLS_FILES:
        shutil.copyfile(config_file.parent / name, root / "tls" / name)
    for name in ("client", "proxy", "fastcgi", "scgi", "uwsgi"):
        (root / "runtime/publisher" / name).mkdir(exist_ok=True)
    (root / "runtime/publisher/nginx.conf").write_text(text)
    native(
        [
            release / "nginx/nginx.exe",
            "-t",
            "-p",
            str(root / "runtime/publisher") + "/",
            "-c",
            root / "runtime/publisher/nginx.conf",
        ]
    )
    config["enabled"] = False
    write_json(root / "publisher.json", config)
    from .windows import exists

    configure(root, release, create=not exists(SERVICES["publisher"]), only="publisher")
    # Never creates a firewall exception or activates network access automatically.


def start(root, stop_file):
    root = Path(root)
    release = Path(read_state(root)["release"])
    config = json.loads((root / "publisher.json").read_text())
    runtime = root / "runtime/publisher"
    # Re-render public paths after updates, while TLS identity stays outside the program.
    (runtime / "nginx.conf").write_text(render(release, root, config))
    args = [
        str(release / "nginx/nginx.exe"),
        "-p",
        str(runtime) + "/",
        "-c",
        str(runtime / "nginx.conf"),
    ]
    subprocess.run([*args, "-t"], check=True, timeout=20)
    process = subprocess.Popen([*args, "-g", "daemon off;"])
    Path(str(stop_file) + ".ready").write_text("ready")
    try:
        while not Path(stop_file).exists():
            if process.poll() is not None:
                raise UnsafeOperation("O publicador HTTPS parou.")
            time.sleep(0.5)
    finally:
        subprocess.run([*args, "-s", "quit"], check=True, timeout=15)
        process.wait(timeout=60)


def enable(root, request):
    from .state import exclusive

    root = Path(root)
    if request.get("it_network_ready") is not True:
        raise UnsafeOperation(
            "É necessária conferência explícita de certificados, DNS, dispositivos e firewall pela informática."
        )
    with exclusive(root):
        if (root / "maintenance.json").exists():
            raise UnsafeOperation("Há manutenção por concluir.")
        config = json.loads((root / "publisher.json").read_text())
        render(Path(read_state(root)["release"]), root, config)
        native(["sc.exe", "config", SERVICES["publisher"], "start=", "delayed-auto"])
        native(["sc.exe", "start", SERVICES["publisher"]])
        config["enabled"] = True
        write_json(root / "publisher.json", config)
