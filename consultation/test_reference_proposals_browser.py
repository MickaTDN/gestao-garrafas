import os
import re
import secrets
import shutil

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import sync_playwright

from consultation import test_reference_proposals as fixtures
from inventory.models import Reference
from tests import browser as base_browser


@override_settings(ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"])
class ProposalOfficeBrowserTests(fixtures.ProposalFixtures, StaticLiveServerTestCase):
    database_call = staticmethod(base_browser.BrowserSmokeTests.database_call)

    def setUp(self):
        self.prepare_transport()
        self.password = secrets.token_urlsafe(32)
        self.admin.set_password(self.password)
        self.admin.save(update_fields=["password"])
        self.pw = sync_playwright().start()
        self.addCleanup(self.pw.stop)
        self.browser = self.pw.chromium.launch(
            executable_path=os.getenv("CHROMIUM_PATH") or shutil.which("chromium"),
            headless=True,
            args=["--no-sandbox"],
        )
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page(viewport={"width": 390, "height": 844})
        self.page.set_default_timeout(10000)
        self.page.goto(self.live_server_url + reverse("login"))
        self.page.locator('input[name="username"]').fill(self.admin.username)
        self.page.locator('input[name="password"]').fill(self.password)
        self.page.get_by_role("button", name="Entrar", exact=True).click()
        self.page.wait_for_url(self.live_server_url + "/")

    def test_pending_proposal_mobile_location_review_and_confirmation(self):
        sheet = self.database_call(self.received_proposal)
        self.page.goto(self.live_server_url + reverse("web:sheet-process", args=[sheet.pk]))
        self.page.get_by_text("Corrigir a versão de trabalho (exige motivo)", exact=True).click()
        self.page.locator('select[name="lines-1-proposal_location"]').select_option(
            str(self.ref.location_id)
        )
        self.page.locator('textarea[name="correction-reason"]').fill(
            "Localização conferida pela administração"
        )
        self.page.get_by_role("button", name="Guardar correção com motivo", exact=True).click()
        self.page.get_by_role("button", name="Conferir folha", exact=True).click()
        self.page.get_by_role(
            "heading", name="Confirmação oficial explícita", exact=True
        ).wait_for()
        self.assertEqual(self.database_call(lambda: Reference.objects.count()), 1)
        self.page.locator('select[name="report_requested"]').select_option("yes")
        self.page.locator('input[name="confirm"]').check()
        self.page.get_by_role("button", name="Confirmar movimento oficial", exact=True).click()
        self.page.get_by_role("link", name="Abrir PDF oficial", exact=True).wait_for()
        self.assertEqual(self.database_call(lambda: Reference.objects.count()), 2)
        self.page.reload()
        self.assertEqual(self.database_call(lambda: Reference.objects.count()), 2)

    def test_direct_entry_mobile_adds_quantities_without_catalogue_creation_first(self):
        self.page.goto(self.live_server_url + reverse("web:entry"))
        self.page.get_by_role("button", name="Criar nova referência", exact=True).click()
        self.page.get_by_label("Designação", exact=True).fill("Referência direta browser fictícia")
        self.page.get_by_label("Garrafas por caixa", exact=True).fill("6")
        self.page.get_by_label("Localização", exact=True).select_option(str(self.ref.location_id))
        self.page.get_by_label("Caixas recebidas", exact=True).fill("1")
        self.page.get_by_label("Garrafas soltas recebidas", exact=True).fill("2")
        self.page.get_by_role(
            "button", name="Adicionar nova referência à entrada", exact=True
        ).click()
        self.assertEqual(self.database_call(lambda: Reference.objects.count()), 1)
        self.page.get_by_label("Pessoa que entregou", exact=True).fill("Pessoa fictícia direta")
        self.page.get_by_role("button", name="Guardar e conferir operação", exact=True).click()
        self.page.get_by_role(
            "heading",
            name="Nova referência a aprovar · Referência direta browser fictícia",
            exact=True,
        ).wait_for()
        self.page.locator('select[name="report_requested"]').select_option("yes")
        self.page.locator('input[name="confirm"]').check()
        self.page.get_by_role("button", name="Confirmar entrada", exact=True).click()
        self.page.wait_for_url(re.compile(r"/operacoes/\d+/$"))
        self.assertEqual(self.database_call(lambda: Reference.objects.count()), 2)
        self.assertEqual(
            self.database_call(
                lambda: (
                    Reference.objects.get(name="Referência direta browser fictícia").current_stock
                )
            ),
            8,
        )
