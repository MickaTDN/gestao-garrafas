"""Exercise the Windows Compose payload on a NEW, disposable Linux engine project.

The Windows/PowerShell shell and ACLs are tested separately on a Windows CI runner.
No existing container, database, namespace or volume is adopted or removed.
"""

import argparse
import json
import secrets
import socket
import subprocess
import tempfile
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(args, *, capture=True, env=None):
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            env=env,
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE,
            timeout=300,
        )
    except subprocess.CalledProcessError as error:
        # CI-only synthetic output. User scripts never dump Docker environments/secrets.
        detail = ((error.stdout or "") + " " + (error.stderr or ""))[-1800:]
        detail = detail.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error title=Windows pilot integration::" + detail, flush=True)
        raise
    return result.stdout.strip() if capture else ""


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def make_state(home, image, port):
    instance = uuid.uuid4()
    project = "gg-win5-" + instance.hex[:12]
    home.mkdir(mode=0o700)
    secret_root = home / "secrets"
    secret_root.mkdir(mode=0o700)
    for name in ("django_key", "db_owner_password", "db_app_password"):
        path = secret_root / name
        path.write_text(secrets.token_urlsafe(48) + "\n")
        # Compose bind-mounted secrets retain host modes on Linux. The enclosing
        # temporary directories are 0700; the read-only file must be readable by
        # container UID 10001. Windows uses private NTFS ACLs instead.
        path.chmod(0o444)
    env_file = home / "pilot.env"
    escaped_secret_root = str(secret_root).replace("'", "\\'")
    env_file.write_text(
        f"GG_PILOT_ID={instance}\nGG_PILOT_IMAGE={image}\nGG_HTTP_PORT={port}\nGG_SOURCE_ROOT='{ROOT}'\nGG_SECRET_ROOT='{escaped_secret_root}'\n"
    )
    env_file.chmod(0o600)
    command = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--file",
        str(ROOT / "deploy/windows/compose.yaml"),
        "--env-file",
        str(env_file),
    ]
    existing = run(
        [
            "docker",
            "volume",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ]
    )
    if existing:
        raise RuntimeError("Refusing an existing pilot namespace")
    return str(instance), project, command


def compose(command, *args):
    return run(command + list(args))


def status(command):
    return json.loads(
        compose(command, "exec", "-T", "app", "python", "/app/deploy/windows/pilot.py", "status")
    )


def sql(command, statement):
    return compose(
        command,
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        "gg_pilot_owner",
        "-d",
        "garrafas_windows_synthetic",
        "-tA",
        "-c",
        statement,
    )


def validate_scope(command, project):
    ids = compose(command, "ps", "--quiet").splitlines()
    for container in ids:
        data = json.loads(run(["docker", "inspect", container]))[0]
        assert data["Config"]["Labels"]["com.docker.compose.project"] == project
        service = data["Config"]["Labels"]["com.docker.compose.service"]
        bindings = data["HostConfig"]["PortBindings"] or {}
        if service == "db":
            assert not bindings
        else:
            assert set(bindings) == {"8000/tcp"}
            assert all(binding["HostIp"] == "127.0.0.1" for binding in bindings["8000/tcp"])
    volumes = run(
        [
            "docker",
            "volume",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ]
    ).splitlines()
    assert volumes and all(name.startswith(project + "_") for name in volumes)
    return volumes


