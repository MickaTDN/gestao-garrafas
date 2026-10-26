"""New private transfer files only, outside code and public assets; never overwrite."""

import json
import os
import stat
from pathlib import Path

from django.conf import settings


def output_path(value):
    configured = Path(value).expanduser()
    path = configured.resolve()
    if (
        not configured.is_absolute()
        or path.is_relative_to(Path(settings.BASE_DIR).resolve())
        or configured.is_symlink()
    ):
        raise ValueError("Use uma pasta privada absoluta fora do código e do publicador.")
    if path.exists():
        raise ValueError("Não se substituem ficheiros existentes.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt" and stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
        raise ValueError(
            "A pasta deve ser privada (0700). No Windows, a informática deve validar as ACL NTFS do suporte."
        )
    return path


def write_json(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False)
