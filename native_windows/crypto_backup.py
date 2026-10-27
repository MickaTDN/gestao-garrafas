"""Streaming authenticated backup encryption with a separate RSA recovery key.

No recovery private key is stored by the automatic backup service. Decryption
publishes nothing until authentication succeeds. Metadata is authenticated too.
"""

import base64
import json
import os
import struct
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .package import UnsafeOperation, digest

MAGIC = b"GVABACKUP1\n"
LIMIT = 100 * 1024**3


def create_recovery_key(password):
    if len(password) < 16:
        raise UnsafeOperation("A frase de recuperação deve ter pelo menos 16 caracteres.")
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    return (
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(password.encode())),
        key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo),
    )


def encrypt(source, destination, public_pem, metadata):
    key = serialization.load_pem_public_key(public_pem)
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072:
        raise UnsafeOperation("Chave pública de recuperação inválida.")
    content_key = os.urandom(32)
    nonce = os.urandom(12)
    header = json.dumps({"schema": 1, "metadata": metadata, "sha256": digest(source), "size": Path(source).stat().st_size, "nonce": base64.b64encode(nonce).decode(), "key": base64.b64encode(key.encrypt(content_key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=MAGIC))).decode()}, sort_keys=True).encode()
    cipher = Cipher(algorithms.AES(content_key), modes.GCM(nonce)).encryptor()
    cipher.authenticate_additional_data(MAGIC + header)
    destination = Path(destination)
    partial = destination.with_suffix(destination.suffix + ".partial")
    try:
        with Path(source).open("rb") as inp, partial.open("xb") as out:
            out.write(MAGIC + struct.pack(">I", len(header)) + header)
            for block in iter(lambda: inp.read(1024 * 1024), b""):
                out.write(cipher.update(block))
            out.write(cipher.finalize())
            out.write(cipher.tag)
            out.flush()
            os.fsync(out.fileno())
        if destination.exists():
            raise UnsafeOperation("O backup de destino já existe.")
        os.replace(partial, destination)
    finally:
        partial.unlink(missing_ok=True)


def decrypt(source, destination, private_pem, password):
    destination = Path(destination)
    if destination.exists():
        raise UnsafeOperation("O destino de recuperação já existe.")
    temporary = destination.with_suffix(destination.suffix + ".partial")
    try:
        private = serialization.load_pem_private_key(private_pem, password=password.encode())
        with Path(source).open("rb") as inp:
            if inp.read(len(MAGIC)) != MAGIC:
                raise ValueError
            length = struct.unpack(">I", inp.read(4))[0]
            if not 1 <= length <= 16384:
                raise ValueError
            header = inp.read(length)
            data = json.loads(header)
            if data["schema"] != 1 or not 0 <= data["size"] <= LIMIT:
                raise ValueError
            key = private.decrypt(base64.b64decode(data["key"], validate=True), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=MAGIC))
            end = inp.seek(0, 2)
            if end != len(MAGIC) + 4 + length + data["size"] + 16:
                raise ValueError
            inp.seek(end - 16)
            tag = inp.read(16)
            inp.seek(len(MAGIC) + 4 + length)
            cipher = Cipher(algorithms.AES(key), modes.GCM(base64.b64decode(data["nonce"], validate=True), tag)).decryptor()
            cipher.authenticate_additional_data(MAGIC + header)
            remaining = data["size"]
            with temporary.open("xb") as out:
                while remaining:
                    block = inp.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ValueError
                    remaining -= len(block)
                    out.write(cipher.update(block))
                out.write(cipher.finalize())
                out.flush()
                os.fsync(out.fileno())
            if digest(temporary) != data["sha256"]:
                raise ValueError
            os.replace(temporary, destination)
            return data["metadata"]
    except Exception as error:
        raise UnsafeOperation("Backup inválido, alterado ou chave/frase de recuperação incorreta.") from error
    finally:
        temporary.unlink(missing_ok=True)
