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

from native_windows.package import CONTEXT, UnsafeOperation, digest, regular_tree, version  # noqa: E402


def unpack(archive, target):
    target.mkdir()
    if archive.name.endswith(".tar.gz"):
        with tarfile.open(archive) as handle:
            handle.extractall(target, filter="data")
    else:
        with zipfile.ZipFile(archive) as handle:
            for name in handle.namelist():
                parts = name.replace("\\", "/").split("/")
                if any(part == ".." for part in parts) or name.startswith(("/", "\\")) or ":" in name:
                    raise UnsafeOperation("Arquivo do fornecedor contém caminhos inválidos.")
            handle.extractall(target)


def build(args):
    version(args.version)
    version(args.minimum_version)
    output = Path(args.output).resolve()
    if output.exists() or output.is_relative_to(ROOT):
        raise UnsafeOperation("Escolha uma pasta de saída NOVA fora do código.")
    policy = json.loads(Path(args.policy).read_text())
    if policy["channel"] not in ("release", "synthetic"):
        raise UnsafeOperation("Canal inválido.")
    key = serialization.load_pem_private_key(Path(args.key).read_bytes(), password=os.environ.get("GVA_PACKAGE_KEY_PASSWORD", "").encode() or None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise UnsafeOperation("Assinatura do pacote exige ECDSA P-256.")
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    if policy["public_key"] != public:
        raise UnsafeOperation("A chave de assinatura não corresponde à política revista.")
    if policy["channel"] == "release" and (not policy.get("authenticode_sha256") or len(policy["authenticode_sha256"]) != 64):
        raise UnsafeOperation("Distribuição exige certificado Authenticode aprovado.")
    sources = json.loads(Path(args.inputs).read_text(encoding="utf-8-sig"))
    output.mkdir(parents=True)
    payload = output / "payload"
    payload.mkdir()
    provenance = []
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        for component, executable in (("python", "python.exe"), ("postgres", "bin/postgres.exe"), ("nginx", "nginx.exe")):
            item = sources[component]
            archive = Path(item["archive"])
            if digest(archive) != item["sha256"] or len(item["sha256"]) != 64:
                raise UnsafeOperation("SHA-256 do fornecedor incorreto: " + component)
            dest = temp / component
            unpack(archive, dest)
            candidates = [path for path in dest.rglob(Path(executable).name) if path.as_posix().endswith("/" + executable)]
            if len(candidates) != 1:
                raise UnsafeOperation("Estrutura do fornecedor ambígua: " + component)
            source = candidates[0]
            for _ in Path(executable).parts:
                source = source.parent
            shutil.copytree(source, payload / component)
            provenance.append({"component": component, "version": item["version"], "sha256": item["sha256"], "source": item["source"]})
    app = payload / "app"
    app.mkdir()
    for folder in ("accounts", "inventory", "imports", "web", "consultation", "config", "templates", "static", "vertente", "native_windows"):
        shutil.copytree(ROOT / folder, app / folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"))
    for file in ("manage.py", "pyproject.toml", "uv.lock"):
        shutil.copy2(ROOT / file, app / file)
    (app / "deploy/vertente").mkdir(parents=True)
    shutil.copy2(ROOT / "deploy/app-role.sql", app / "deploy/app-role.sql")
    shutil.copy2(ROOT / "deploy/vertente/nginx.conf.template", app / "deploy/vertente/nginx.conf.template")
    def write(path, value):
        Path(path).write_text(json.dumps(value, sort_keys=True, indent=2), encoding="utf-8")
    write(app / "native-provenance.json", provenance)
    requirements = output / "requirements.txt"
    with requirements.open("w") as handle:
        subprocess.run(["uv", "export", "--frozen", "--no-dev", "--format", "requirements-txt"], cwd=ROOT, stdout=handle, check=True)
    python = str(payload / "python/python.exe")
    subprocess.run([python, "-m", "pip", "install", "--require-hashes", "--only-binary=:all:", "-r", str(requirements)], check=True)
    env = {**os.environ, "DJANGO_SECRET_KEY": "synthetic-static-build-only-not-a-deployment-secret", "APP_ENV": "production", "DJANGO_DEBUG": "0", "PYTHONDONTWRITEBYTECODE": "1"}
    subprocess.run([python, "-B", str(app / "manage.py"), "collectstatic", "--noinput"], env=env, check=True)
    # Caches do not belong to the executable inventory; installed code is read-only.
    for path in payload.rglob("__pycache__"):
        shutil.rmtree(path)
    host = payload / "host"
    subprocess.run(["dotnet", "publish", str(ROOT / "deploy/native/Host/Host.csproj"), "-c", "Release", "-o", str(host), "-p:NativeTrust=" + str(Path(args.policy).resolve())], check=True)
    manifest = {"schema": 1, "version": args.version, "minimum_version": args.minimum_version, "postgres_major": 17, "channel": policy["channel"], "files": regular_tree(payload)}
    write(output / "package.json", manifest)
    signature = key.sign(CONTEXT + (output / "package.json").read_bytes(), ec.ECDSA(hashes.SHA256()))
    (output / "package.sig").write_bytes(base64.b64encode(signature))
    write(output / "release-trust.json", policy)
    requirements.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for arg in ("version", "minimum-version", "policy", "key", "inputs", "output"):
        parser.add_argument("--" + arg, required=True)
    build(parser.parse_args())
