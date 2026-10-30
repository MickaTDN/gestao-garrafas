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
            old = version(installed["version"])
            repair = installed.get("uninstalled") is True and old == current
            if repair and installed.get("package_sha256") != hashlib.sha256(raw).hexdigest():
                raise UnsafeOperation(
                    "Repor o programa exige o instalador exato anteriormente instalado."
                )
            if (
                installed["channel"] != manifest["channel"]
                or (old >= current and not repair)
                or (installed.get("uninstalled") is True and not repair)
                or old < minimum
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
            "service/GVA.Native.exe",
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


def copy_reviewed_source(source_root, destination, tracked, *, prefixes=(), explicit=()):
    """Ignored local workbooks/secrets can never become installer contents."""
    import shutil

    source_root, destination = Path(source_root), Path(destination)
    private_suffixes = {
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".xlsx",
        ".xls",
        ".csv",
        ".dump",
        ".backup",
        ".gvabackup",
        ".pdf",
    }
    for name in tracked:
        path = Path(name)
        if not (name in explicit or any(name.startswith(prefix + "/") for prefix in prefixes)):
            continue
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        if (
            path.is_absolute()
            or ".." in path.parts
            or ":" in name
            or path.suffix.lower() in private_suffixes
            or name.endswith(
                (
                    ".vastock.json",
                    ".vaprefs.json",
                    ".vagrant.json",
                    ".vareceipts.json",
                    ".vatrust.json",
                    ".varequest.json",
                )
            )
            or any(part in {"private", "secrets", "media", "backups"} for part in path.parts)
        ):
            raise UnsafeOperation(
                "Ficheiro privado ou caminho inválido entre os fontes do instalador."
            )
        source = source_root / path
        if source.is_symlink() or source.is_junction() or not source.is_file():
            raise UnsafeOperation("Os fontes revistos devem ser ficheiros regulares.")
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def reject_private_material(payload):
    """Public CA bundles are allowed; private keys and datasets are not."""
    pattern = re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=]{32,}"
    )
    for path in Path(payload).rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(payload)
        if path.suffix.lower() in {
            ".key",
            ".pfx",
            ".p12",
            ".xlsx",
            ".xls",
            ".csv",
            ".dump",
            ".backup",
            ".gvabackup",
        } or (relative.parts[0] == "postgres" and "data" in relative.parts[1:]):
            raise UnsafeOperation("Material privado/dados de utilizador recusados no instalador.")
        with path.open("rb") as stream:
            overlap = b""
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                if pattern.search(overlap + block):
                    raise UnsafeOperation("Chave privada recusada no instalador.")
                overlap = block[-4096:]
