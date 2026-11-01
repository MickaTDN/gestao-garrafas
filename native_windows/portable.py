"""Portable recovery credentials; legacy RSA backups and demo kits stay readable.

Only a password-encrypted RSA key is retained for unattended backups. Neither the
password nor the clear private key is written to disk. Fixed KDF costs prevent
untrusted headers from requesting arbitrary memory/CPU.
"""

import base64
import json
import os
import secrets
import struct
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .crypto_backup import MAGIC, decrypt
from .package import UnsafeOperation

CONTEXT = b"gva-portable-recovery-v1"


def b64(value):
    return base64.b64encode(value).decode("ascii")


def un64(value):
    return base64.b64decode(value, validate=True)


def derive(password, salt):
    if not isinstance(password, str) or not 16 <= len(password) <= 1024 or len(salt) != 16:
        raise ValueError("credential")
    return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(password.encode("utf-8"))


def envelope(private_pem, old_password, password, public_pem):
    """Bind portable credentials to the existing identity; never rotate legacy keys."""
    try:
        key = serialization.load_pem_private_key(private_pem, password=old_password.encode())
        public = serialization.load_pem_public_key(public_pem)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 3072:
            raise ValueError
        if key.public_key().public_numbers() != public.public_numbers():
            raise ValueError
        salt, nonce = os.urandom(16), os.urandom(12)
        plain = key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        cipher = AESGCM(derive(password, salt)).encrypt(nonce, plain, CONTEXT)
        return {
            "format": "gva-portable-recovery",
            "version": 1,
            "salt": b64(salt),
            "nonce": b64(nonce),
            "ciphertext": b64(cipher),
        }
    except Exception as error:
        raise UnsafeOperation(
            "Credencial inválida ou chave não correspondente a esta instalação. Use uma frase de pelo menos 16 caracteres."
        ) from error


def unlock(value, password):
    try:
        if value["format"] != "gva-portable-recovery" or value["version"] != 1:
            raise ValueError
        cipher, nonce = un64(value["ciphertext"]), un64(value["nonce"])
        if len(cipher) > 8192 or len(nonce) != 12:
            raise ValueError
        plain = AESGCM(derive(password, un64(value["salt"]))).decrypt(nonce, cipher, CONTEXT)
        key = serialization.load_der_private_key(plain, password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 3072:
            raise ValueError
        # Existing decrypt API requires encrypted PKCS8. This ephemeral password
        # and PEM only exist in memory; no temporary .pem is ever created.
        temporary_password = secrets.token_urlsafe(48)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(temporary_password.encode()),
        )
        return pem, temporary_password
    except Exception as error:
        raise UnsafeOperation(
            "Credencial de recuperação incorreta ou ficheiro alterado."
        ) from error


def header(path):
    try:
        with Path(path).open("rb") as stream:
            if stream.read(len(MAGIC)) != MAGIC:
                raise ValueError
            raw = stream.read(4)
            if len(raw) != 4 or not 1 <= (length := struct.unpack(">I", raw)[0]) <= 16384:
                raise ValueError
            value = json.loads(stream.read(length))
            if not isinstance(value, dict) or value.get("schema") != 1:
                raise ValueError
            return value
    except (OSError, ValueError, TypeError) as error:
        raise UnsafeOperation(
            "Cabeçalho ou formato de backup inválido. Instalação preservada."
        ) from error


def demo_material(path, code, channel):
    """Interop with the original .NET AES-GCM .gvademo v1 format."""
    try:
        if channel != "synthetic" or Path(path).stat().st_size > 131072:
            raise ValueError
        value = json.loads(Path(path).read_bytes())
        if value["format"] != "gva-synthetic-kit" or value["version"] != 1:
            raise ValueError
        key = un64(code)
        if len(key) != 32:
            raise ValueError
        plain = AESGCM(key).decrypt(
            un64(value["nonce"]),
            un64(value["ciphertext"]) + un64(value["tag"]),
            b"gva-synthetic-kit-v1",
        )
        data = json.loads(plain)
        pem, password = un64(data["PrivateKey"]), data["RecoveryPassword"]
        serialization.load_pem_private_key(pem, password=password.encode())
        return pem, password
    except Exception as error:
        raise UnsafeOperation(
            "Kit de demonstração inválido ou código incorreto. O kit original foi preservado."
        ) from error


def material(request, channel, archive=None):
    if request.get("recovery_private_b64"):
        return un64(request["recovery_private_b64"]), request["recovery_password"]
    if request.get("demo_kit"):
        return demo_material(request["demo_kit"], request.get("credential", ""), channel)
    if request.get("recovery_key"):
        return Path(request["recovery_key"]).read_bytes(), request.get(
            "recovery_password", request.get("credential", "")
        )
    if archive:
        value = header(archive).get("recovery")
        if value:
            return unlock(value, request.get("credential", ""))
    raise UnsafeOperation(
        "Este backup antigo exige o kit .gvademo e o respetivo código, ou a chave original e a sua frase. Não é possível substituir uma chave perdida."
    )


def decrypt_backup(archive, destination, request, channel):
    pem, password = material(request, channel, archive)
    return decrypt(archive, destination, pem, password)