def main(image):
    source = None
    recovered = None
    with tempfile.TemporaryDirectory(prefix="gg-windows-stack-") as temporary:
        root = Path(temporary)
        try:
            instance, project, source = make_state(root / "source O'Neill $", image, free_port())
            config = json.loads(compose(source, "config", "--format", "json"))
            assert not config["services"]["db"].get("ports")
            assert config["networks"]["pilot"]["internal"] is True
            assert (
                config["services"]["app"]["environment"]["DJANGO_SETTINGS_MODULE"]
                == "config.windows_local"
            )
            compose(source, "up", "--detach", "--wait", "--wait-timeout", "120", "db")
            compose(source, "--profile", "setup", "run", "--rm", "initialize")
            compose(source, "up", "--detach", "--wait", "--wait-timeout", "180", "app")
            current = status(source)
            assert current["instance"] == instance and current["references"] == 3
            assert not current["administrator_exists"]
            assert sql(source, "SELECT count(*) FROM inventory_importbatch") == "0"
            assert sql(source, "SELECT count(*) FROM inventory_location") == "4"
            assert sql(source, "SELECT count(*) FROM inventory_sector") == "27"
            volumes = validate_scope(source, project)
            port = config["services"]["app"]["ports"][0]["published"]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/entrar/", timeout=10) as response:
                assert response.status == 200
                assert "no-store" in response.headers["Cache-Control"]
                assert "Traceback" not in response.read().decode()
            # Create only an unusable-password synthetic actor, then exercise the SAME services.
            code = "from accounts.models import User; from inventory.models import Reference; from tests.document_fixtures import confirmed_operation; u=User.objects.create_user(username='windows-smoke-synthetic',role='admin'); r=Reference.objects.get(code='SYN-WIN-001'); confirmed_operation(u,r,units=2,signed=True)"
            compose(
                source,
                "exec",
                "-T",
                "app",
                "python",
                "manage.py",
                "shell",
                "--verbosity",
                "0",
                "-c",
                code,
            )
            expected_stock = sql(
                source, "SELECT current_stock FROM inventory_reference WHERE code='SYN-WIN-001'"
            )
            expected_documents = sql(
                source, "SELECT string_agg(sha256,',' ORDER BY id) FROM inventory_document"
            )
            assert expected_stock == "22" and len(expected_documents.split(",")) == 2
            # Explicit repair/migrations are idempotent: no duplicate synthetic balances.
            compose(source, "--profile", "setup", "run", "--rm", "initialize")
            assert sql(source, "SELECT count(*) FROM inventory_openingbalance") == "3"
            assert (
                sql(
                    source, "SELECT current_stock FROM inventory_reference WHERE code='SYN-WIN-001'"
                )
                == expected_stock
            )
            compose(source, "stop", "--timeout", "45", "app", "db")
            assert all(
                run(["docker", "volume", "inspect", volume, "--format", "{{.Name}}"]) == volume
                for volume in volumes
            )
            compose(source, "up", "--detach", "--wait", "--wait-timeout", "180", "app")
            assert (
                sql(
                    source, "SELECT current_stock FROM inventory_reference WHERE code='SYN-WIN-001'"
                )
                == expected_stock
            )
            compose(
                source, "exec", "-T", "app", "python", "manage.py", "backup_data", "--synthetic"
            )
            archives = json.loads(
                compose(
                    source,
                    "exec",
                    "-T",
                    "app",
                    "python",
                    "-c",
                    "import json;from pathlib import Path;print(json.dumps([p.name for p in Path('/backups').glob('gg-backup-*.tar.gz')]))",
                )
            )
            archive = root / "copy.tar.gz"
            compose(source, "cp", f"app:/backups/{archives[-1]}", str(archive))
            archive.chmod(0o444)  # read-only bind for container UID, private parent remains 0700
            instance2, project2, recovered = make_state(root / "recovered", image, free_port())
            compose(recovered, "up", "--detach", "--wait", "--wait-timeout", "120", "db")
            compose(
                recovered,
                "--profile",
                "setup",
                "run",
                "--rm",
                "--volume",
                f"{archive}:/restore/pilot.tar.gz:ro",
                "initialize",
                "python",
                "/app/deploy/windows/pilot.py",
                "recover",
            )
            compose(recovered, "up", "--detach", "--wait", "--wait-timeout", "180", "app")
            assert status(recovered)["instance"] == instance2
            assert (
                sql(
                    recovered,
                    "SELECT current_stock FROM inventory_reference WHERE code='SYN-WIN-001'",
                )
                == expected_stock
            )
            assert (
                sql(recovered, "SELECT string_agg(sha256,',' ORDER BY id) FROM inventory_document")
                == expected_documents
            )
            # Restore a second time MUST refuse to touch an existing target.
            result = subprocess.run(
                recovered
                + [
                    "--profile",
                    "setup",
                    "run",
                    "--rm",
                    "--volume",
                    f"{archive}:/restore/pilot.tar.gz:ro",
                    "initialize",
                    "python",
                    "/app/deploy/windows/pilot.py",
                    "recover",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            assert result.returncode != 0
            assert (
                sql(
                    source, "SELECT current_stock FROM inventory_reference WHERE code='SYN-WIN-001'"
                )
                == expected_stock
            )
            assert status(source)["instance"] == instance
            assert (
                sql(
                    recovered,
                    "SELECT current_stock FROM inventory_reference WHERE code='SYN-WIN-001'",
                )
                == expected_stock
            )
            validate_scope(recovered, project2)
            print(
                "Windows payload smoke: isolated setup, least-privilege operation, PDF/signature, restart persistence, backup, separate recovery, existing-target refusal and unchanged source: PASS"
            )
        finally:
            # Test-only cleanup: only randomly-created namespaces from THIS process.
            # User-facing Windows scripts intentionally contain no removal/reset command.
            for command in (recovered, source):
                if command:
                    compose(command, "--profile", "setup", "down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    main(parser.parse_args().image)
