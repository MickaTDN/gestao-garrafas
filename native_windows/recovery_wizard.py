"""Verified recovery with explicit consent and preservation of the previous root.

No in-place pg_restore, SQL DROP or automatic schema migration. The replacement
uses a fresh cluster. A crash leaves a journal and both roots, never silent success.
"""

import hashlib
import json
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from .crypto_backup import LIMIT
from .install import create_cluster, health_http, prepare_acl, wait_database
from .maintenance import connection, evidence, extract_verified, grants, matching_evidence, pg_tool
from .package import UnsafeOperation, digest, refuse_reparse, version
from .portable import decrypt_backup, header
from .runtime import manage, read_state
from .state import exclusive, write_json
from .windows import (
    SERVICES,
    activate,
    administrator,
    configure,
    disable_all,
    exists,
    free_port,
    native,
    protect,
    stop_all,
)


def validate_snapshot(data, metadata, saved, manifest):
    state = json.loads((data / "installation.json").read_text())
    for field in ("instance", "version", "channel", "package_sha256"):
        if metadata.get(field) != saved.get(field) or saved.get(field) != state.get(field):
            raise UnsafeOperation("Identidade ou versão inconsistente no backup.")
    uuid.UUID(state["instance"])
    if (
        state.get("schema") != 1
        or state.get("postgres_major") != 17
        or state.get("database") not in ("gva_native", "gva_native_synthetic")
        or state["channel"] != manifest["channel"]
        or (state["channel"] == "synthetic" and state["database"] != "gva_native_synthetic")
        or not version(manifest["minimum_version"])
        <= version(state["version"])
        <= version(manifest["version"])
    ):
        raise UnsafeOperation(
            "Backup incompatível com a versão/canal deste instalador. Nenhum dado existente foi substituído."
        )
    for port in (state.get("db_port"), state.get("http_port")):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise UnsafeOperation("Porta inválida no backup.")
    if state["db_port"] == state["http_port"]:
        raise UnsafeOperation("Portas incompatíveis no backup.")
    for name, user in (("owner", "gva_owner"), ("app", "gva_web")):
        value = json.loads((data / f"secrets/{name}.json").read_text())
        if (
            value.get("username") != user
            or not value.get("password")
            or not value.get("django_key")
        ):
            raise UnsafeOperation("Credenciais internas incompletas no backup.")
    required = (
        "recovery-public.pem",
        "package-policy.json",
        "backup-policy.json",
        "signing/signing.pem",
        "signing/origin.vatrust.json",
    )
    if any(not (data / name).is_file() for name in required):
        raise UnsafeOperation("Faltam configurações ou chaves necessárias à recuperação.")
    return state


@contextmanager
def prepared(root, release, manifest, request):
    """Authenticate and validate in a private disposable workspace, before stopping services."""
    root, release = Path(root), Path(release)
    refuse_reparse(root)
    refuse_reparse(release)
    archive = Path(request["archive"])
    refuse_reparse(archive)
    archive = archive.resolve()
    if not archive.is_file() or not 1 <= archive.stat().st_size <= LIMIT + 16414:
        raise UnsafeOperation("Selecione um ficheiro de backup válido com tamanho suportado.")
    required = 3 * archive.stat().st_size + 512 * 1024**2
    if shutil.disk_usage(tempfile.gettempdir()).free < required:
        raise UnsafeOperation(
            "Espaço insuficiente para validar a cópia; instalação existente preservada."
        )
    if root == archive or root in archive.parents:
        raise UnsafeOperation("Selecione a cópia externa, fora da instalação a recuperar.")
    with tempfile.TemporaryDirectory(prefix="gva-recovery-") as temporary:
        temp = Path(temporary)
        refuse_reparse(temp)
        protect(temp)
        # Stable private copy closes file-selection/replacement races; it remains encrypted.
        frozen = temp / "input.gvabackup"
        shutil.copyfile(archive, frozen)
        plain = temp / "archive.tar"
        metadata = decrypt_backup(frozen, plain, request, manifest["channel"])
        data = temp / "data"
        saved = extract_verified(plain, data)
        state = validate_snapshot(data, metadata, saved, manifest)
        recovery_envelope = header(frozen).get("recovery")
        if recovery_envelope:
            # Header was authenticated by decrypt_backup; preserve unattended portability.
            write_json(data / "secrets/recovery-envelope.json", recovery_envelope)
        if (root / "maintenance.json").exists():
            raise UnsafeOperation(
                "Há manutenção interrompida. Preserve os dados e peça diagnóstico antes de iniciar outra recuperação."
            )
        current = (
            digest(root / "installation.json") if (root / "installation.json").exists() else None
        )
        binding = {
            "backup": digest(frozen),
            "destination": current,
            "package": digest(release.parent / "package.json"),
        }
        token = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        summary = {
            "token": token,
            "sha256": binding["backup"],
            "instance": state["instance"],
            "version": state["version"],
            "target_version": manifest["version"],
            "replaces_existing": current is not None,
            "rows": {
                name: value["rows"]
                for name, value in saved["evidence"].items()
                if name != "__sequences__"
            },
            "network": "disabled-pending-destination-approval",
            "android_local_preferences": "not-in-server-backup",
        }
        yield data, saved, state, summary


