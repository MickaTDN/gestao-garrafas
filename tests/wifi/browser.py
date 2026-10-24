"""Network-loss UX, with synthetic fixtures and no browser persistence of writes."""

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.urls import reverse

from inventory.models import Movement
from tests import browser as fixtures


class WifiConnectivityBrowserTests(StaticLiveServerTestCase):
    database_call = staticmethod(fixtures.OperationalBrowserTests.database_call)
    setUp = fixtures.OperationalBrowserTests.setUp
    page = fixtures.OperationalBrowserTests.page
    stocks = fixtures.OperationalBrowserTests.stocks

    def review(self):
        page = self.page("entry", 393)
        page.evaluate("async () => { await navigator.serviceWorker.ready; }")
        page.reload()
        page.wait_for_function("navigator.serviceWorker.controller !== null")
        page.get_by_role("button", name="Criar rascunho", exact=True).click()
        page.get_by_label("Adicionar SYN-OP-1", exact=True).check()
        page.get_by_role("button", name="Adicionar selecionadas e guardar", exact=True).click()
        page.get_by_label("Pessoa que entregou / levantou", exact=True).fill(
            "Pessoa Wi-Fi fictícia"
        )
        page.get_by_label("Garrafas soltas", exact=True).fill("2")
        page.get_by_role("button", name="Guardar e conferir operação", exact=True).click()
        page.locator('[name="report_requested"]').select_option("no")
        page.locator('[name="confirm"]').check()
        return page

    def test_server_unreachable_while_browser_stays_online_blocks_write(self):
        page = self.review()
        page.context.route("**/ligacao/", lambda route: route.abort())
        page.evaluate("window.dispatchEvent(new Event('online'))")
        page.wait_for_function("!document.querySelector('#offline-banner').hidden")
        self.assertTrue(page.evaluate("navigator.onLine"))
        self.assertTrue(
            page.get_by_role("button", name="Confirmar entrada", exact=True).is_disabled()
        )
        self.assertEqual(self.stocks(), [15, 5])
        self.assertEqual(self.database_call(lambda: Movement.objects.get().status), "draft")
        page.context.unroute("**/ligacao/")
        page.evaluate("window.dispatchEvent(new Event('online'))")
        page.wait_for_function("document.querySelector('#offline-banner').hidden")
        page.get_by_role("button", name="Confirmar entrada", exact=True).click()
        self.assertIn("CONFIRMADO", page.locator("body").inner_text())
        self.assertEqual(self.stocks(), [17, 5])

    def test_failed_native_post_shows_unknown_result_without_replay(self):
        page = self.review()
        review_url = page.url
        requests = []

        def abort(route):
            requests.append(route.request.method)
            route.abort()

        page.context.route("**/operacoes/*/conferir/", abort)
        page.get_by_role("button", name="Confirmar entrada", exact=True).click()
        page.get_by_role("heading", name="Sem ligação", exact=True).wait_for()
        self.assertIn("resultado é desconhecido", page.locator("body").inner_text())
        self.assertNotIn("CONFIRMADO", page.locator("body").inner_text())
        self.assertEqual(requests, ["POST"])
        self.assertEqual(self.stocks(), [15, 5])
        page.context.unroute("**/operacoes/*/conferir/")
        page.goto(self.live_server_url + reverse("web:drafts"))
        self.assertEqual(self.database_call(lambda: Movement.objects.get().status), "draft")
        page.goto(review_url)
        page.locator('[name="report_requested"]').select_option("no")
        page.locator('[name="confirm"]').check()
        page.get_by_role("button", name="Confirmar entrada", exact=True).click()
        self.assertIn("CONFIRMADO", page.locator("body").inner_text())
        self.assertEqual(self.stocks(), [17, 5])
