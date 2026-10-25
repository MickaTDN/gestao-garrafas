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

from playwright.sync_api import sync_playwright

from tests.vertente.fixtures import fixture, snapshot
from tests.wifi.certificates import certificates
from tests.wifi.tls_device import tls_device
from tests.windows.smoke_stack import ROOT, free_port, run

HOST = "local.playwright"


def main():
    command = None
    with tempfile.TemporaryDirectory(prefix="gg-va7-https-") as temporary:
        home = Path(temporary)
        try:
            certificates(home / "tls", HOST)
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
                f"VA_PROJECT={project}\nVA_BIND_IP=127.0.0.1\nVA_HTTPS_PORT={port}\nVA_SOURCE_ROOT={ROOT}\nVA_PRIVATE_ROOT={home}\n"
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

            def curl(device="device", extra=()):
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
                    args + list(extra) + [url + "/"], check=True, capture_output=True, text=True
                ).stdout

            assert curl() == "200"
            assert curl(device=None) == "400" and curl("revoked") == "400"
            assert curl(extra=("-X", "POST", "--data", "stock=999")) == "403"
            assert curl(extra=("-H", "Host: office.invalid")) == "421"
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
                    page.goto(url)
                    assert page.title() == "Vertente Aveludada" and page.evaluate(
                        "window.isSecureContext"
                    )
                    page.evaluate(
                        "async ({trust,stock})=>{const m=await import('/assets/store.js');await m.enroll(trust,trust.keys[0].key_id);await m.importSnapshot(stock);}",
                        {"trust": trust, "stock": stock},
                    )
                    page.reload()
                    page.get_by_role(
                        "heading", name="A sua fotografia de stock", exact=True
                    ).wait_for()
                    page.evaluate(
                        "async()=>{await Promise.race([navigator.serviceWorker.ready,new Promise((_,r)=>setTimeout(()=>r(new Error('SW timeout')),12000))]);}"
                    )
                    page.reload()
                    page.wait_for_function("navigator.serviceWorker.controller !== null")
                    session = context.new_cdp_session(page)
                    assert session.send("Page.getAppManifest")["errors"] == []
                    errors = session.send("Page.getInstallabilityErrors")["installabilityErrors"]
                    assert errors == [], errors
                    session.detach()
                    assert page.locator(".reference-card").count() == 3
                    context.set_offline(True)
                    page.reload()
                    page.get_by_role(
                        "heading", name="A sua fotografia de stock", exact=True
                    ).wait_for()
                    page.get_by_label("Pesquisar designação ou código", exact=True).fill("CORACAO")
                    assert page.locator(".reference-card").count() == 1
                    page.get_by_label("Pesquisar designação ou código", exact=True).fill("")
                    card = page.locator('[data-id="1"]')
                    card.get_by_text("Configurar alerta mínimo", exact=True).click()
                    card.get_by_label("Limite de garrafas", exact=True).fill("24")
                    card.get_by_role("button", name="Guardar alerta", exact=True).click()
                    page.get_by_role("status").filter(has_text="Alerta guardado").wait_for()
                    page.get_by_role("button", name="Já encomendada", exact=True).click()
                    page.locator("#confirmation").get_by_role(
                        "button", name="Confirmar", exact=True
                    ).click()
                    page.get_by_role("status").filter(has_text="Encomenda registada").wait_for()
                    page.reload()
                    page.get_by_role(
                        "heading", name="A sua fotografia de stock", exact=True
                    ).wait_for()
                    assert page.locator('.metric[data-filter="ordered"] strong').inner_text() == "1"
                    assert page.evaluate("document.documentElement.scrollWidth") <= 393
                    assert context.cookies() == []
                    print(
                        "PASS Vertente: isolated static publisher, trusted HTTPS/mTLS, private-key exclusion, no write API, Android installability, offline reload/search/alerts/orders and persistence",
                        flush=True,
                    )
                finally:
                    context.close()
        finally:
            if command:
                run(command + ["down", "--remove-orphans"])


if __name__ == "__main__":
    main()
