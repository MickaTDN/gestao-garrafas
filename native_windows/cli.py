"""Private installer/service entry point. Sanitized errors, no secrets on argv."""

import argparse
import json
import os
import sys
from pathlib import Path

from .package import UnsafeOperation


def data_root():
    # The host pins the channel at build time, not from a browser-controlled value.
    channel = os.environ.get("GVA_NATIVE_CHANNEL", "release")
    suffix = (
        "GestaoVertenteAveludada-Teste" if channel == "synthetic" else "GestaoVertenteAveludada"
    )
    if os.name != "nt":
        raise UnsafeOperation("Este instalador exige Windows.")
    # Read the Windows known folder, not an overrideable PROGRAMDATA variable.
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    import uuid

    folder = GUID.from_buffer_copy(uuid.UUID("62AB5D82-FDC1-4DC3-A9DD-070D1D495D97").bytes_le)
    pointer = ctypes.c_void_p()
    result = ctypes.windll.shell32.SHGetKnownFolderPath(
        ctypes.byref(folder), 0, None, ctypes.byref(pointer)
    )
    if result:
        raise UnsafeOperation("Não foi possível localizar ProgramData de forma segura.")
    try:
        return Path(ctypes.wstring_at(pointer)) / suffix
    finally:
        ctypes.windll.ole32.CoTaskMemFree(pointer)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "verify",
            "install",
            "update",
            "service",
            "backup",
            "uninstall",
            "publisher",
            "recover",
            "approve-recovery",
            "enable-publisher",
        ),
    )
    parser.add_argument("--package")
    parser.add_argument("--trust")
    parser.add_argument("--request")
    parser.add_argument("--kind")
    parser.add_argument("--stop-file")
    args = parser.parse_args()
    root = data_root()
    from .package import refuse_reparse

    refuse_reparse(root)
    if args.action == "service":
        from .runtime import service

        service(root, args.kind, args.stop_file)
        return
    from .windows import administrator

    administrator()
    if args.action in ("verify", "install", "update", "recover"):
        from .package import verify

        installed = (
            json.loads((root / "installation.json").read_text())
            if (root / "installation.json").exists()
            else None
        )
        trust_path = root / "package-policy.json" if installed else Path(args.trust)
        manifest = verify(
            args.package, trust_path, installed=installed if args.action != "recover" else None
        )
        if args.action == "verify":
            return
        release = Path(args.package) / "payload"
    request = {}
    if args.request:
        # GUI writes only an ACL-restricted temporary file, removed even on failure.
        request_path = Path(args.request)
        try:
            request = json.loads(request_path.read_text(encoding="utf-8-sig"))
        finally:
            request_path.unlink(missing_ok=True)
    if args.action == "install":
        from .install import initial

        initial(root, release, manifest, request, trust_path)
    elif args.action == "update":
        from .maintenance import UpdateActions
        from .state import update

        update(
            root,
            manifest,
            UpdateActions(root, release, request["recovery_key"], request["recovery_password"]),
        )
    elif args.action == "recover":
        from .recover import recover

        recover(root, release, manifest, request)
    elif args.action == "backup":
        from .maintenance import backup
        from .state import exclusive

        with exclusive(root):
            if (root / "maintenance.json").exists():
                raise UnsafeOperation("Há manutenção por concluir; não inicie outro backup manual.")
            backup(root)
    elif args.action == "uninstall":
        from .windows import uninstall

        uninstall()
    elif args.action == "approve-recovery":
        from .recover import approve_recovery

        approve_recovery(root, request)
    elif args.action == "enable-publisher":
        from .publisher import enable

        enable(root, request)
    elif args.action == "publisher":
        from .publisher import configure_publisher
        from .state import exclusive

        with exclusive(root):
            if (root / "maintenance.json").exists():
                raise UnsafeOperation("Há manutenção por concluir.")
            configure_publisher(root, request["configuration"])


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # No raw SQL, dump errors, request files, credentials or private file contents.
        message = (
            str(error)
            if isinstance(error, UnsafeOperation)
            else "A operação falhou. Preserve os dados e contacte a informática. Categoria: "
            + type(error).__name__
        )
        print(message, file=sys.stderr)
        sys.exit(1)
