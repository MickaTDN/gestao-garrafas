"""Machine DPAPI plus administrator-only DACL; never a portable recovery dependency."""

import ctypes
import json
import os
from pathlib import Path

from .package import UnsafeOperation
from .windows import administrator, protect

NAME = "backup-vault.dpapi"


def crypt(data, *, decrypt=False):
    if os.name != "nt":
        raise UnsafeOperation("O cofre requer proteção DPAPI do Windows.")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    api = ctypes.WinDLL("crypt32", use_last_error=True)
    function = api.CryptUnprotectData if decrypt else api.CryptProtectData
    function.restype = wintypes.BOOL
    function.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(Blob),
    ]
    # LocalMachine allows a different explicitly elevated Windows administrator;
    # the file DACL, never DPAPI alone, restricts access. No UI or process secrets.
    if not function(
        ctypes.byref(source), None, None, None, None, 1 if decrypt else 5, ctypes.byref(output)
    ):
        raise UnsafeOperation(
            "Cofre indisponível. Use a frase-passe original; não altere backups anteriores."
        )
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(output.data, output.length)
    finally:
        kernel.LocalFree(output.data)


def save(root, value):
    administrator()
    path = Path(root) / "secrets" / NAME
    encrypted = crypt(json.dumps({"schema": 1, **value}).encode())
    # Only encrypted bytes reach disk; secure the file before opening it.
    if not path.exists():
        path.touch(exist_ok=False)
    protect(path)
    with path.open("wb") as stream:
        stream.write(encrypted)
        stream.flush()
        os.fsync(stream.fileno())


def load(root):
    administrator()
    try:
        data = (Path(root) / "secrets" / NAME).read_bytes()
        if len(data) > 32768:
            raise ValueError
        value = json.loads(crypt(data, decrypt=True))
        if value["schema"] != 1:
            raise ValueError
        return value
    except Exception as error:
        raise UnsafeOperation(
            "Cofre indisponível. Reconfigure com a frase-passe original ou recupere uma cópia portátil."
        ) from error