def preview(root, release, manifest, request):
    administrator()
    with prepared(root, release, manifest, request) as (_, _, _, summary):
        return summary


def restore(root, release, manifest, request, trust_path):
    administrator()
    root, release = Path(root), Path(release)
    trusted_policy = Path(trust_path).read_bytes()
    # Serialises wizard invocations outside the root that will be renamed.
    control = root.parent / (root.name + "-RecoveryControl")
    refuse_reparse(control)
    control.mkdir(exist_ok=True)
    protect(control)
    with (
        exclusive(control),
        prepared(root, release, manifest, request) as (data, saved, source, summary),
    ):
        if (
            request.get("confirmed") is not True
            or request.get("token") != summary["token"]
            or request.get("source_offline") is not True
            or request.get("confirmed_identity_history") is not True
        ):
            raise UnsafeOperation(
                "Reveja o resumo e confirme a substituição, o isolamento da origem e a conferência do histórico/exportações posteriores ao backup."
            )
        previous = read_state(root) if (root / "installation.json").exists() else None
        if root.exists() and previous is None:
            raise UnsafeOperation(
                "Destino contém dados não reconhecidos; nenhum ficheiro foi adotado."
            )
        registered = [name for name in SERVICES.values() if exists(name)]
        if registered and (previous is None or previous.get("uninstalled")):
            raise UnsafeOperation(
                "Existem serviços não pertencentes a uma instalação ativa reconhecida."
            )
        if previous and previous["channel"] != source["channel"]:
            raise UnsafeOperation("Não é permitida a conversão entre testes e produção.")
        if previous and version(previous["version"]) > version(manifest["version"]):
            raise UnsafeOperation(
                "Instalador anterior à instalação existente; recuperação recusada."
            )
        if (
            shutil.disk_usage(root.parent).free
            < 3 * (data / "database.dump").stat().st_size + 512 * 1024**2
        ):
            raise UnsafeOperation(
                "Espaço insuficiente para preservar a instalação anterior e criar um cluster novo."
            )
        operation = uuid.uuid4().hex
        preserved = root.parent / (root.name + "-Preserved-" + operation)
        failed = root.parent / (root.name + "-Failed-" + operation)
        record = {
            "id": operation,
            "phase": "validated",
            "backup_sha256": summary["sha256"],
            "previous_preserved": preserved.name if previous else None,
        }
        # Only known service configurations are ever changed. A fresh destination
        # is required when another application's services occupy these names.
        old_moved = False
        owns_journal = False
        try:
            if previous:
                with exclusive(root):
                    if (root / "maintenance.json").exists():
                        raise UnsafeOperation("Outra manutenção está em curso.")
                    write_json(root / "maintenance.json", record)
                    owns_journal = True
                    disable_all()
                    stop_all()
                root.rename(preserved)
                old_moved = True
            else:
                root.mkdir(exist_ok=False)
            root.mkdir(exist_ok=True)
            protect(root)

            def mark(phase):
                record["phase"] = phase
                write_json(root / "maintenance.json", record)

            mark("recovery-new-cluster")
            owns_journal = True
            for name in ("secrets", "signing", "tls", "runtime/web/documents"):
                if (data / name).is_dir():
                    shutil.copytree(data / name, root / name, dirs_exist_ok=True)
            for name in ("recovery-public.pem", "backup-policy.json", "publisher.json"):
                if (data / name).is_file():
                    shutil.copyfile(data / name, root / name)
            # A recovered archive cannot appoint its own executable signing authority.
            (root / "package-policy.json").write_bytes(trusted_policy)
            config = json.loads((root / "backup-policy.json").read_text())
            write_json(root / "backup-policy.json", {**config, "copy_to": None})
            if (root / "publisher.json").exists():
                config = json.loads((root / "publisher.json").read_text())
                write_json(root / "publisher.json", {**config, "enabled": False})
            ports = {
                name: previous[name] if previous else source[name]
                for name in ("db_port", "http_port")
            }
            for port in ports.values():
                free_port(port)
            state = {
                **source,
                **ports,
                "release": str(release),
                "version": manifest["version"],
                "package_sha256": digest(release.parent / "package.json"),
                "uninstalled": False,
            }
            write_json(root / "installation.json", state)
            configure(root, release, create=not registered)
            # Machine-bound vaults must never survive transfer to another host.
            (root / "secrets/backup-vault.dpapi").unlink(missing_ok=True)
            prepare_acl(root)
            create_cluster(root)
            mark("recovery-database")
            with (data / "database.dump").open("rb") as dump:
                pg_tool(root, "pg_restore", state["database"], stdin=dump)
            with connection(root) as conn:
                if not matching_evidence(evidence(conn), saved["evidence"]):
                    raise UnsafeOperation(
                        "O restauro não corresponde ao backup. Arranque recusado."
                    )
            mark("recovery-schema-and-identity")
            # No migration here: reject newer/older schemas before any web process starts.
            manage(
                root,
                "shell",
                "-c",
                "from native_windows.schema import assert_current; assert_current()",
            )
            from .maintenance import validate_material

            validate_material(root)
            grants(root)
            manage(
                root,
                "shell",
                "-c",
                "from inventory.models import AuditEvent; AuditEvent.objects.create(action='native.recovery.verified', details="
                + repr(
                    {
                        "backup_sha256": summary["sha256"],
                        "authorization": "Windows administrator",
                        "previous_preserved": preserved.name if previous else None,
                    }
                )
                + ")",
            )
            manage(root, "check", "--fail-level", "WARNING")
            mark("recovery-activation")
            stop_all()
            (root / "activation-permit").write_text(str(release))
            activate(root)
            health_http(root)
            record.update(
                phase="completed", restored_instance=source["instance"], network_enabled=False
            )
            write_json(root / ("recovery-" + operation + ".json"), record)
            (root / "maintenance.json").unlink()
            return {
                "status": "verified-and-running",
                "previous_preserved": preserved.name if previous else None,
            }
        except Exception as error:
            if not owns_journal:
                raise
            # Preserve both sides on ALL failures. Never run old code on restored data.
            try:
                disable_all()
                stop_all()
                record.update(failed=True, category=type(error).__name__)
                if old_moved:
                    if root.exists():
                        write_json(root / "maintenance.json", record)
                        root.rename(failed)
                    preserved.rename(root)
                    if previous.get("uninstalled"):
                        from .windows import uninstall

                        uninstall()
                    else:
                        configure(
                            root,
                            previous["release"],
                            create=not any(exists(name) for name in SERVICES.values()),
                        )
                    if not previous.get("uninstalled"):
                        # Original cluster and keys are untouched. Verify schema before resuming.
                        native(["sc.exe", "config", SERVICES["postgres"], "start=", "demand"])
                        native(["sc.exe", "start", SERVICES["postgres"]])
                        wait_database(root)
                        manage(
                            root,
                            "shell",
                            "-c",
                            "from native_windows.schema import assert_current; assert_current()",
                        )
                        (root / "activation-permit").write_text(previous["release"])
                        activate(root)
                        health_http(root)
                    write_json(root / ("recovery-failed-" + operation + ".json"), record)
                    (root / "maintenance.json").unlink(missing_ok=True)
                elif root.exists():
                    write_json(root / "maintenance.json", record)
            except Exception:
                # If rollback cannot be proven, retain the maintenance gate.
                disable_all()
                stop_all()
                raise UnsafeOperation(
                    "Recuperação interrompida. Os dados anteriores foram preservados; é necessária assistência antes de iniciar serviços."
                ) from error
            raise UnsafeOperation(
                "Recuperação recusada na etapa "
                + record["phase"]
                + ". Dados anteriores preservados. Categoria: "
                + type(error).__name__
            ) from error
        finally:
            if owns_journal and root.exists():
                (root / "activation-permit").unlink(missing_ok=True)
