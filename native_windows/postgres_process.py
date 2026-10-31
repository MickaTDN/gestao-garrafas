"""Private PostgreSQL child environment and allowlisted, secret-free diagnostics."""

import json
import os
import subprocess
from pathlib import Path

from .package import UnsafeOperation, refuse_reparse
from .state import write_json

REASONS = {
    "dependency": "Dependência Windows em falta ou incompatível; confirme o runtime Microsoft.",
    "permission": "A conta virtual não conseguiu aceder aos ficheiros necessários.",
    "temporary": "O PostgreSQL não conseguiu utilizar o diretório temporário privado.",
    "identity": "O PostgreSQL não conseguiu validar a identidade da conta virtual.",
    "locale": "O PostgreSQL recusou a configuração de locale.",
    "timeout": "O comando PostgreSQL excedeu o limite de execução.",
    "command": "O comando PostgreSQL falhou; consulte o código de saída no diagnóstico.",
}


def child_environment(root, release):
    runtime = Path(root) / "runtime/postgres"
    temporary = runtime / "tmp"
    refuse_reparse(temporary)
    temporary.mkdir(exist_ok=True)
    env = {
        k: v for k, v in os.environ.items()
        if not k.upper().startswith(("PG", "DB_", "DJANGO_", "PYTHON", "GVA_", "GG_"))
    }
    env.update(TEMP=str(temporary), TMP=str(temporary), LC_ALL="C", LANGUAGE="C")
    env["PATH"] = str(Path(release) / "postgres/bin") + os.pathsep + env.get("PATH", "")
    return env


def reason(code, output):
    if code is not None and (code & 0xFFFFFFFF) in (0xC0000135, 0xC000007B, 0xC0000142):
        return "dependency"
    text = output.lower()
    for category, patterns in (
        ("temporary", ("temporary file", "temporary directory", "could not create temp")),
        ("permission", ("permission denied", "access is denied", "access denied")),
        ("identity", ("user name", "username", "effective user", "administrator")),
        ("locale", ("invalid locale", "locale name", "locale provider")),
    ):
        if any(pattern in text for pattern in patterns):
            return category
    return "command"


def command(root, release, tool, arguments, *, timeout, bootstrap=False):
    if tool not in ("initdb", "postgres", "pg_ctl"):
        raise UnsafeOperation("Comando PostgreSQL desconhecido.")
    stage = "initdb" if bootstrap else tool
    # pg_ctl starts a long-lived server on Windows. Captured anonymous pipes can
    # remain inherited by that server after pg_ctl exits: communicate() then
    # waits for EOF, even after killing pg_ctl on timeout. No pipes for a daemon
    # launcher; PostgreSQL already has its private -l server log.
    output_options = (
        {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if tool == "pg_ctl" else {"capture_output": True}
    )
    try:
        result = subprocess.run(
            [str(Path(release) / f"postgres/bin/{tool}.exe"), *map(str, arguments)],
            cwd=Path(root) / "runtime/postgres",
            env=child_environment(root, release),
            **output_options,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        code, category = None, "timeout"
    except OSError as error:
        code = error.winerror if hasattr(error, "winerror") else error.errno
        category = "permission" if isinstance(error, PermissionError) else "dependency"
    else:
        if result.returncode == 0:
            return result
        code = result.returncode
        # The output is examined only in memory, never persisted or sent to UI.
        output = ((result.stdout or b"") + (result.stderr or b"")).decode("utf-8", errors="replace")
        category = reason(code, output)
    record = {"command": stage, "exit_code": code, "reason": category}
    write_json(Path(root) / "runtime/postgres/startup-diagnostic.json", record)
    raise UnsafeOperation(
        f"PostgreSQL ({stage}): {REASONS[category]} Código: {code}. "
        "Preserve o cluster e maintenance.json; consulte runtime/postgres/startup-diagnostic.json."
    )


def startup_failure(root):
    """Use only typed/allowlisted fields, even if a service wrote unexpected JSON."""
    try:
        data = json.loads((Path(root) / "runtime/postgres/startup-diagnostic.json").read_text())
        if not isinstance(data, dict):
            return "Consulte runtime/postgres/last-error.txt e o diagnóstico de arranque."
        category = data.get("reason")
        code = data.get("exit_code")
        if category in REASONS and (code is None or type(code) is int):
            return REASONS[category] + f" Código: {code}."
    except (OSError, ValueError, TypeError):
        pass
    return "Consulte runtime/postgres/last-error.txt e o diagnóstico de arranque."
