"""Offline inputs, exact wheel lock, immutable version directories and signed inventory.

Release inputs must be fetched/reviewed by IT, then supplied with independent
SHA-256 values. CI's synthetic package is deliberately a separate installation.
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

from native_windows.package import (  # noqa: E402
    CONTEXT,
    UnsafeOperation,
    copy_reviewed_source,
    digest,
    regular_tree,
    reject_private_material,
    version,
)


def unpack(archive, target):
    target.mkdir()
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive) as handle:
            handle.extractall(target, filter="data")
    else:
        with zipfile.ZipFile(archive) as handle:
            for name in handle.namelist():
                parts = name.replace("\\", "/").split("/")
                if (
                    any(part == ".." for part in parts)
                    or name.startswith(("/", "\\"))
                    or ":" in name
                ):
                    raise UnsafeOperation("Arquivo do fornecedor contém caminhos inválidos.")
            handle.extractall(target)


def build(args):
    version(args.version)
    # A payload must correspond to the reviewed commit, not ignored private files
    # or uncommitted working-copy changes on a developer machine.
    for command in (["git", "diff", "--quiet"], ["git", "diff", "--cached", "--quiet"]):
        if subprocess.run(command, cwd=ROOT).returncode:
            raise UnsafeOperation(
                "Compile apenas um commit limpo revisto; não se empacotam alterações locais."
            )
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    key_path = Path(args.key).resolve()
    if key_path.is_relative_to(ROOT):
        raise UnsafeOperation("A chave privada de pacotes deve ficar fora do repositório.")
    version(args.minimum_version)
    output = Path(args.output).resolve()
    if output.exists() or output.is_relative_to(ROOT):
        raise UnsafeOperation("Escolha uma pasta de saída NOVA fora do código.")
    policy = json.loads(Path(args.policy).read_text())
    if policy["channel"] not in ("release", "synthetic"):
        raise UnsafeOperation("Canal inválido.")
    key = serialization.load_pem_private_key(
        Path(args.key).read_bytes(),
        password=os.environ.get("GVA_PACKAGE_KEY_PASSWORD", "").encode() or None,
    )
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise UnsafeOperation("Assinatura do pacote exige ECDSA P-256.")
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    if policy["public_key"] != public:
        raise UnsafeOperation("A chave de assinatura não corresponde à política revista.")
    if policy["channel"] == "release" and (
        not policy.get("authenticode_sha256") or len(policy["authenticode_sha256"]) != 64
    ):
        raise UnsafeOperation("Distribuição exige certificado Authenticode aprovado.")
    sources = json.loads(Path(args.inputs).read_text(encoding="utf-8-sig"))
    output.mkdir(parents=True)
    payload = output / "payload"
    payload.mkdir()
    provenance = []
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        for component, executable in (
            ("python", "python.exe"),
            ("postgres", "bin/postgres.exe"),
            ("nginx", "nginx.exe"),
        ):
            item = sources[component]
            archive = Path(item["archive"])
            if digest(archive) != item["sha256"] or len(item["sha256"]) != 64:
                raise UnsafeOperation("SHA-256 do fornecedor incorreto: " + component)
            dest = temp / component
            unpack(archive, dest)
            candidates = [
                path
                for path in dest.rglob(Path(executable).name)
                if path.as_posix().endswith("/" + executable)
            ]
            if candidates:
                depth = min(len(path.parts) for path in candidates)
                candidates = [path for path in candidates if len(path.parts) == depth]
            if len(candidates) != 1:
                raise UnsafeOperation("Estrutura do fornecedor ambígua: " + component)
            source = candidates[0]
            for _ in Path(executable).parts:
                source = source.parent
            shutil.copytree(source, payload / component)
            provenance.append(
                {
                    "component": component,
                    "version": item["version"],
                    "sha256": item["sha256"],
                    "source": item["source"],
                }
            )
    if args.synthetic_migration_probe and policy["channel"] != "synthetic":
        raise UnsafeOperation("A migração de ensaio nunca pode entrar num pacote de distribuição.")
    python_version = json.loads(
        subprocess.check_output(
            [
                str(payload / "python/python.exe"),
                "-s",
                "-c",
                "import json,sys;print(json.dumps(list(sys.version_info[:2])))",
            ],
            text=True,
        )
    )
    pg_version = subprocess.check_output(
        [str(payload / "postgres/bin/postgres.exe"), "--version"], text=True
    )
    if python_version != [3, 12] or not pg_version.startswith("postgres (PostgreSQL) 17."):
        raise UnsafeOperation("Os fornecedores devem conter Python3.12 e PostgreSQL17 reais.")
    app = payload / "app"
    app.mkdir()
    copy_reviewed_source(
        ROOT,
        app,
        tracked,
        prefixes=(
            "accounts",
            "inventory",
            "imports",
            "web",
            "consultation",
            "config",
            "templates",
            "static",
            "vertente",
            "native_windows",
        ),
        explicit=(
            "manage.py",
            "pyproject.toml",
            "uv.lock",
            "deploy/app-role.sql",
            "deploy/vertente/nginx.conf.template",
            "docs/windows-native.md",
            "docs/windows-native.html",
        ),
    )
    if args.synthetic_migration_probe:
        (app / "consultation/migrations/0003_native_synthetic_probe.py").write_text(
            "from django.db import migrations\n"
            "class Migration(migrations.Migration):\n"
            "    dependencies = [('consultation', '0002_authorizeddevice')]\n"
            "    operations = [migrations.RunSQL(\"CREATE TABLE gva_native_ci_probe(id integer PRIMARY KEY, label text NOT NULL); INSERT INTO gva_native_ci_probe VALUES(1, 'synthetic-forward-migration')\")]\n"
        )

    def write(path, value):
        Path(path).write_text(json.dumps(value, sort_keys=True, indent=2), encoding="utf-8")

    write(
        app / "native-provenance.json",
        {
            "vendors": provenance,
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "version": args.version,
            "channel": policy["channel"],
        },
    )
    requirements = output / "requirements.txt"
    with requirements.open("w") as handle:
        subprocess.run(
            ["uv", "export", "--frozen", "--no-dev", "--format", "requirements-txt"],
            cwd=ROOT,
            stdout=handle,
            check=True,
        )
    python = str(payload / "python/python.exe")
    subprocess.run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "--only-binary=:all:",
            "-r",
            str(requirements),
        ],
        check=True,
    )
    env = {
        **os.environ,
        "DJANGO_SECRET_KEY": "synthetic-static-build-only-not-a-deployment-secret",
        "APP_ENV": "production",
        "DJANGO_DEBUG": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    subprocess.run(
        [python, "-B", str(app / "manage.py"), "collectstatic", "--noinput"], env=env, check=True
    )
    # Caches do not belong to the executable inventory; installed code is read-only.
    for path in payload.rglob("__pycache__"):
        shutil.rmtree(path)
    host_source = output / "host-source"
    copy_reviewed_source(
        ROOT,
        host_source,
        tracked,
        prefixes=("deploy/native/Host",),
        explicit=("static/branding/copo-com-vida.ico",),
    )
    host_project = host_source / "deploy/native/Host/Host.csproj"
    host = payload / "host"
    result = subprocess.run(
        [
            "dotnet",
            "publish",
            str(host_project),
            "-c",
            "Release",
            "-p:Version=" + args.version,
            "-o",
            str(host),
            "-p:NativeTrust=" + str(Path(args.policy).resolve()),
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode:
        print(
            "::error::Native host compile: "
            + (result.stdout + result.stderr)[-10000:].replace("\n", " "),
            file=sys.stderr,
        )
        raise UnsafeOperation("Falha na compilação do anfitrião Windows.")
    # Windows service identities must not share .NET's self-extraction cache.
    # Publish an unpacked private runtime in read-only ProgramFiles for services;
    # the standalone launcher/preflight remains a single executable.
    service_host = payload / "service"
    result = subprocess.run(
        [
            "dotnet",
            "publish",
            str(host_project),
            "-c",
            "Release",
            "-p:Version=" + args.version,
            "-o",
            str(service_host),
            "-p:NativeTrust=" + str(Path(args.policy).resolve()),
            "-p:PublishSingleFile=false",
            "-p:IncludeNativeLibrariesForSelfExtract=false",
        ],
        text=True,
        capture_output=True,
    )
    if result.returncode:
        print(
            "::error::Service host compile: "
            + (result.stdout + result.stderr)[-10000:].replace("\n", " "),
            file=sys.stderr,
        )
        raise UnsafeOperation("Falha na compilação do anfitrião de serviços Windows.")
    if policy["channel"] == "release":
        if not args.host_sign_command:
            raise UnsafeOperation(
                "A distribuição exige assinatura Authenticode do anfitrião por uma ferramenta empresarial autorizada."
            )
        command = json.loads(args.host_sign_command)
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(item, str) for item in command)
        ):
            raise UnsafeOperation(
                "O comando de assinatura deve ser uma lista JSON de argumentos, sem shell nem segredos."
            )
        for executable in (host / "GVA.Native.exe", service_host / "GVA.Native.exe"):
            subprocess.run([*command, str(executable)], check=True)
            subprocess.run(
                [str(host / "GVA.Native.exe"), "--verify-signer", str(executable)], check=True
            )
    reject_private_material(payload)
    manifest = {
        "schema": 1,
        "version": args.version,
        "minimum_version": args.minimum_version,
        "postgres_major": 17,
        "channel": policy["channel"],
        "files": regular_tree(payload),
    }
    write(output / "package.json", manifest)
    signature = key.sign(
        CONTEXT + (output / "package.json").read_bytes(), ec.ECDSA(hashes.SHA256())
    )
    (output / "package.sig").write_bytes(base64.b64encode(signature))
    write(output / "release-trust.json", policy)
    requirements.unlink()
    shutil.rmtree(host_source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-migration-probe", action="store_true")
    parser.add_argument(
        "--host-sign-command", help="JSON argv of approved enterprise signer; no passwords on argv"
    )
    for arg in ("version", "minimum-version", "policy", "key", "inputs", "output"):
        parser.add_argument("--" + arg, required=True)
    try:
        build(parser.parse_args())
    except Exception as error:
        print(
            "::error::Native package build: "
            + type(error).__name__
            + ": "
            + str(error).replace("\n", " "),
            file=sys.stderr,
        )
        raise
