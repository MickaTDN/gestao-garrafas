"""Reviewed Microsoft CRT app-local deployment, never a global installation."""

import json
import os
import re
import shutil
import struct
import subprocess
from pathlib import Path

from native_windows.package import UnsafeOperation

REQUIRED = {"vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"}
ALLOWED = re.compile(r"(?:vcruntime140(?:_1)?|msvcp140(?:_[a-z0-9_]+)?|concrt140|vccorlib140|vcamp140)\.dll")


def verify_microsoft(path, signers):
    script = """$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$s=Get-AuthenticodeSignature -LiteralPath $env:GVA_CRT_CHECK
if($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'Untrusted Microsoft CRT' }
$h=[Security.Cryptography.SHA256]::Create()
$f=([BitConverter]::ToString($h.ComputeHash($s.SignerCertificate.RawData))).Replace('-','').ToLowerInvariant()
@{signer=$f}|ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        # A pwsh build must not load PowerShell 7 modules into Windows PS 5.1.
        env={k: v for k, v in os.environ.items() if k.lower() != "psmodulepath"} | {"GVA_CRT_CHECK": str(path)},
        capture_output=True, timeout=60,
    )
    if result.returncode or json.loads(result.stdout.decode("utf-8-sig"))["signer"] not in signers:
        raise UnsafeOperation("Runtime Microsoft sem assinatura aprovada: " + path.name)


def deploy(payload, source, metadata, *, verifier=verify_microsoft):
    source = Path(source)
    files = list(source.iterdir())
    names = {p.name.lower() for p in files}
    if not REQUIRED <= names or len(names) != len(files):
        raise UnsafeOperation("O arquivo CRT não contém o conjunto x64 completo e inequívoco.")
    signers = metadata.get("signers_sha256")
    if not isinstance(signers, list) or not signers or any(
        not isinstance(s, str) or not re.fullmatch(r"[a-f0-9]{64}", s) for s in signers
    ):
        raise UnsafeOperation("Faltam fingerprints aprovados dos fornecedores CRT.")
    for path in files:
        if path.is_symlink() or not path.is_file() or not ALLOWED.fullmatch(path.name.lower()):
            raise UnsafeOperation("Ficheiro não autorizado no arquivo CRT.")
        data = path.read_bytes()
        try:
            offset = struct.unpack_from("<I", data, 0x3C)[0]
            valid = data[:2] == b"MZ" and data[offset:offset + 4] == b"PE\0\0" and struct.unpack_from("<H", data, offset + 4)[0] == 0x8664
        except struct.error:
            valid = False
        if not valid:
            raise UnsafeOperation("O runtime deve ser PE x64: " + path.name)
        verifier(path, signers)
    # Every binary needs its own app-local DLL search directory. Never replace
    # System32, modify PATH globally, copy debug runtimes or change service ACLs.
    for destination in (Path(payload) / "postgres/bin", Path(payload) / "nginx"):
        for path in files:
            target = destination / path.name.lower()
            # The destination is a NEW build payload, never an installation.
            # The reviewed CRT input deliberately supersedes same-name vendor DLLs.
            if target.is_symlink():
                raise UnsafeOperation("Destino CRT inválido.")
            shutil.copyfile(path, target)
