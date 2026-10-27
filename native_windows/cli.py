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
    suffix = "GestaoVertenteAveludada-Teste" if channel == "synthetic" else "GestaoVertenteAveludada"
    return Path(os.environ["PROGRAMDATA"]) / suffix


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("verify", "install", "update", "service", "backup", "uninstall", "publisher", "recover"))
    parser.add_argument("--package")
    parser.add_argument("--trust")
    parser.add_argument("--request")
    parser.add_argument("--kind")
    parser.add_argument("--stop-file")
    args = parser.parse_args()
    root = data_root()
    if args.action == "service":
        from .runtime import service
        service(root, args.kind, args.stop_file)
        return
    from .windows import administrator
    administrator()
    if args.action in ("verify", "install", "update", "recover"):
        from .package import verify
        installed = json.loads((root / "installation.json").read_text()) if (root / "installation.json").exists() else None
        manifest = verify(args.package, args.trust, installed=installed if args.action != "recover" else None)
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
        initial(root, release, manifest, request)
    elif args.action == "update":
        from .maintenance import UpdateActions
        from .state import update
        update(root, manifest, UpdateActions(root, release, request["recovery_key"], request["recovery_password"]))
    elif args.action == "recover":
        from .recover import recover
        recover(root, release, manifest, request)
    elif args.action == "backup":
        from .maintenance import backup
        backup(root)
    elif args.action == "uninstall":
        from .windows import uninstall
        uninstall()
    elif args.action == "publisher":
        from .publisher import configure_publisher
        configure_publisher(root, request["configuration"])


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # No raw SQL, dump errors, request files, credentials or private file contents.
        message = str(error) if isinstance(error, UnsafeOperation) else "A operação falhou. Preserve os dados e contacte a informática. Categoria: " + type(error).__name__
        print(message, file=sys.stderr)
        sys.exit(1)
