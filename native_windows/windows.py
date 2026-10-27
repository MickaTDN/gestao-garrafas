"""Windows-only OS boundary. No global policy, firewall, router or Docker changes."""

import ctypes
import os
import socket
import subprocess
import time
from pathlib import Path

from .package import UnsafeOperation

SERVICES = {
    "postgres": "GVAPostgres17",
    "web": "GVAWeb",
    "backup": "GVABackup",
    "publisher": "GVAPublisher",
}


def native(args, **kwargs):
    result = subprocess.run(
        list(map(str, args)), timeout=120, capture_output=True, text=True, **kwargs
    )
    if result.returncode:
        detail = ""
        if os.getenv("GVA_NATIVE_CHANNEL") == "synthetic" and os.getenv("GITHUB_ACTIONS") == "true":
            detail = ": " + (result.stdout + result.stderr)[-1800:]
        raise UnsafeOperation(
            "Falha no componente "
            + Path(str(args[0])).name
            + "; código "
            + str(result.returncode)
            + detail
        )
    return result


def administrator():
    if os.name != "nt" or not ctypes.windll.shell32.IsUserAnAdmin():
        raise UnsafeOperation(
            "A instalação/manutenção exige autorização de administrador da informática."
        )


def protect(path, grants=()):
    """Explicit DACL; names use SIDs except Windows virtual service accounts."""
    flags = "(OI)(CI)" if Path(path).is_dir() else ""
    command = [
        "icacls.exe",
        str(path),
        "/inheritance:r",
        "/grant:r",
        f"*S-1-5-18:{flags}F",
        "/grant:r",
        f"*S-1-5-32-544:{flags}F",
    ]
    for account, access in grants:
        command += ["/grant:r", f"NT SERVICE\\{SERVICES[account]}:{flags}{access}"]
    native(command)


def free_port(port):
    with socket.socket() as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind(("127.0.0.1", port))


def service_state(name):
    """Invariant SCM API: never parse localized sc.exe output on Portuguese Windows."""
    from ctypes import wintypes

    class Status(ctypes.Structure):
        _fields_ = [
            (field, wintypes.DWORD)
            for field in ("type", "state", "accepted", "exit", "specific", "checkpoint", "hint")
        ]

    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    api.OpenSCManagerW.restype = wintypes.HANDLE
    api.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    api.OpenServiceW.restype = wintypes.HANDLE
    api.QueryServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(Status)]
    api.QueryServiceStatus.restype = wintypes.BOOL
    api.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    manager = api.OpenSCManagerW(None, None, 1)
    if not manager:
        raise UnsafeOperation("Não foi possível consultar o gestor de serviços Windows.")
    handle = None
    try:
        handle = api.OpenServiceW(manager, name, 4)
        if not handle:
            if ctypes.get_last_error() == 1060:
                return None
            raise UnsafeOperation("Não foi possível consultar o serviço autorizado.")
        status = Status()
        if not api.QueryServiceStatus(handle, ctypes.byref(status)):
            raise UnsafeOperation("Não foi possível obter o estado do serviço.")
        return status.state
    finally:
        if handle:
            api.CloseServiceHandle(handle)
        api.CloseServiceHandle(manager)


def exists(name):
    return service_state(name) is not None


def stopped(name):
    return service_state(name) in (None, 1)


def stop(name):
    if not exists(name):
        return
    subprocess.run(["sc.exe", "stop", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(150):
        if stopped(name):
            return
        subprocess.run(
            ["sc.exe", "stop", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        time.sleep(1)
    raise UnsafeOperation("O serviço não terminou de forma controlada. Atualização interrompida.")


def configure(root, release, *, create=False, only=None):
    for kind, name in SERVICES.items():
        if only and kind != only:
            continue
        binary = f'"{Path(release) / "service/GVA.Native.exe"}" --service {kind}'
        command = [
            "sc.exe",
            "create" if create else "config",
            name,
            "binPath=",
            binary,
            "start=",
            "disabled",
            "obj=",
            f"NT SERVICE\\{name}",
        ]
        if kind != "postgres":
            command += ["depend=", SERVICES["postgres"]] if kind != "publisher" else []
        native(command)
        native(["sc.exe", "sidtype", name, "unrestricted"])
        native(
            [
                "sc.exe",
                "description",
                name,
                f"Gestão Vertente Aveludada — {kind}; dados locais preservados na desinstalação.",
            ]
        )
        # No automatic restart loop after maintenance or a failed migration.


def disable_all():
    for name in SERVICES.values():
        if exists(name):
            native(["sc.exe", "config", name, "start=", "disabled"])


def stop_all():
    for kind in ("publisher", "backup", "web", "postgres"):
        stop(SERVICES[kind])


def activate(root):
    for kind in ("postgres", "web", "backup", "publisher"):
        name = SERVICES[kind]
        if kind == "publisher":
            import json

            config = Path(root) / "publisher.json"
            if not config.is_file() or json.loads(config.read_text()).get("enabled") is not True:
                continue
        if exists(name):
            native(
                [
                    "sc.exe",
                    "config",
                    name,
                    "start=",
                    "delayed-auto" if kind != "postgres" else "auto",
                ]
            )
            state = service_state(name)
            if state not in (2, 4):
                native(["sc.exe", "start", name])
            for _ in range(150):
                if service_state(name) == 4:
                    break
                time.sleep(1)
            else:
                raise UnsafeOperation(
                    "O serviço não ficou disponível; preserve os dados e consulte o diagnóstico."
                )


def uninstall():
    administrator()
    disable_all()
    stop_all()
    for name in SERVICES.values():
        if exists(name):
            native(["sc.exe", "delete", name])
    # Intentionally no filesystem deletion, SQL DROP, retention or key changes.
