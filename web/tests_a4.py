from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from inventory import operations
from inventory.models import AuditEvent, Location, Movement, Reference, Sector
from web import tests_operations as operation_helpers
from web.tests_a2 import DetailsParser


class InventoryWorklistTests(TestCase):
    payload = staticmethod(operation_helpers.OperationWebTests.payload)

    def setUp(self):
        self.actor = get_user_model().objects.create_user(
            username="a4-worklist-admin", role="admin"
        )
        self.location = Location.objects.create(name="Armazém A4 fictício")
        self.other = Location.objects.create(name="Outro armazém A4 fictício")
        self.sectors = {
            name: Sector.objects.create(name="Setor " + name, location=self.location)
            for name in ("1", "2", "9", "10")
        }
        self.first = Reference.objects.create(
            code="A4-WORK-1",
            name="Azul A4 fictícia",
            location=self.location,
            sector=self.sectors["9"],
            current_stock=12,
            box_capacity=6,
        )
        self.second = Reference.objects.create(
            code="A4-WORK-2",
            name="Verde A4 fictícia",
            location=self.location,
            sector=self.sectors["10"],
            current_stock=6,
            box_capacity=6,
        )
        self.unknown = Reference.objects.create(
            code="A4-WORK-3", name="Sem setor A4 fictícia", location=self.location
        )
        self.foreign = Reference.objects.create(
            code="A4-WORK-4", name="Azul noutro local A4 fictícia", location=self.other
        )
        self.client.force_login(self.actor)

    def new(self):
        url = reverse("web:inventory")
        response = self.client.get(url, {"location": self.location.pk})
        data = self.payload(response)
        data.update(action=f"add:{self.first.pk}", search_q="")
        response = self.client.post(url + f"?location={self.location.pk}", data)
        self.assertEqual(response.status_code, 302)
        return Movement.objects.latest("pk"), response.url

    def test_location_search_shows_all_references_with_sector_and_numeric_order(self):
        response = self.client.get(
            reverse("web:inventory"), {"location": self.location.pk, "partial": "references"}
        )
        self.assertEqual(
            [ref.pk for ref in response.context["refs_page"]],
            [self.first.pk, self.second.pk, self.unknown.pk],
        )
        self.assertContains(response, "Setor 9")
        self.assertContains(response, "Setor 10")
        self.assertContains(response, "Sem setor definido")
        self.assertNotContains(response, self.location.name)
        self.assertNotContains(response, self.foreign.name)
        self.assertFalse(Movement.objects.exists())

    def test_name_search_without_location_shows_configured_location_and_sector(self):
        response = self.client.get(reverse("web:inventory"), {"q": "AZUL", "partial": "references"})
        self.assertContains(response, self.first.name)
        self.assertContains(response, self.foreign.name)
        self.assertContains(response, self.location.name)
        self.assertContains(response, self.other.name)
        self.assertContains(response, "Setor 9")
        self.assertContains(response, "Sem setor definido")

    def test_direct_add_preserves_location_and_focuses_only_new_count_without_stock(self):
        draft, url = self.new()
        self.assertIn("location=" + str(self.location.pk), url)
        line = draft.lines.get()
        self.assertIn("focus=" + str(line.pk), url)
        response = self.client.get(url)
        row = next(
            item
            for item in DetailsParser(response.content.decode()).details
            if "operation-line" in item.get("class", "")
        )
        self.assertIn("open", row)
        self.assertIsNone(line.counted_quantity)
        self.assertContains(response, "Ainda não contado")
        self.assertEqual(Reference.objects.get(pk=self.first.pk).current_stock, 12)

    def test_count_minimizes_with_visible_name_sector_quantity_and_keeps_whole_worklist(self):
        draft, url = self.new()
        line = draft.lines.get()
        response = self.client.get(url)
        data = self.payload(response)
        data.update(
            {"form-0-boxes": 2, "form-0-units": "", "search_q": "", "action": f"check:{line.pk}"}
        )
        response = self.client.post(url.split("#")[0], data)
        self.assertEqual(response.status_code, 302)
        self.assertIn("location=" + str(self.location.pk), response.url)
        self.assertNotIn("focus=", response.url)
        response = self.client.get(response.url)
        row = next(
            item
            for item in DetailsParser(response.content.decode()).details
            if "operation-line" in item.get("class", "")
        )
        self.assertNotIn("open", row)
        self.assertContains(response, "Setor 9")
        self.assertContains(response, "2 caixas")
        self.assertContains(response, 'data-open-line="' + str(line.pk) + '"')
        self.assertEqual(response.context["refs_page"].paginator.count, 3)
        self.assertEqual(draft.lines.count(), 1)
        self.assertEqual(Reference.objects.get(pk=self.first.pk).current_stock, 12)

    def test_reopening_selected_reference_is_read_only_and_repeated_add_is_rejected(self):
        draft, url = self.new()
        line = draft.lines.get()
        before = AuditEvent.objects.count()
        self.client.get(url)
        fragment = self.client.get(
            reverse("web:operation-edit", args=[draft.pk]),
            {"location": self.location.pk, "partial": "references"},
        )
        self.assertContains(fragment, 'data-open-line="' + str(line.pk) + '"')
        self.assertContains(fragment, self.first.name)
        self.assertEqual(AuditEvent.objects.count(), before)
        data = self.payload(self.client.get(url))
        data.update(action=f"add:{self.first.pk}", search_q="")
        self.assertEqual(self.client.post(url.split("#")[0], data).status_code, 400)
        self.assertEqual(draft.lines.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), before)

    def test_full_worklist_initially_collapsed_and_zero_different_from_unknown_after_clear(self):
        draft = operations.create_draft(
            actor=self.actor,
            kind="inventory",
            inventory_scope="full",
            references=[self.first, self.second, self.unknown],
        )
        url = reverse("web:operation-edit", args=[draft.pk])
        response = self.client.get(url, {"location": self.location.pk})
        details = [
            item
            for item in DetailsParser(response.content.decode()).details
            if "operation-line" in item.get("class", "")
        ]
        self.assertEqual(len(details), 3)
        self.assertTrue(all("open" not in item for item in details))
        data = self.payload(response)
        line = draft.lines.get(reference=self.first)
        data.update(
            {
                "form-0-units": 0,
                "form-0-reason": "Contagem zero A4 fictícia",
                "action": f"check:{line.pk}",
                "search_q": "",
            }
        )
        self.assertEqual(
            self.client.post(url + f"?location={self.location.pk}", data).status_code, 302
        )
        line.refresh_from_db()
        self.assertEqual(line.counted_quantity, 0)
        response = self.client.get(url, {"location": self.location.pk})
        self.assertContains(response, "0 garrafas")
        data = self.payload(response)
        data.update(action=f"clear:{line.pk}", search_q="")
        self.assertEqual(
            self.client.post(url + f"?location={self.location.pk}", data).status_code, 302
        )
        line.refresh_from_db()
        self.assertIsNone(line.counted_quantity)
        self.assertEqual(draft.lines.count(), 3)
        self.assertContains(self.client.get(url), "Ainda não contado")
        self.assertEqual(Reference.objects.get(pk=self.first.pk).current_stock, 12)

    def test_pagination_and_search_preserve_saved_counts_and_link_to_correct_count_page(self):
        references = [self.first, self.second, self.unknown] + [
            Reference.objects.create(
                code=f"A4-PAGE-{i}",
                name=f"Garrafa A4 página {i:02}",
                location=self.location,
                sector=self.sectors["2"],
            )
            for i in range(32)
        ]
        draft = operations.create_draft(actor=self.actor, kind="inventory", references=references)
        line = draft.lines.get(reference=self.first)
        draft = operations.save_draft(
            draft.pk,
            actor=self.actor,
            revision=0,
            header={},
            rows=[
                {
                    "id": line.pk,
                    "units": 12,
                    "target_location": self.location,
                    "target_sector": self.sectors["9"],
                }
            ],
            check_ids=[line.pk],
        )
        url = reverse("web:operation-edit", args=[draft.pk])
        before = AuditEvent.objects.count()
        for query in (
            {"q": self.first.name, "partial": "references"},
            {"location": self.location.pk, "ref_page": 2, "partial": "references"},
            {"location": self.location.pk, "page": 2},
        ):
            self.assertEqual(self.client.get(url, query).status_code, 200)
        fragment = self.client.get(url, {"q": self.first.name, "partial": "references"})
        self.assertContains(fragment, "page=2")
        self.assertContains(fragment, "12 garrafas")
        self.assertEqual(draft.lines.get(pk=line.pk).counted_quantity, 12)
        self.assertEqual(AuditEvent.objects.count(), before)
        self.assertEqual(draft.lines.count(), 35)


