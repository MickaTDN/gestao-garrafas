"""Recovery ONLY into a new installation, using the matching code package."""

import json
import tempfile
from pathlib import Path

from .crypto_backup import decrypt
from .install import create_cluster, prepare_acl
from .maintenance import evidence, extract_verified, grants, pg_tool
from .package import UnsafeOperation
from .state import write_json
from .windows import administrator, configure, protect


def recover(root, release, manifest, request):
    administrator()
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        raise UnsafeOperation("A recuperação exige uma pasta NOVA; nenhum dado existente foi substituído.")
    root.mkdir(parents=True, exist_ok=True)
    protect(root)
    write_json(root / "maintenance.json", {"phase": "recovery-started"})
    with tempfile.TemporaryDirectory(dir=root, prefix=".restore-") as temp:
        plain = Path(temp) / "archive.tar"
        metadata = decrypt(request["archive"], plain, Path(request["recovery_key"]).read_bytes(), request["recovery_password"])
        if metadata["version"] != manifest["version"] or metadata["channel"] != manifest["channel"]:
            raise UnsafeOperation("Recupere primeiro com a versão exata do backup; atualize apenas depois da validação.")
        data = Path(temp) / "extracted"
        saved = extract_verified(plain, data)
        if metadata["instance"] != saved["instance"]:
            raise UnsafeOperation("Identidade do backup inconsistente.")
        state = json.loads((data / "installation.json").read_text())
        if state["database"] not in ("gva_native", "gva_native_synthetic") or state["postgres_major"] != 17:
            raise UnsafeOperation("Base de recuperação inválida.")
        from .windows import SERVICES, exists, free_port
        if any(exists(name) for name in SERVICES.values()):
            raise UnsafeOperation("A recuperação exige máquina/VM isolada sem estes serviços.")
        free_port(state["db_port"])
        free_port(state["http_port"])
        import shutil
        for name in ("secrets", "signing", "tls"):
            if (data / name).exists():
                shutil.copytree(data / name, root / name)
        for name in ("recovery-public.pem", "backup-policy.json", "publisher.json"):
            if (data / name).exists():
                shutil.copyfile(data / name, root / name)
        state["release"] = str(release)
        write_json(root / "installation.json", state)
        configure(root, release, create=True)
        prepare_acl(root)
        create_cluster(root)
        with (data / "database.dump").open("rb") as dump:
            pg_tool(root, "pg_restore", state["database"], stdin=dump)
        from .maintenance import connection
        with connection(root) as conn:
            if json.loads(json.dumps(evidence(conn))) != saved["evidence"]:
                raise UnsafeOperation("O restauro difere do original; arranque continua bloqueado.")
        grants(root)
        write_json(root / "recovery-verified.json", {"instance": state["instance"], "version": state["version"], "status": "verified-awaiting-IT-cutover"})
    # Keep services disabled and journal present. Restored source may have a stale
    # Android sequence/history: no automatic publication, cutover or duplicate origin.
