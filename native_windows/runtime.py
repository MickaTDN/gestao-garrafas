"""Low-privilege service processes. All listeners have explicit addresses."""

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from .package import UnsafeOperation, digest


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
    try:
        subprocess.run(
            [str(release / "python/python.exe"), "-B", str(release / "app/manage.py"), *arguments],
            env=environment(root, owner=True),
            cwd=release / "app",
            check=True,
            timeout=600,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as error:
        raise UnsafeOperation(
            "Falha no comando Django de manutenção: "
            + arguments[0]
            + ". Código "
            + str(error.returncode)
        ) from error


def service(root, kind, stop_file):
    root = Path(root)
    state = read_state(root)
    release = Path(state["release"])
    if Path(__file__).resolve().parents[1] != (release / "app").resolve():
        raise UnsafeOperation(
            "Serviço de uma versão antiga recusado. Use apenas a versão instalada."
        )
    installed = json.loads((release.parent / "package.json").read_text())
    if installed["version"] != state["version"] or installed["channel"] != state["channel"]:
        raise UnsafeOperation("Versão/pacote inconsistentes; arranque recusado.")
    if state.get("package_sha256") != digest(release.parent / "package.json"):
        raise UnsafeOperation("O código não corresponde ao pacote instalado; arranque recusado.")
    permit = root / "activation-permit"
    permitted = permit.is_file() and permit.read_text() == state["release"]
    if kind != "postgres" and (root / "maintenance.json").exists() and not permitted:
        raise UnsafeOperation("Arranque bloqueado por manutenção incompleta.")
    ready_file = Path(str(stop_file) + ".ready")
    if kind == "postgres":
        # PostgreSQL owns WAL and crash recovery. Never use fsync=off or immediate shutdown.
        from .postgres_process import command

        pg = release / "postgres/bin/pg_ctl.exe"
        if not (root / "cluster/PG_VERSION").is_file():
            bootstrap = root / "runtime/postgres/bootstrap-password"
            if not bootstrap.is_file() or any((root / "cluster").iterdir()):
                raise UnsafeOperation(
                    "Cluster ausente/incompleto: inicialização automática recusada."
                )
            try:
                if Path(stop_file).exists():
                    raise UnsafeOperation("Arranque cancelado; preserve o cluster e o diário.")
                command(
                    root, release, "initdb",
                    [
                        "-D",
                        str(root / "cluster"),
                        "--username=gva_cluster",
                        "--encoding=UTF8",
                        "--locale-provider=builtin",
                        "--builtin-locale=C.UTF-8",
                        "--auth=scram-sha-256",
                        "--pwfile",
                        str(bootstrap),
                    ],
                    timeout=120,
                    bootstrap=True,
                )
                (root / "cluster/postgresql.conf").write_text(
                    f"listen_addresses = '127.0.0.1'\nport = {state['db_port']}\nfsync = on\nsynchronous_commit = on\nfull_page_writes = on\npassword_encryption = 'scram-sha-256'\ntimezone = 'UTC'\n",
                    encoding="ascii",
                )
                (root / "cluster/pg_hba.conf").write_text(
                    "host all all 127.0.0.1/32 scram-sha-256\n", encoding="ascii"
                )
            finally:
                bootstrap.unlink(missing_ok=True)
        if Path(stop_file).exists():
            raise UnsafeOperation("Arranque cancelado; preserve o cluster e o diário.")
        command(
            root, release, "pg_ctl",
            [
                "-D",
                str(root / "cluster"),
                "-l",
                str(root / "runtime/postgres/server.log"),
                "-w",
                "start",
            ],
            timeout=90,
        )
        ready_file.write_text("ready")
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
        from .schema import assert_current

        assert_current()
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
            server.task_dispatcher.shutdown(cancel_pending=False, timeout=60)
            from waitress import wasyncore

            wasyncore.close_all(map=server._map)

        ready_file.write_text("ready")
        threading.Thread(target=stop, daemon=True).start()
        server.run()
    elif kind == "backup":
        from .maintenance import backup

        ready_file.write_text("ready")

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
