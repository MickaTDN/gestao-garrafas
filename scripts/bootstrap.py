"""Create private local development settings without overwriting existing secrets."""

import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent.parent
(root / "private").mkdir(mode=0o700, exist_ok=True)
target = root / ".env"
if not target.exists():
    content = (root / ".env.example").read_text()
    content = content.replace("DJANGO_SECRET_KEY=\n", f"DJANGO_SECRET_KEY={secrets.token_urlsafe(64)}\n")
    content = content.replace("DB_PASSWORD=\n", f"DB_PASSWORD={secrets.token_urlsafe(32)}\n")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(content)
    print("Configuração local criada em .env (ignorada pelo Git).")
else:
    print("Configuração .env existente preservada.")
