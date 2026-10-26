import secrets
from datetime import datetime, time, timedelta
from html.parser import HTMLParser

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import AccessProfile
from accounts.permissions import SUBSTITUTE
from inventory import operations
from inventory.documents import verified_bytes
from inventory.models import AuditEvent, Location, Movement, Reference, ReportFile, ReportNumber
from tests.document_fixtures import confirmed_operation

from . import tests_operations as helpers


class DetailsParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.details = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "details":
            self.details.append(dict(attrs))


class A2WebTests(TestCase):
    payload = staticmethod(helpers.OperationWebTests.payload)

    def setUp(self):
        self.password = secrets.token_urlsafe(32)
        self.admin = get_user_model().objects.create_user(
            username="a2-web-admin", role="admin", password=self.password
        )
        self.location = Location.objects.create(name="Local web A2 fictício")
        self.ref = Reference.objects.create(
            code="A2-WEB-1",
            name="Azul fictícia A2",
            box_capacity=6,
            current_stock=20,
            location=self.location,
        )
        self.other = Reference.objects.create(
            code="A2-WEB-2", name="Verde fictícia A2", current_stock=0, location=self.location
        )
        self.client.force_login(self.admin)

    def new(self, kind="entry"):
        url = reverse("web:" + kind)
        data = self.payload(self.client.get(url, {"q": self.ref.name}))
        data.update(action=f"add:{self.ref.pk}", search_q=self.ref.name)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        return Movement.objects.latest("pk")

    def edit(self, draft, **changes):
        url = reverse("web:operation-edit", args=[draft.pk])
        data = self.payload(self.client.get(url))
        data.update(changes)
        return self.client.post(url, data)

    def test_entry_exit_search_starts_empty_with_no_checkboxes_or_add_button(self):
        for kind in ("entry", "exit"):
            response = self.client.get(reverse("web:" + kind))
            self.assertEqual(response.context["refs_page"].paginator.count, 0)
            self.assertNotContains(response, self.ref.name)
            self.assertNotContains(response, 'name="add_reference"')
            self.assertNotContains(response, "Adicionar selecionadas e guardar")
            self.assertContains(response, "Pesquisar referência")
            self.assertNotContains(response, 'name="location"')
            self.assertNotContains(response, 'name="sector"')
        self.assertFalse(Movement.objects.exists())

    def test_direct_selection_and_quantity_confirmation_minimize_without_stock_effect(self):
        for kind in ("entry", "exit"):
            draft = self.new(kind)
            line = draft.lines.get()
            self.assertEqual((line.boxes, line.units, line.quantity_checked), (None, None, False))
            response = self.edit(
                draft, **{"form-0-boxes": 1, "form-0-units": 2, "action": f"check:{line.pk}"}
            )
            self.assertEqual(response.status_code, 302)
            line.refresh_from_db()
            self.assertTrue(line.quantity_checked)
            response = self.client.get(reverse("web:operation-edit", args=[draft.pk]))
            details = [
                item
                for item in DetailsParser(response.content.decode()).details
                if "operation-line" in item.get("class", "")
            ]
            self.assertEqual(len(details), 1)
            self.assertNotIn("open", details[0])
            self.assertContains(response, "1 caixa + 2 garrafas")
            self.ref.refresh_from_db()
            self.assertEqual(self.ref.current_stock, 20)

    def test_edit_invalidates_individual_check_and_remove_preserves_stock(self):
        draft = self.new("exit")
        line = draft.lines.get()
        self.edit(draft, **{"form-0-units": 2, "action": f"check:{line.pk}"})
        self.edit(draft, **{"form-0-units": 3})
        line.refresh_from_db()
        self.assertFalse(line.quantity_checked)
        response = self.edit(draft, **{"form-0-units": -3, "action": f"remove:{line.pk}"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(draft.lines.count(), 0)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 20)

    def test_duplicate_or_out_of_search_reference_rejected(self):
        url = reverse("web:entry")
        data = self.payload(self.client.get(url, {"q": self.ref.name}))
        data.update(action=f"add:{self.other.pk}", search_q=self.ref.name)
        self.assertEqual(self.client.post(url, data).status_code, 400)
        self.assertFalse(Movement.objects.exists())
        draft = self.new()
        self.assertEqual(
            self.edit(draft, action=f"add:{self.ref.pk}", search_q=self.ref.name).status_code, 400
        )
        self.assertEqual(draft.lines.count(), 1)

    def test_addition_beyond_first_page_opens_new_line_and_search_preserves_page(self):
        existing = [self.ref] + [
            Reference.objects.create(
                code=f"A2-PAGE-{i}", name=f"Outra fictícia {i:02}", location=self.location
            )
            for i in range(29)
        ]
        draft = operations.create_draft(actor=self.admin, kind="entry", references=existing)
        url = reverse("web:operation-edit", args=[draft.pk])
        data = self.payload(self.client.get(url))
        data.update(action=f"add:{self.other.pk}", search_q=self.other.name)
        response = self.client.post(url, data)
        self.assertRedirects(response, url + "?page=2")
        response = self.client.get(url, {"page": 2})
        self.assertContains(response, self.other.name)
        self.assertContains(response, 'name="page" value="2"')
        fragment = self.client.get(url, {"page": 2, "q": "fictícia", "partial": "references"})
        self.assertIn("page=2", fragment.context["ref_params"])
        data = self.payload(response)
        line = draft.lines.get(reference=self.other)
        data.update({"action": f"check:{line.pk}", "form-0-units": 2})
        self.assertEqual(self.client.post(url + "?page=2", data).status_code, 302)
        line.refresh_from_db()
        self.assertTrue(line.quantity_checked)
        self.assertEqual(draft.lines.count(), 31)
        self.assertEqual(Reference.objects.get(pk=self.other.pk).current_stock, 0)

    def test_invalid_edit_of_checked_quantity_expands_errors_without_saving(self):
        draft = self.new()
        line = draft.lines.get()
        self.edit(draft, **{"form-0-units": 2, "action": f"check:{line.pk}"})
        response = self.edit(draft, **{"form-0-units": -1, "action": f"check:{line.pk}"})
        self.assertEqual(response.status_code, 400)
        row = next(
            item
            for item in DetailsParser(response.content.decode()).details
            if "operation-line" in item.get("class", "")
        )
        self.assertIn("open", row)
        line.refresh_from_db()
        self.assertEqual((line.units, line.quantity_checked), (2, True))

    def test_individual_confirmation_rejects_zero_negative_unknown_boxes_and_insufficient_stock(
        self,
    ):
        draft = self.new("exit")
        line = draft.lines.get()
        for boxes, units in [("", 0), ("", -1), ("", 21)]:
            response = self.edit(
                draft,
                **{"form-0-boxes": boxes, "form-0-units": units, "action": f"check:{line.pk}"},
            )
            self.assertEqual(response.status_code, 400)
            line.refresh_from_db()
            self.assertFalse(line.quantity_checked)
        Reference.objects.filter(pk=self.ref.pk).update(box_capacity=None)
        self.assertEqual(
            self.edit(
                draft, **{"form-0-boxes": 1, "form-0-units": "", "action": f"check:{line.pk}"}
            ).status_code,
            400,
        )
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 20)

    def test_stock_dynamic_fragment_searches_only_name_and_keeps_pagination(self):
        url = reverse("web:stock")
        response = self.client.get(url)
        self.assertEqual(response.context["page_obj"].paginator.count, 2)
        self.assertContains(response, "Criar referência")
        response = self.client.get(
            url, {"q": "AZUL", "partial": "stock", "location": 999, "sector": 999}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertNotContains(response, "Navegação principal")
        self.assertContains(response, self.ref.name)
        self.assertNotContains(response, self.ref.code)
        self.assertEqual(
            self.client.get(url, {"q": self.ref.code}).context["page_obj"].paginator.count, 0
        )

    def test_references_menu_removed_management_accessible_from_stock(self):
        for route in ("home", "stock", "history"):
            response = self.client.get(reverse("web:" + route))
            self.assertNotContains(response, 'href="' + reverse("web:references") + '"')
        stock = self.client.get(reverse("web:stock"))
        self.assertContains(stock, reverse("web:reference-create"))
        self.assertContains(stock, "state=inactive")
        home = self.client.get(reverse("web:home"))
        self.assertNotContains(home, "Operações por concluir")
        self.assertNotContains(home, "Localizações existentes")

    def test_history_initially_collapsed_and_get_never_mutates_audit_or_stock(self):
        movement = confirmed_operation(self.admin, self.ref)
        before = AuditEvent.objects.count()
        response = self.client.get(reverse("web:history"))
        details = [
            item
            for item in DetailsParser(response.content.decode()).details
            if "movement-details" in item.get("class", "")
        ]
        self.assertEqual(len(details), 1)
        self.assertNotIn("open", details[0])
        self.assertContains(response, str(movement.report_number))
        self.assertContains(response, "Regenerar PDF")
        self.assertEqual(AuditEvent.objects.count(), before)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 18)

    def test_delete_requires_confirmation_and_csrf_then_history_regenerates_exact_bytes(self):
        movement = confirmed_operation(self.admin, self.ref, signed=True)
        document = movement.documents.get(kind="pdf")
        original = verified_bytes(document)
        url = reverse("web:document-delete", args=[document.pk])
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.admin)
        self.assertEqual(csrf.get(url).status_code, 200)
        self.assertEqual(csrf.post(url, {"confirm": "yes"}).status_code, 403)
        token = csrf.cookies["csrftoken"].value
        self.assertEqual(csrf.post(url, {"csrfmiddlewaretoken": token}).status_code, 400)
        self.assertEqual(
            csrf.post(url, {"csrfmiddlewaretoken": token, "confirm": "yes"}).status_code, 302
        )
        self.assertIsNone(ReportFile.objects.get(document=document).payload)
        history = self.client.get(reverse("web:history"))
        self.assertContains(history, "Ficheiro PDF eliminado")
        self.assertEqual(
            self.client.post(reverse("web:document-regenerate", args=[document.pk])).status_code,
            302,
        )
        self.assertEqual(verified_bytes(document), original)
        self.assertEqual(ReportNumber.objects.count(), 1)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 18)

    def test_previous_day_http_confirmation_cannot_be_forged(self):
        draft = self.new()
        Movement.objects.filter(pk=draft.pk).update(
            created_at=timezone.make_aware(
                datetime.combine(timezone.localdate() - timedelta(days=1), time(12))
            )
        )
        self.edit(
            draft,
            **{
                "form-0-units": 2,
                "action": "review",
                "created_at": timezone.now().isoformat(),
                "date": timezone.localdate().isoformat(),
            },
        )
        draft.refresh_from_db()
        response = self.client.get(reverse("web:operation-edit", args=[draft.pk]))
        self.assertContains(response, "outro dia")
        response = self.client.post(
            reverse("web:operation-review", args=[draft.pk]),
            {"token": draft.review_token, "report_requested": "yes", "confirm": "on"},
        )
        self.assertContains(response, "outro dia", status_code=400)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 20)
        self.assertFalse(ReportNumber.objects.exists())

    def test_admin_creates_profile_and_assigns_account_through_real_forms(self):
        response = self.client.post(
            reverse("web:profile-create"),
            {
                "name": "Férias fictícias",
                "active": "on",
                "capabilities": SUBSTITUTE,
                "current_password": self.password,
                "reason": "Teste fictício",
                "confirm": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        profile = AccessProfile.objects.get(name="Férias fictícias")
        password = secrets.token_urlsafe(32)
        response = self.client.post(
            reverse("web:user-create"),
            {
                "username": "a2-form-account",
                "role": "custom",
                "access_profile": profile.pk,
                "password1": password,
                "password2": password,
                "current_password": self.password,
            },
        )
        self.assertEqual(response.status_code, 302)
        account = get_user_model().objects.get(username="a2-form-account")
        self.assertEqual(account.access_profile_id, profile.pk)
        self.assertEqual(account.role, "custom")
