"""Strict offline package authentication, inventory and forward-only versions."""

import base64
import hashlib
import json
import re
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

CONTEXT = b"gva-windows-package-v1\0"


class UnsafeOperation(RuntimeError):
    pass


def version(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value
    ):
        raise UnsafeOperation("Versão inválida; use major.minor.patch.")
    return tuple(map(int, value.split(".")))


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def regular_tree(root):
    root = Path(root)
    found = {}
    for path in root.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise UnsafeOperation("O pacote contém links ou junções.")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            if any(part in ("..", ".") for part in name.split("/")) or ":" in name:
                raise UnsafeOperation("Caminho inválido no pacote.")
            found[name] = {"size": path.stat().st_size, "sha256": digest(path)}
    return found


def verify(root, trust_path, installed=None):
    root = Path(root)
    raw = (root / "package.json").read_bytes()
    if len(raw) > 8 * 1024 * 1024:
        raise UnsafeOperation("Manifesto demasiado grande.")
    trust = json.loads(Path(trust_path).read_text())
    try:
        key = serialization.load_pem_public_key(trust["public_key"].encode())
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError
        key.verify(
            base64.b64decode((root / "package.sig").read_bytes(), validate=True),
            CONTEXT + raw,
            ec.ECDSA(hashes.SHA256()),
        )
        manifest = json.loads(raw)
        if set(manifest) != {
            "schema",
            "version",
            "minimum_version",
            "postgres_major",
            "channel",
            "files",
        }:
            raise ValueError
        if (
            manifest["schema"] != 1
            or manifest["postgres_major"] != 17
            or manifest["channel"] != trust["channel"]
        ):
            raise ValueError
        current = version(manifest["version"])
        minimum = version(manifest["minimum_version"])
        if minimum > current:
            raise ValueError
        if installed:
            if (
                installed["channel"] != manifest["channel"]
                or version(installed["version"]) >= current
                or version(installed["version"]) < minimum
            ):
                raise UnsafeOperation(
                    "Atualização antiga, repetida ou incompatível. Os dados não foram alterados."
                )
        actual = regular_tree(root / "payload")
        if not actual or actual != manifest["files"]:
            raise ValueError
        required = {
            "python/python.exe",
            "postgres/bin/postgres.exe",
            "postgres/bin/pg_dump.exe",
            "postgres/bin/pg_restore.exe",
            "app/manage.py",
            "host/GVA.Native.exe",
            "nginx/nginx.exe",
        }
        if not required.issubset(actual):
            raise ValueError
    except UnsafeOperation:
        raise
    except Exception as error:
        raise UnsafeOperation("Pacote inválido, alterado ou sem assinatura autorizada.") from error
    return manifest


def refuse_reparse(path):
    path = Path(path)
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise UnsafeOperation(
                "Não são permitidos links/junções nas pastas de programa ou dados."
            )