class ConfirmationNumberWebTests(TestCase):
    def test_no_pdf_entry_confirmation_message_detail_and_history_use_assigned_number(self):
        actor = get_user_model().objects.create_user(username="a4-confirmation-web", role="admin")
        location = Location.objects.create(name="Local confirmação A4 fictício")
        reference = Reference.objects.create(
            code="A4-CONFIRM", name="Garrafa confirmação fictícia", location=location
        )
        self.client.force_login(actor)
        draft = operations.create_draft(actor=actor, kind="entry", references=[reference])
        draft = operations.save_draft(
            draft.pk,
            actor=actor,
            revision=0,
            header={"person_name": "Cliente fictício"},
            rows=[{"id": draft.lines.get().pk, "units": 2}],
        )
        reviewed, _ = operations.review_draft(draft.pk, actor=actor, revision=draft.revision)
        response = self.client.post(
            reverse("web:operation-review", args=[draft.pk]),
            {"token": reviewed.review_token, "report_requested": "no", "confirm": "on"},
            follow=True,
        )
        official = str(Movement.objects.get(pk=draft.pk).report_number)
        self.assertContains(response, official)
        self.assertContains(response, "confirmada")
        self.assertFalse(draft.documents.exists())
        self.assertContains(self.client.get(reverse("web:history")), official)
        self.assertNotContains(
            self.client.get(reverse("web:reports")),
            reverse("web:operation-detail", args=[draft.pk]),
        )
