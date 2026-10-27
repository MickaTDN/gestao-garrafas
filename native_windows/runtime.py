"""Low-privilege service processes. All listeners have explicit addresses."""

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from .package import UnsafeOperation


def read_state(root):
    return json.loads((Path(root) / "installation.json").read_text(encoding="utf-8"))


def environment(root, *, owner=False):
    state = read_state(root)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DJANGO_", "DB_", "PG", "GVA_", "GG_"))
    }
    env.update(
        APP_ENV="windows-native",
        DJANGO_SETTINGS_MODULE="config.windows_native",
        GVA_DATA_ROOT=str(root),
        GVA_MAINTENANCE="1" if owner else "0",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONNOUSERSITE="1",
        PYTHONPATH=str(Path(state["release"]) / "app"),
    )
    env["PATH"] = (
        str(Path(state["release"]) / "postgres" / "bin") + os.pathsep + os.environ.get("PATH", "")
    )
    return env


def manage(root, *arguments):
    state = read_state(root)
    release = Path(state["release"])
    subprocess.run(
        [str(release / "python/python.exe"), "-B", str(release / "app/manage.py"), *arguments],
        env=environment(root, owner=True),
        cwd=release / "app",
        check=True,
        timeout=600,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def service(root, kind, stop_file):
    root = Path(root)
    state = read_state(root)
    release = Path(state["release"])
    permit = root / "activation-permit"
    permitted = permit.is_file() and permit.read_text() == state["release"]
    if kind != "postgres" and (root / "maintenance.json").exists() and not permitted:
        raise UnsafeOperation("Arranque bloqueado por manutenção incompleta.")
    if kind == "postgres":
        # PostgreSQL owns WAL and crash recovery. Never use fsync=off or immediate shutdown.
        pg = release / "postgres/bin/pg_ctl.exe"
        subprocess.run(
            [
                str(pg),
                "-D",
                str(root / "cluster"),
                "-l",
                str(root / "runtime/postgres/server.log"),
                "-w",
                "start",
            ],
            check=True,
            timeout=90,
        )
        try:
            while not Path(stop_file).exists():
                probe = subprocess.run(
                    [str(pg), "-D", str(root / "cluster"), "status"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if probe.returncode:
                    raise UnsafeOperation("O PostgreSQL parou; preserve o diretório de dados.")
                time.sleep(1)
        finally:
            subprocess.run(
                [str(pg), "-D", str(root / "cluster"), "-m", "fast", "-w", "-t", "60", "stop"],
                check=True,
                timeout=70,
            )
    elif kind == "web":
        os.environ.update(environment(root))
        import django
        from waitress import create_server

        django.setup()
        from config.wsgi import application

        server = create_server(
            application,
            host="127.0.0.1",
            port=state["http_port"],
            threads=8,
            clear_untrusted_proxy_headers=True,
            channel_timeout=60,
        )

        def stop():
            while not Path(stop_file).exists():
                time.sleep(0.25)
            server.close()

        threading.Thread(target=stop, daemon=True).start()
        server.run()
    elif kind == "backup":
        from .maintenance import backup

        while not Path(stop_file).exists():
            # Start-of-day backup covers computers powered off each night.
            try:
                backup(root)
                (root / "runtime/backup/last-success.txt").write_text(str(time.time()))
            except Exception:
                (root / "runtime/backup/last-failure.txt").write_text(
                    "Backup falhou. Contacte a informática; cópias anteriores conservadas."
                )
            deadline = time.monotonic() + 24 * 3600
            while time.monotonic() < deadline and not Path(stop_file).exists():
                time.sleep(1)
    elif kind == "publisher":
        from .publisher import start

        start(root, stop_file)
    else:
        raise UnsafeOperation("Serviço desconhecido.")
