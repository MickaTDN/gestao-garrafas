"""Real isolated static publisher, trusted TLS/mTLS and installable offline PWA.

Uses the Stage 6 test-only device adapter; native Android certificate selection is
still a physical acceptance requirement. No trust-store changes on the host.
"""

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from scripts.build_vertente import PUBLIC
from tests.vertente.fixtures import fixture, grant, open_initial_shell, snapshot, wait_offline_shell
from tests.wifi.certificates import certificates
from tests.wifi.tls_device import tls_device
from tests.windows.smoke_stack import ROOT, free_port, run

HOST = "vertente.local.playwright"  # Distinct from the office smoke test's hostname.


def main():
    command = None
    with tempfile.TemporaryDirectory(prefix="gg-va7-https-") as temporary:
        home = Path(temporary)
        try:
            certificates(home / "tls", HOST)
            site = home / "site"
            for name in [*PUBLIC, "service-worker.js"]:
                target = site / "vertente" / name
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                target.parent.chmod(0o755)
                shutil.copyfile(ROOT / "vertente" / name, target)
                target.chmod(0o644)
            for name in ("signing.pem", "private.vastock.json"):
                sentinel = site / "vertente" / name
                sentinel.write_text("Synthetic sentinel, not a private key or real data.")
                sentinel.chmod(0o644)
            port = free_port()
            project = "gg-va7-test-" + uuid.uuid4().hex[:12]
            for kind in ("container", "volume", "network"):
                assert not run(
                    [
                        "docker",
                        kind,
                        "ls",
                        "-q",
                        "--filter",
                        "label=com.docker.compose.project=" + project,
                    ]
                )
            env = home / "publisher.env"
            env.write_text(
                f"VA_PROJECT={project}\nVA_BIND_IP=127.0.0.1\nVA_HTTPS_PORT={port}\nVA_SOURCE_ROOT={site}\nVA_PRIVATE_ROOT={home}\n"
            )
            (home / "nginx.conf").write_text(
                (ROOT / "deploy/vertente/nginx.conf.template").read_text().replace("__HOST__", HOST)
            )
            (home / "clients.conf").write_text("allow all;\n")
            for name in ("nginx.conf", "clients.conf"):
                (home / name).chmod(0o444)
            command = [
                "docker",
                "compose",
                "--project-name",
                project,
                "--file",
                str(ROOT / "deploy/vertente/compose.yaml"),
                "--env-file",
                str(env),
            ]
            run(command + ["run", "--rm", "--no-deps", "consultation", "nginx", "-t"])
            run(command + ["up", "-d"])
            container = run(command + ["ps", "-q", "consultation"])
            info = json.loads(run(["docker", "inspect", container]))[0]
            assert info["Config"]["Labels"]["com.docker.compose.project"] == project
            assert list(info["HostConfig"]["PortBindings"]) == ["8444/tcp"]
            assert all(
                p["HostIp"] == "127.0.0.1" for p in info["HostConfig"]["PortBindings"]["8444/tcp"]
            )
            assert not any(
                m["Type"] == "volume"
                or "signing" in m["Destination"]
                or "docker.sock" in m["Destination"]
                for m in info["Mounts"]
            )
            url = f"https://{HOST}:{port}"

            def curl(device="device", extra=(), path="/"):
                args = [
                    "curl",
                    "--silent",
                    "--show-error",
                    "--noproxy",
                    "*",
                    "--max-time",
                    "10",
                    "--resolve",
                    f"{HOST}:{port}:127.0.0.1",
                    "--cacert",
                    str(home / "tls/ca.crt"),
                    "-o",
                    str(home / "body"),
                    "-w",
                    "%{http_code}",
                ]
                if device:
                    args += [
                        "--cert",
                        str(home / f"tls/{device}.crt"),
                        "--key",
                        str(home / f"tls/{device}.key"),
                    ]
                return subprocess.run(
                    args + list(extra) + [url + path], check=True, capture_output=True, text=True
                ).stdout

            initial = curl()
            assert initial == "200", initial
            assert curl(device=None) == "400" and curl("revoked") == "400"
            assert curl(extra=("-X", "POST", "--data", "stock=999")) == "403"
            assert curl(extra=("-H", "Host: office.invalid")) == "421"
            for path in ("/signing.pem", "/private.vastock.json", "/entradas/", "/operacoes/"):
                assert curl(path=path) == "404"
            browser_home = home / "browser-home"
            nss = browser_home / ".pki/nssdb"
            nss.mkdir(parents=True)
            run(["certutil", "-N", "--empty-password", "-d", "sql:" + str(nss)])
            run(
                [
                    "certutil",
                    "-A",
                    "-n",
                    "VA synthetic CA",
                    "-t",
                    "C,,",
                    "-i",
                    str(home / "tls/ca.crt"),
                    "-d",
                    "sql:" + str(nss),
                ]
            )
            key, trust = fixture()
            stock = snapshot(key, trust)
            with tls_device(home / "tls", HOST, port), sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    str(home / "profile"),
                    executable_path=os.getenv("CHROMIUM_PATH") or shutil.which("chromium"),
                    headless=True,
                    args=[
                        "--no-sandbox",
                        f"--host-resolver-rules=MAP {HOST} 127.0.0.2",
                        "--no-proxy-server",
                    ],
                    env={**os.environ, "HOME": str(browser_home)},
                    viewport={"width": 393, "height": 851},
                    is_mobile=True,
                    has_touch=True,
                )
                try:
                    page = context.new_page()
                    page.set_default_timeout(12000)
                    open_initial_shell(page, url)
                    assert page.title() == "Stock Vertente Aveludada" and page.evaluate(
                        "window.isSecureContext"
                    )
                    page.locator("#trust-file").wait_for()
                    request = page.evaluate(
                        "async trust=>{const m=await import('/assets/store.js');await m.enroll(trust,trust.keys[0].key_id);return m.deviceRequest();}",
                        trust,
                    )
                    authorization = grant(key, trust, request)
                    page.evaluate(
                        "async ({authorization,stock})=>{const m=await import('/assets/store.js');await m.activate(authorization);await m.unlock('synthetic-private-owner-only-phrase');await m.importSnapshot(stock);}",
                        {"authorization": authorization, "stock": stock},
                    )
                    page.reload()
                    page.get_by_role(
                        "heading", name="Última atualização de stock", exact=True
                    ).wait_for()
                    page.evaluate(
                        "async()=>{await Promise.race([navigator.serviceWorker.ready,new Promise((_,r)=>setTimeout(()=>r(new Error('SW timeout')),12000))]);}"
                    )
                    page.reload()
                    wait_offline_shell(page)
                    session = context.new_cdp_session(page)
                    assert session.send("Page.getAppManifest")["errors"] == []
                    errors = session.send("Page.getInstallabilityErrors")["installabilityErrors"]
                    assert errors == [], errors
                    session.detach()
                    expect(page.locator(".reference")).to_have_count(3)
                    context.set_offline(True)
                    page.reload()
                    page.get_by_role(
                        "heading", name="Última atualização de stock", exact=True
                    ).wait_for()
                    page.get_by_label("Pesquisar pelo nome", exact=True).fill("CORACAO")
                    assert page.locator(".reference").count() == 1
                    page.get_by_label("Pesquisar pelo nome", exact=True).fill("")
                    page.get_by_label("Frase-passe do cofre", exact=True).fill(
                        "synthetic-private-owner-only-phrase"
                    )
                    page.get_by_role("button", name="Desbloquear", exact=True).click()
                    page.get_by_role("status").filter(has_text="Cofre desbloqueado").wait_for()
                    page.get_by_role("button", name="Água de Ensaio", exact=True).click()
                    page.get_by_role("button", name="Criar encomenda", exact=True).click()
                    page.get_by_role("button", name="Guardar encomenda", exact=True).click()
                    page.get_by_role("status").filter(has_text="Encomenda guardada").wait_for()
                    page.reload()
                    page.get_by_label("Frase-passe do cofre", exact=True).fill(
                        "synthetic-private-owner-only-phrase"
                    )
                    page.get_by_role("button", name="Desbloquear", exact=True).click()
                    page.get_by_role("status").filter(has_text="Cofre desbloqueado").wait_for()
                    saved = page.evaluate(
                        "async()=>(await(await import('/assets/store.js')).state()).orders"
                    )
                    assert len(saved) == 1 and saved[0]["state"] == "waiting"
                    assert page.evaluate("document.documentElement.scrollWidth") <= 393
                    assert context.cookies() == []
                    print(
                        "PASS Vertente: isolated static publisher, trusted HTTPS/mTLS, private-key exclusion, no write API, Android installability, offline reload/name search/encrypted owner orders and persistence",
                        flush=True,
                    )
                finally:
                    context.close()
        finally:
            if command:
                run(command + ["down", "--remove-orphans"])


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import traceback

        # Synthetic diagnostics only; never emit environment, keys or TLS URLs.
        detail = (
            (type(error).__name__ + ": " + str(error))
            .replace("%", "%25")
            .replace("\r", "%0D")
            .replace("\n", "%0A")
        )
        print("::error title=Stock HTTPS synthetic validation::" + detail, flush=True)
        traceback.print_exc()
        raise SystemExit(1)
