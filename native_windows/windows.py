"""Windows-only OS boundary. No global policy, firewall, router or Docker changes."""

import ctypes
import os
import socket
import subprocess
import time
from pathlib import Path

from .package import UnsafeOperation

SERVICES = {"postgres": "GVAPostgres17", "web": "GVAWeb", "backup": "GVABackup", "publisher": "GVAPublisher"}


def native(args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def administrator():
    if os.name != "nt" or not ctypes.windll.shell32.IsUserAnAdmin():
        raise UnsafeOperation("A instalação/manutenção exige autorização de administrador da informática.")


def protect(path, grants=()):
    """Explicit DACL; names use SIDs except Windows virtual service accounts."""
    command = ["icacls.exe", str(path), "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"]
    for account, access in grants:
        command.append(f"NT SERVICE\\{SERVICES[account]}:(OI)(CI){access}")
    native(command)


def free_port(port):
    with socket.socket() as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(("127.0.0.1", port))


def exists(name):
    return subprocess.run(["sc.exe", "query", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def stopped(name):
    # Query numeric service state through the .NET host, never localized sc text.
    result = subprocess.run(["sc.exe", "query", name], capture_output=True, text=True)
    import re
    return result.returncode == 0 and bool(re.search(r"STATE\s*:\s*1\s", result.stdout))


def stop(name):
    if not exists(name):
        return
    subprocess.run(["sc.exe", "stop", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(90):
        if stopped(name):
            return
        time.sleep(1)
    raise UnsafeOperation("O serviço não terminou de forma controlada. Atualização interrompida.")


def configure(root, release, *, create=False, only=None):
    for kind, name in SERVICES.items():
        if only and kind != only:
            continue
        if kind == "publisher" and not (Path(root) / "publisher.json").exists():
            continue
        binary = f'"{Path(release) / "host/GVA.Native.exe"}" --service {kind}'
        command = ["sc.exe", "create" if create else "config", name, "binPath=", binary, "start=", "disabled", "obj=", f"NT SERVICE\\{name}"]
        if kind != "postgres":
            command += ["depend=", SERVICES["postgres"]] if kind != "publisher" else []
        native(command)
        native(["sc.exe", "sidtype", name, "unrestricted"])
        native(["sc.exe", "description", name, f"Gestão Vertente Aveludada — {kind}; dados locais preservados na desinstalação."])
        # No automatic restart loop after maintenance or a failed migration.


def disable_all():
    for name in SERVICES.values():
        if exists(name):
            native(["sc.exe", "config", name, "start=", "disabled"])


def stop_all():
    for kind in ("publisher", "backup", "web", "postgres"):
        stop(SERVICES[kind])


def activate():
    for kind in ("postgres", "web", "backup", "publisher"):
        name = SERVICES[kind]
        if exists(name):
            native(["sc.exe", "config", name, "start=", "delayed-auto" if kind != "postgres" else "auto"])
            native(["sc.exe", "start", name])


def uninstall():
    administrator()
    disable_all()
    stop_all()
    for name in SERVICES.values():
        if exists(name):
            native(["sc.exe", "delete", name])
    # Intentionally no filesystem deletion, SQL DROP, retention or key changes.
