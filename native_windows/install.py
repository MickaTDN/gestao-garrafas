"""Fresh-install bootstrap; never adopts a pre-existing directory or database."""

import json
import secrets
import tempfile
import time
import uuid
from pathlib import Path

import psycopg
from psycopg import sql

from .crypto_backup import create_recovery_key
from .maintenance import connection, grants
from .package import UnsafeOperation
from .runtime import manage, read_state
from .state import write_json
from .windows import SERVICES, activate, administrator, configure, free_port, native, protect


def prepare_acl(root):
    root = Path(root)
    protect(root, [(kind, "RX") for kind in SERVICES])
    native(["icacls.exe", root, "/grant:r", "*S-1-5-32-545:(OI)(CI)RX"])
    for name, rights in {
        "cluster": [("postgres", "M")],
        "runtime": [(kind, "RX") for kind in SERVICES],
        "runtime/web": [("web", "M")],
        "runtime/postgres": [("postgres", "M")],
        "runtime/backup": [("backup", "M")],
        "runtime/publisher": [("publisher", "M")],
        "secrets": [("web", "RX"), ("backup", "RX")],
        "signing": [("web", "R"), ("backup", "R")],
        "tls": [("publisher", "R"), ("backup", "R")],
        "backups": [("backup", "M")],
    }.items():
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        protect(path, rights)
    # Web process must not read the migration/backup credentials.
    protect(root / "secrets/owner.json", [("backup", "R")])
    protect(root / "secrets/app.json", [("web", "R"), ("backup", "R")])


def wait_database(root):
    for _ in range(60):
        try:
            with connection(root):
                return
        except psycopg.OperationalError:
            time.sleep(1)
    raise UnsafeOperation("O PostgreSQL local não ficou disponível.")


def create_cluster(root):
    root = Path(root)
    state = read_state(root)
    release = Path(state["release"])
    owner = json.loads((root / "secrets/owner.json").read_text())
    app = json.loads((root / "secrets/app.json").read_text())
    cluster_password = secrets.token_urlsafe(48)
    with tempfile.TemporaryDirectory(dir=root, prefix=".initialize-") as temporary:
        password_file = Path(temporary) / "password"
        password_file.write_text(cluster_password)
        native(
            [
                release / "postgres/bin/initdb.exe",
                "-D",
                root / "cluster",
                "--username=gva_cluster",
                "--encoding=UTF8",
                "--locale=C",
                "--auth=scram-sha-256",
                "--pwfile",
                password_file,
            ]
        )
    # IPv4 loopback only, even if a local environment variable requests another host.
    (root / "cluster/postgresql.conf").write_text(
        f"listen_addresses = '127.0.0.1'\nport = {state['db_port']}\nfsync = on\nsynchronous_commit = on\nfull_page_writes = on\npassword_encryption = 'scram-sha-256'\n",
        encoding="ascii",
    )
    (root / "cluster/pg_hba.conf").write_text(
        "host all all 127.0.0.1/32 scram-sha-256\n", encoding="ascii"
    )
    # initdb was run elevated. Transfer only the NEW cluster to its dedicated service.
    native(
        [
            "icacls.exe",
            root / "cluster",
            "/grant:r",
            f"NT SERVICE\\{SERVICES['postgres']}:(OI)(CI)M",
            "/T",
            "/Q",
        ]
    )
    native(["sc.exe", "config", SERVICES["postgres"], "start=", "demand"])
    native(["sc.exe", "start", SERVICES["postgres"]])
    for attempt in range(60):
        try:
            cluster = psycopg.connect(
                host="127.0.0.1",
                port=state["db_port"],
                dbname="postgres",
                user="gva_cluster",
                password=cluster_password,
                autocommit=True,
            )
            break
        except psycopg.OperationalError:
            if attempt == 59:
                raise
            time.sleep(1)
    with cluster:
        cluster.execute(
            sql.SQL(
                "CREATE ROLE gva_owner LOGIN NOSUPERUSER CREATEDB NOCREATEROLE PASSWORD {}"
            ).format(sql.Literal(owner["password"]))
        )
        cluster.execute(
            sql.SQL(
                "CREATE ROLE gva_web LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
            ).format(sql.Literal(app["password"]))
        )
        cluster.execute(
            sql.SQL("CREATE DATABASE {} OWNER gva_owner TEMPLATE template0").format(
                sql.Identifier(state["database"])
            )
        )
        cluster.execute("ALTER ROLE gva_cluster NOLOGIN")
    # No cluster-superuser credential retained in the installed application.


