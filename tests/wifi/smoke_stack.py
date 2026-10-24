"""Real TLS/mTLS + Android Chromium on an exclusively NEW synthetic Docker project.

No OS trust store changes: Chromium uses a temporary HOME/NSS store. No TLS bypass.
All destructive cleanup below is limited to this randomly allocated test namespace.
"""

import argparse
import io
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright
from pypdf import PdfReader

from tests.wifi.certificates import certificates
from tests.windows.smoke_stack import ROOT, free_port, make_state, run

# Playwright's reserved loopback name avoids external DNS inside its mTLS transport.
HOST = "local.playwright"


def main(image):
    command = None
    with tempfile.TemporaryDirectory(prefix="gg-wifi6-") as temporary:
        root = Path(temporary)
        try:
            # Reuse only the Stage 5 secret generator; never run/adopt its stack.
            instance, _, base = make_state(root / "installation", image, free_port())
            home = root / "installation"
            certificates(home / "tls", HOST)
            port = free_port()
            project = "gg-wifi6-test-" + uuid.uuid4().hex[:12]
            # /29 allocated from a random test-only subnet, not a LAN interface.
            subnet = f"172.30.{secrets.randbelow(240) + 10}"
            env_path = home / "pilot.env"
            env_path.write_text(
                env_path.read_text()
                + f"GG_WIFI_PRIVATE_ROOT={home}\nGG_WIFI_HOST={HOST}\nGG_BIND_IP=127.0.0.1\nGG_HTTPS_PORT={port}\nGG_PROXY_SUBNET={subnet}.0/29\nGG_PROXY_IP={subnet}.2\nGG_APP_IP={subnet}.3\n"
            )
            template = (ROOT / "deploy/wifi/nginx.conf.template").read_text()
            (home / "nginx.conf").write_text(
                template.replace("__HOST__", HOST).replace("__PORT__", str(port))
            )
            # Test engine may NAT the host. Device identity is independently mTLS.
            (home / "clients.conf").write_text("allow all;\n")
            for name in ("nginx.conf", "clients.conf"):
                (home / name).chmod(0o444)
            candidate = [
                "docker",
                "compose",
                "--project-name",
                project,
                "--file",
                str(ROOT / "deploy/wifi/compose.yaml"),
                "--env-file",
                str(env_path),
            ]
            for resource in ("volume", "network", "container"):
                assert not run(
                    [
                        "docker",
                        resource,
                        "ls",
                        "-q",
                        "--filter",
                        f"label=com.docker.compose.project={project}",
                    ]
                )
            command = candidate

            def compose(*args):
                return run(command + list(args))

            def shell(code):
                result = subprocess.run(
                    command + ["exec", "-T", "app", "python", "manage.py", "shell"],
                    input=code,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode:
                    raise RuntimeError("Synthetic fixture/status command failed (input withheld).")
                return result.stdout.strip()

            config = json.loads(compose("--profile", "setup", "config", "--format", "json"))
            for service in ("app", "db", "initialize"):
                assert not config["services"][service].get("ports")
            assert config["services"]["proxy"]["ports"][0]["host_ip"] == "127.0.0.1"
            assert config["networks"]["pilot"]["internal"]
            assert config["networks"]["backend"]["internal"]
            compose("up", "-d", "--wait", "db")
            compose("--profile", "setup", "run", "--rm", "initialize")
            compose("up", "-d", "--wait", "--wait-timeout", "180", "app")
            compose("run", "--rm", "--no-deps", "proxy", "nginx", "-t")
            compose("up", "-d", "proxy")
            url = f"https://{HOST}:{port}"
            tls = home / "tls"

            def curl(path="/entrar/", device="device", extra=(), *, check=True):
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
                    str(tls / "ca.crt"),
                    "--output",
                    str(root / "curl-body"),
                    "--write-out",
                    "%{http_code}",
                ]
                if device:
                    args += [
                        "--cert",
                        str(tls / (device + ".crt")),
                        "--key",
                        str(tls / (device + ".key")),
                    ]
                return subprocess.run(
                    args + list(extra) + [url + path], capture_output=True, text=True, check=check
                )

            assert curl().stdout == "200"
            assert curl(device=None).stdout == "400"
            assert curl(device="revoked").stdout == "400"
            assert curl(extra=("--header", "Host: evil.invalid")).stdout == "421"
            # Supplied headers cannot turn HTTPS into HTTP or spoof login's client IP.
            assert (
                curl(
                    extra=(
                        "--header",
                        "X-Forwarded-Proto: http",
                        "--header",
                        "X-Forwarded-For: 1.1.1.1",
                    )
                ).stdout
                == "200"
            )
            assert curl("/stock/").stdout == "302"
            assert curl(extra=("--request", "POST", "--data", "username=x")).stdout == "403"
            # Removing server trust must fail; no -k / ignore_https_errors anywhere.
            bad = subprocess.run(
                [
                    "curl",
                    "--silent",
                    "--noproxy",
                    "*",
                    "--resolve",
                    f"{HOST}:{port}:127.0.0.1",
                    url + "/entrar/",
                ],
                capture_output=True,
            )
            assert bad.returncode == 60
            (home / "clients.conf").chmod(0o644)
            (home / "clients.conf").write_text("# no authorised network origins\n")
            compose("exec", "-T", "proxy", "nginx", "-s", "reload")
            # A new connection observes the replacement worker after reload.
            import time

            for _ in range(25):
                if curl().stdout == "403":
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("Network default-deny did not apply")
            (home / "clients.conf").write_text("allow all;\n")
            compose("exec", "-T", "proxy", "nginx", "-s", "reload")
            for _ in range(25):
                if curl().stdout == "200":
                    break
                time.sleep(0.1)

            password = secrets.token_urlsafe(32)
            shell(
                "from accounts.models import User; from inventory.models import ImportBatch; assert not ImportBatch.objects.exists(); "
                + f"User.objects.create_user(username='wifi-synthetic-admin',password={password!r},role='admin'); User.objects.create_user(username='wifi-synthetic-viewer',password={password!r})"
            )
            browser_home = root / "browser-home"
            nss = browser_home / ".pki/nssdb"
            nss.mkdir(parents=True)
            run(["certutil", "-N", "--empty-password", "-d", "sql:" + str(nss)])
            run(
                [
                    "certutil",
                    "-A",
                    "-n",
                    "Synthetic WiFi CA",
                    "-t",
                    "C,,",
                    "-i",
                    str(tls / "ca.crt"),
                    "-d",
                    "sql:" + str(nss),
                ]
            )
            # The Playwright certificate transport also validates the private test CA.
            old_ca = os.environ.get("NODE_EXTRA_CA_CERTS")
            old_no_proxy = {key: os.environ.get(key) for key in ("NO_PROXY", "no_proxy")}
            os.environ["NODE_EXTRA_CA_CERTS"] = str(tls / "ca.crt")
            os.environ.update(NO_PROXY="*", no_proxy="*")
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        executable_path=os.getenv("CHROMIUM_PATH") or shutil.which("chromium"),
                        headless=True,
                        args=["--no-sandbox", f"--host-resolver-rules=MAP {HOST} 127.0.0.1"],
                        env={**os.environ, "HOME": str(browser_home)},
                    )
                    context = browser.new_context(
                        viewport={"width": 393, "height": 851},
                        is_mobile=True,
                        has_touch=True,
                        client_certificates=[
                            {
                                "origin": url,
                                "certPath": tls / "device.crt",
                                "keyPath": tls / "device.key",
                            }
                        ],
                    )
                    page = context.new_page()
                    page.set_default_timeout(12000)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))

                    def login(username):
                        page.goto(url + "/stock/")
                        page.get_by_label("Utilizador", exact=True).fill(username)
                        page.get_by_label("Palavra-passe", exact=True).fill(password)
                        page.get_by_role("button", name="Entrar", exact=True).click()
                        page.wait_for_url(url + "/stock/")

                    login("wifi-synthetic-admin")
                    assert page.evaluate("window.isSecureContext")
                    assert all(
                        c["secure"]
                        for c in context.cookies()
                        if c["name"] in ("sessionid", "csrftoken")
                    )
                    page.evaluate("async () => { await navigator.serviceWorker.ready; }")
                    page.reload()
                    page.wait_for_function("navigator.serviceWorker.controller !== null")
                    session = context.new_cdp_session(page)
                    assert (
                        session.send("Page.getInstallabilityErrors")["installabilityErrors"] == []
                    )
                    session.detach()

                    def stocks():
                        return json.loads(
                            shell(
                                "import json; from inventory.models import Reference; print(json.dumps(list(Reference.objects.order_by('code').values_list('current_stock',flat=True))))"
                            ).splitlines()[-1]
                        )

                    def create(kind, codes):
                        page.goto(url + ("/entradas/" if kind == "entry" else "/saidas/"))
                        page.get_by_role("button", name="Criar rascunho", exact=True).click()
                        for code in codes:
                            page.get_by_label("Adicionar " + code, exact=True).check()
                        page.get_by_role(
                            "button", name="Adicionar selecionadas e guardar", exact=True
                        ).click()
                        page.get_by_label("Pessoa que entregou / levantou", exact=True).fill(
                            "Pessoa Wi-Fi fictícia"
                        )
                        for row in page.locator(".operation-line").all():
                            assert row.get_by_label("Caixas", exact=True).input_value() == ""
                            assert (
                                row.get_by_label("Garrafas soltas", exact=True).input_value() == ""
                            )

                    create("entry", ["SYN-WIN-001", "SYN-WIN-003"])
                    page.locator(".operation-line").filter(has_text="SYN-WIN-001").get_by_label(
                        "Caixas", exact=True
                    ).fill("1")
                    page.locator(".operation-line").filter(has_text="SYN-WIN-001").get_by_label(
                        "Garrafas soltas", exact=True
                    ).fill("2")
                    page.locator(".operation-line").filter(has_text="SYN-WIN-003").get_by_label(
                        "Garrafas soltas", exact=True
                    ).fill("1")
                    page.get_by_role(
                        "button", name="Guardar e conferir operação", exact=True
                    ).click()
                    assert stocks() == [24, 0, 9]
                    page.locator('[name="report_requested"]').select_option("yes")
                    page.locator('[name="confirm"]').check()
                    page.get_by_role("button", name="Confirmar entrada", exact=True).click()
                    page.get_by_text("CONFIRMADO", exact=True).wait_for()
                    assert stocks() == [32, 0, 10]

                    create("exit", ["SYN-WIN-001", "SYN-WIN-003"])
                    page.locator(".operation-line").filter(has_text="SYN-WIN-001").get_by_label(
                        "Garrafas soltas", exact=True
                    ).fill("2")
                    page.locator(".operation-line").filter(has_text="SYN-WIN-003").get_by_label(
                        "Garrafas soltas", exact=True
                    ).fill("1")
                    page.get_by_role(
                        "button", name="Guardar e conferir operação", exact=True
                    ).click()
                    review_url = page.url
                    page.get_by_label("Validação da saída", exact=True).select_option("signed")
                    canvas = page.locator("#signature-canvas")
                    canvas.scroll_into_view_if_needed()
                    bounds = canvas.bounding_box()
                    session = context.new_cdp_session(page)
                    points = [
                        {
                            "x": bounds["x"] + bounds["width"] * x,
                            "y": bounds["y"] + bounds["height"] * y,
                        }
                        for x, y in [(0.1, 0.7), (0.25, 0.2), (0.4, 0.8), (0.55, 0.3), (0.8, 0.65)]
                    ]
                    session.send(
                        "Input.dispatchTouchEvent",
                        {"type": "touchStart", "touchPoints": [points[0]]},
                    )
                    for point in points[1:]:
                        session.send(
                            "Input.dispatchTouchEvent",
                            {"type": "touchMove", "touchPoints": [point]},
                        )
                    session.send(
                        "Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}
                    )
                    session.detach()
                    assert (
                        page.locator('[name="signature_data"]')
                        .input_value()
                        .startswith("data:image/png")
                    )
                    page.locator('[name="confirm"]').check()
                    # Capture the exact original payload for a deliberate duplicate test.
                    payload = page.locator("form.card").evaluate(
                        "form => Object.fromEntries(new FormData(form))"
                    )
                    page.get_by_role("button", name="Confirmar saída", exact=True).click()
                    page.get_by_text("CONFIRMADO", exact=True).wait_for()
                    assert stocks() == [30, 0, 9]
                    pdf_url = page.get_by_role(
                        "link", name="Abrir / imprimir PDF", exact=True
                    ).get_attribute("href")
                    # Browser fetch uses the same trusted TLS + device identity as navigation.
                    pdf_data = page.evaluate(
                        "async path => { const r=await fetch(path); return {status:r.status, cache:r.headers.get('cache-control'), bytes:Array.from(new Uint8Array(await r.arrayBuffer()))}; }",
                        pdf_url,
                    )
                    assert pdf_data["status"] == 200 and "no-store" in pdf_data["cache"]
                    assert any(
                        list(p.images)
                        for p in PdfReader(io.BytesIO(bytes(pdf_data["bytes"]))).pages
                    )
                    assert (
                        page.evaluate(
                            "async ({path,data}) => (await fetch(path,{method:'POST',body:new URLSearchParams(data)})).status",
                            {"path": review_url, "data": payload},
                        )
                        == 200
                    )
                    assert stocks() == [30, 0, 9]

                    page.goto(url + "/inventario/")
                    page.get_by_label("Âmbito", exact=True).select_option("full")
                    page.get_by_role("button", name="Criar rascunho", exact=True).click()
                    rows = page.locator(".operation-line")
                    for row, quantity in zip(rows.all(), (29, 0, 9), strict=True):
                        assert row.get_by_label("Garrafas soltas", exact=True).input_value() == ""
                        row.get_by_label("Garrafas soltas", exact=True).fill(str(quantity))
                        row.get_by_label("Motivo da diferença / transferência", exact=True).fill(
                            "Contagem Wi-Fi sintética"
                        )
                    # Transfer the first reference to a different seeded location.
                    location_select = rows.first.get_by_label(
                        "Localização após inventário", exact=True
                    )
                    options = location_select.locator("option").evaluate_all(
                        "nodes => nodes.map(n => n.value).filter(Boolean)"
                    )
                    destination = next(
                        value for value in options if value != location_select.input_value()
                    )
                    location_select.select_option(destination)
                    page.get_by_role(
                        "button", name="Guardar e conferir operação", exact=True
                    ).click()
                    inventory_review = page.url
                    page.locator('[name="confirm"]').check()
                    # Browser stays online while PC/proxy stops responding (health probe failure).
                    page.route("**/ligacao/", lambda route: route.abort())
                    page.evaluate("window.dispatchEvent(new Event('online'))")
                    page.wait_for_function("!document.querySelector('#offline-banner').hidden")
                    assert page.evaluate("navigator.onLine")
                    assert page.get_by_role(
                        "button", name="Confirmar inventário", exact=True
                    ).is_disabled()
                    assert stocks() == [30, 0, 9]
                    page.unroute("**/ligacao/")
                    page.evaluate("window.dispatchEvent(new Event('online'))")
                    page.wait_for_function("document.querySelector('#offline-banner').hidden")
                    # Lose only the response AFTER PostgreSQL has committed. Never replay.
                    context.set_offline(True)
                    page.wait_for_function(
                        "!navigator.onLine && !document.querySelector('#offline-banner').hidden"
                    )
                    assert stocks() == [30, 0, 9]
                    context.set_offline(False)
                    page.goto(inventory_review)
                    page.locator('[name="confirm"]').check()
                    payload = page.locator("form.card").evaluate(
                        "form => Object.fromEntries(new FormData(form))"
                    )

                    # Abort after fetching the request upstream. This simulates a dropped response.
                    def lost_response(route):
                        route.fetch()
                        route.abort()

                    page.route("**/operacoes/*/conferir/", lost_response)
                    # Fetch is explicit here to avoid Chrome's own error-page replacing the harness.
                    result = page.evaluate(
                        "async ({path,data}) => {try {await fetch(path,{method:'POST',body:new URLSearchParams(data)});return 'unexpected';}catch(_){return 'unknown';}}",
                        {"path": inventory_review, "data": payload},
                    )
                    assert result == "unknown"
                    assert stocks() == [29, 0, 9]
                    page.unroute("**/operacoes/*/conferir/")
                    page.goto(inventory_review)
                    assert stocks() == [29, 0, 9]
                    page.evaluate(
                        "async ({path,data}) => fetch(path,{method:'POST',body:new URLSearchParams(data)})",
                        {"path": inventory_review, "data": payload},
                    )
                    assert stocks() == [29, 0, 9]
                    assert json.loads(
                        shell(
                            "import json; from inventory.models import Reference; print(json.dumps(Reference.objects.get(code='SYN-WIN-001').location_id))"
                        ).splitlines()[-1]
                    ) == int(destination)
                    page.goto(url + "/stock/")
                    assert page.evaluate("document.documentElement.scrollWidth") <= 393
                    assert errors == [], errors
                    cached = page.evaluate(
                        "async () => {const paths=[];for(const name of await caches.keys())for(const r of await (await caches.open(name)).keys()) paths.push(new URL(r.url).pathname);return paths;}"
                    )
                    assert cached and all(
                        p == "/offline/" or p.startswith("/static/") for p in cached
                    )
                    page.get_by_role("button", name="Sair", exact=True).click()
                    login("wifi-synthetic-viewer")
                    for path in ("/entradas/", "/saidas/", "/inventario/", "/referencias/"):
                        response = page.goto(url + path)
                        assert response.status == 403
                    browser.close()
            finally:
                if old_ca is None:
                    os.environ.pop("NODE_EXTRA_CA_CERTS", None)
                else:
                    os.environ["NODE_EXTRA_CA_CERTS"] = old_ca
                for key, value in old_no_proxy.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            print(
                "PASS Wi-Fi synthetic: trusted TLS/mTLS + revoked/absent device rejection + allowlist + HTTPS CSRF + Android PWA/entry/signed-exit/PDF/inventory/transfer + network failure/retry + viewer permissions",
                flush=True,
            )
        finally:
            if command:
                run(command + ["down", "--volumes", "--remove-orphans"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    main(parser.parse_args().image)