def initial(root, release, manifest, request, trust_path):
    administrator()
    root, release = Path(root), Path(release)
    if root.exists() and any(root.iterdir()):
        raise UnsafeOperation("A pasta privada já existe. Instalação recusada; não foi adotada.")
    if len(request.get("password", "")) < 12 or not request.get("username"):
        raise UnsafeOperation(
            "Indique a conta inicial e uma palavra-passe de pelo menos 12 caracteres."
        )
    if manifest["channel"] == "synthetic" and not request["synthetic"]:
        raise UnsafeOperation("O instalador de validação só permite dados fictícios.")
    recovery = Path(request["recovery_key"])
    if (
        not recovery.is_absolute()
        or recovery.exists()
        or root == recovery
        or root in recovery.parents
        or release in recovery.parents
        or not recovery.parent.is_dir()
    ):
        raise UnsafeOperation(
            "Escolha um ficheiro NOVO num suporte empresarial autorizado, fora da instalação."
        )
    private, public = create_recovery_key(request["recovery_password"])
    for port in (request.get("db_port", 55432), request.get("http_port", 8765)):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise UnsafeOperation("Porta inválida.")
        free_port(port)
    if request.get("db_port", 55432) == request.get("http_port", 8765):
        raise UnsafeOperation("As portas da base e da aplicação devem ser diferentes.")
    from .windows import exists

    if any(exists(name) for name in SERVICES.values()):
        raise UnsafeOperation("Já existem serviços com estes nomes; nenhum foi alterado.")
    root.mkdir(parents=True, exist_ok=True)
    protect(root)
    state = {
        "schema": 1,
        "instance": str(uuid.uuid4()),
        "version": manifest["version"],
        "release": str(release),
        "channel": manifest["channel"],
        "postgres_major": 17,
        "database": "gva_native_synthetic" if request["synthetic"] else "gva_native",
        "db_port": request.get("db_port", 55432),
        "http_port": request.get("http_port", 8765),
    }
    write_json(root / "package-policy.json", json.loads(Path(trust_path).read_text()))
    write_json(root / "installation.json", state)
    write_json(root / "maintenance.json", {"phase": "initializing", "version": state["version"]})
    configure(root, release, create=True)
    (root / "secrets").mkdir()
    django_key = secrets.token_urlsafe(64)
    for name, user in (("owner", "gva_owner"), ("app", "gva_web")):
        write_json(
            root / f"secrets/{name}.json",
            {"username": user, "password": secrets.token_urlsafe(48), "django_key": django_key},
        )
    write_json(root / "backup-policy.json", {"retain": 14, "copy_to": None})
    (root / "recovery-public.pem").write_bytes(public)
    with recovery.open("xb") as stream:
        stream.write(private)
    protect(recovery)
    prepare_acl(root)
    create_cluster(root)
    manage(root, "migrate", "--noinput")
    grants(root)
    # Dedicated GUI supplies input on stdin; credentials never appear in process arguments.
    import subprocess

    from .runtime import environment

    subprocess.run(
        [str(release / "python/python.exe"), "-B", "-m", "native_windows.provision"],
        input=json.dumps(
            {
                "username": request["username"],
                "password": request["password"],
                "synthetic": request["synthetic"],
            }
        ).encode(),
        env=environment(root, owner=True),
        cwd=release / "app",
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120,
    )
    manage(root, "vertente_setup", "--directory", str(root / "signing"))
    manage(root, "check", "--fail-level", "WARNING")
    (root / "maintenance.json").unlink()
    activate(root)


def health_http(root):
    import urllib.request

    port = read_state(root)["http_port"]
    for _ in range(45):
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{port}/entrar/", timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise UnsafeOperation("O servidor não respondeu. Não remova dados; contacte a informática.")
