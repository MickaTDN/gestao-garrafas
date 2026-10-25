import io
from datetime import datetime
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from pypdf import PdfReader

from inventory import operations
from inventory.documents import store_document, verified_bytes
from inventory.models import (
    Location,
    Movement,
    Reference,
    ReportNumber,
    ReportSequence,
    Sector,
)
from inventory.reporting import delete_pdf, regenerate_pdf
from inventory.services import confirm_movement
from tests.document_fixtures import confirmed_operation, signature_png
from web import tests_operations as operation_helpers
from web.operation_forms import InventorySearchForm
from web.tests_a2 import DetailsParser


class NumberPresentationTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(username="a3-number-admin", role="admin")
        self.location = Location.objects.create(name="Local numeração fictício")
        self.ref = Reference.objects.create(
            code="A3-NUM",
            name="Garrafa numeração fictícia",
            location=self.location,
            current_stock=30,
            box_capacity=6,
        )
        self.client.force_login(self.admin)

    def test_draft_has_preparation_state_and_explicit_technical_identifier(self):
        draft = operations.create_draft(actor=self.admin, kind="entry", references=[self.ref])
        response = self.client.get(reverse("web:operation-edit", args=[draft.pk]))
        self.assertContains(response, "Em preparação")
        self.assertContains(response, f"ID técnico {draft.pk}")
        self.assertNotContains(response, f"Mov-{draft.pk}/")
        self.assertFalse(ReportNumber.objects.exists())

    def test_official_number_is_looked_up_and_not_derived_from_movement_pk(self):
        for _ in range(3):
            operations.create_draft(actor=self.admin, kind="entry")
        movement = confirmed_operation(self.admin, self.ref)
        official = str(movement.report_number)
        self.assertNotEqual(movement.pk, movement.report_number.number)
        for route in ("web:operation-detail", "web:history", "web:reports"):
            url = reverse(route, args=[movement.pk]) if route.endswith("detail") else reverse(route)
            response = self.client.get(url)
            self.assertContains(response, official)
            self.assertNotContains(response, f"<h1>MOV-{movement.pk}")
        pdf = movement.documents.get(kind="pdf")
        text = "".join(
            page.extract_text() for page in PdfReader(io.BytesIO(verified_bytes(pdf))).pages
        )
        self.assertIn(official, text)
        self.assertEqual(ReportSequence.objects.get(year=movement.date.year).last_number, 1)

    def test_entry_without_report_and_legacy_document_keep_technical_identity(self):
        movement = confirmed_operation(self.admin, self.ref, kind="entry", report=False)
        self.assertIn("Identificador técnico MOV-", str(movement))
        self.assertFalse(ReportNumber.objects.exists())
        historical = Movement.objects.create(kind="exit", created_by=self.admin)
        document = store_document(
            historical,
            kind="pdf",
            payload=b"%PDF-a3-synthetic-legacy",
            metadata={"presentation": 2},
        )
        historical.status = "confirmed"
        historical.save()
        for _ in range(2):
            self.assertContains(
                self.client.get(reverse("web:operation-detail", args=[historical.pk])),
                f"Identificador técnico MOV-{historical.pk}",
            )
        self.assertEqual(document.number, f"MOV-{historical.pk}")
        self.assertEqual(verified_bytes(document), b"%PDF-a3-synthetic-legacy")
        self.assertFalse(ReportNumber.objects.exists())

    def test_number_survives_file_deletion_regeneration_and_new_year(self):
        with patch(
            "django.utils.timezone.now",
            return_value=datetime(2026, 6, 15, 12, tzinfo=dt_timezone.utc),
        ):
            movement = confirmed_operation(self.admin, self.ref)
        pdf = movement.documents.get(kind="pdf")
        original = verified_bytes(pdf)
        delete_pdf(actor=self.admin, document_id=pdf.pk)
        self.assertContains(
            self.client.get(reverse("web:operation-detail", args=[movement.pk])), "Mov-1/26"
        )
        with patch(
            "django.utils.timezone.now",
            return_value=datetime(2027, 6, 15, 12, tzinfo=dt_timezone.utc),
        ):
            later = confirmed_operation(self.admin, self.ref, kind="entry", report=True)
        regenerate_pdf(actor=self.admin, document_id=pdf.pk)
        self.assertEqual(verified_bytes(pdf), original)
        self.assertEqual(str(movement), "Mov-1/26 · Saída")
        self.assertEqual(str(later), "Mov-1/27 · Entrada")
        self.assertEqual(
            list(ReportSequence.objects.order_by("year").values_list("last_number", flat=True)),
            [1, 1],
        )


class InventoryUsabilityTests(TestCase):
    payload = staticmethod(operation_helpers.OperationWebTests.payload)

    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username="a3-inventory-admin", role="admin"
        )
        self.location = Location.objects.create(name="Local inventário A3 fictício")
        self.destination = Location.objects.create(name="Outro local inventário A3 fictício")
        self.sectors = {
            name: Sector.objects.create(location=self.location, name=name)
            for name in ("1", "2", "9", "10", "Especial")
        }
        self.destination_sector = Sector.objects.create(location=self.destination, name="3")
        self.refs = {
            name: Reference.objects.create(
                code="A3-INV-" + str(i),
                name=name + " fictícia",
                location=self.location,
                sector=self.sectors.get(sector),
                current_stock=12,
                box_capacity=6,
            )
            for i, (name, sector) in enumerate(
                [
                    ("Zeta", "1"),
                    ("Beta", "2"),
                    ("Alfa", "2"),
                    ("Nove", "9"),
                    ("Dez", "10"),
                    ("Especial", "Especial"),
                    ("Sem setor", None),
                ]
            )
        }
        self.client.force_login(self.admin)

    def draft(self, full=False, refs=None):
        return operations.create_draft(
            actor=self.admin,
            kind="inventory",
            inventory_scope="full" if full else "partial",
            references=refs if refs is not None else [self.refs["Alfa"]],
        )

    def edit(self, draft, **changes):
        url = reverse("web:operation-edit", args=[draft.pk])
        data = self.payload(self.client.get(url))
        data.update(changes)
        return self.client.post(url, data)

    def test_numeric_order_in_search_full_scope_and_count_navigation(self):
        expected = ["Zeta", "Alfa", "Beta", "Nove", "Dez", "Especial", "Sem setor"]
        response = self.client.get(reverse("web:inventory"), {"location": self.location.pk})
        self.assertEqual(
            [ref.name.split(" fictícia")[0] for ref in response.context["refs_page"]], expected
        )
        form = response.context["filter_form"]
        self.assertEqual(
            [
                sector.name
                for sector in form.fields["sector"].queryset
                if sector.location_id == self.location.pk
            ],
            ["1", "2", "9", "10", "Especial"],
        )
        draft = self.draft(full=True, refs=list(self.refs.values()))
        response = self.client.get(reverse("web:operation-edit", args=[draft.pk]))
        self.assertEqual(
            [line.reference.name.split(" fictícia")[0] for line, form in response.context["pairs"]],
            expected,
        )
        filtered = self.client.get(
            reverse("web:operation-edit", args=[draft.pk]), {"sector": self.sectors["2"].pk}
        )
        self.assertEqual(filtered.context["lines_page"].paginator.count, 2)
        self.assertEqual(draft.lines.count(), 7)

    def test_search_matches_name_not_code_and_direct_selection_has_empty_counts(self):
        url = reverse("web:inventory")
        self.assertEqual(
            self.client.get(url, {"q": self.refs["Alfa"].code})
            .context["refs_page"]
            .paginator.count,
            0,
        )
        response = self.client.get(url, {"q": "ALFA"})
        self.assertContains(response, 'name="action" value="add:')
        self.assertNotContains(response, 'type="checkbox" name="add_reference"')
        data = self.payload(response)
        data.update(action=f"add:{self.refs['Alfa'].pk}", search_q="ALFA")
        self.assertEqual(self.client.post(url + "?q=ALFA", data).status_code, 302)
        draft = Movement.objects.latest("pk")
        line = draft.lines.get()
        self.assertEqual(
            (line.boxes, line.units, line.counted_quantity, line.quantity_checked),
            (None, None, None, False),
        )
        self.assertEqual(self.refs["Alfa"].current_stock, 12)

    def test_zero_count_is_confirmed_minimized_and_can_be_edited_and_removed_without_stock(self):
        draft = self.draft()
        line = draft.lines.get()
        response = self.edit(
            draft,
            **{
                "form-0-units": 0,
                "form-0-reason": "Zero físico fictício",
                "action": f"check:{line.pk}",
            },
        )
        self.assertEqual(response.status_code, 302)
        line.refresh_from_db()
        self.assertEqual((line.counted_quantity, line.quantity_checked), (0, True))
        response = self.client.get(reverse("web:operation-edit", args=[draft.pk]))
        details = next(
            item
            for item in DetailsParser(response.content.decode()).details
            if "operation-line" in item.get("class", "")
        )
        self.assertNotIn("open", details)
        self.assertContains(response, "0 garrafas")
        self.edit(draft, **{"form-0-units": 1, "form-0-reason": "Ajuste fictício"})
        line.refresh_from_db()
        self.assertFalse(line.quantity_checked)
        self.assertEqual(self.edit(draft, action=f"remove:{line.pk}").status_code, 302)
        self.assertEqual(draft.lines.count(), 0)
        self.assertEqual(Reference.objects.get(pk=self.refs["Alfa"].pk).current_stock, 12)

    def test_blank_count_is_not_zero_and_difference_requires_reason(self):
        draft = self.draft()
        line = draft.lines.get()
        self.assertEqual(self.edit(draft, action=f"check:{line.pk}").status_code, 400)
        self.assertEqual(
            self.edit(draft, **{"form-0-units": 0, "action": f"check:{line.pk}"}).status_code, 400
        )
        line.refresh_from_db()
        self.assertIsNone(line.counted_quantity)
        self.assertEqual(
            self.edit(draft, **{"form-0-units": 12, "action": f"check:{line.pk}"}).status_code, 302
        )
        line.refresh_from_db()
        self.assertTrue(line.quantity_checked)

    def test_partial_search_does_not_filter_away_selected_lines_or_lose_input(self):
        draft = self.draft()
        url = reverse("web:operation-edit", args=[draft.pk])
        response = self.client.get(url, {"q": "Dez", "partial": "references"})
        self.assertContains(response, self.refs["Dez"].name)
        data = self.payload(self.client.get(url, {"q": "Dez"}))
        data.update({"form-0-units": 12, "action": f"add:{self.refs['Dez'].pk}", "search_q": "Dez"})
        self.assertEqual(self.client.post(url + "?q=Dez", data).status_code, 302)
        self.assertEqual(draft.lines.count(), 2)
        self.assertEqual(draft.lines.get(reference=self.refs["Alfa"]).counted_quantity, 12)
        data = self.payload(self.client.get(url, {"q": "Dez"}))
        data.update(action=f"add:{self.refs['Dez'].pk}", search_q="Dez")
        self.assertEqual(self.client.post(url + "?q=Dez", data).status_code, 400)

    def test_full_inventory_cannot_remove_scope_but_can_clear_count_without_zeroing_stock(self):
        draft = self.draft(full=True)
        line = draft.lines.get()
        self.edit(draft, **{"form-0-units": 12, "action": f"check:{line.pk}"})
        self.assertEqual(self.edit(draft, action=f"remove:{line.pk}").status_code, 400)
        self.assertEqual(self.edit(draft, action=f"clear:{line.pk}").status_code, 302)
        line.refresh_from_db()
        self.assertEqual((line.counted_quantity, line.quantity_checked), (None, False))
        self.assertEqual(self.edit(draft, action="review").status_code, 302)
        draft.refresh_from_db()
        self.assertIsNone(draft.review_token)
        self.assertEqual(Reference.objects.get(pk=self.refs["Alfa"].pk).current_stock, 12)

    def test_sector_ownership_rejected_in_search_form_line_form_and_domain(self):
        form = InventorySearchForm(
            {"location": self.location.pk, "sector": self.destination_sector.pk}
        )
        self.assertFalse(form.is_valid())
        draft = self.draft()
        line = draft.lines.get()
        response = self.edit(
            draft,
            **{
                "form-0-units": 12,
                "form-0-target_sector": self.destination_sector.pk,
                "action": f"check:{line.pk}",
            },
        )
        self.assertEqual(response.status_code, 400)
        draft.refresh_from_db()
        with self.assertRaises(ValidationError):
            operations.save_draft(
                draft.pk,
                actor=self.admin,
                revision=draft.revision,
                header={},
                rows=[
                    {
                        "id": line.pk,
                        "units": 12,
                        "target_location": self.location,
                        "target_sector": self.destination_sector,
                    }
                ],
                check_ids=[line.pk],
            )
        self.assertEqual(Reference.objects.get(pk=self.refs["Alfa"].pk).current_stock, 12)

    def test_transfer_and_zero_delta_are_only_applied_at_final_confirmation_with_signature(self):
        draft = self.draft()
        line = draft.lines.get()
        response = self.edit(
            draft,
            **{
                "form-0-units": 12,
                "form-0-target_location": self.destination.pk,
                "form-0-target_sector": self.destination_sector.pk,
                "form-0-reason": "Transferência fictícia",
                "action": f"check:{line.pk}",
            },
        )
        self.assertEqual(response.status_code, 302)
        ref = Reference.objects.get(pk=self.refs["Alfa"].pk)
        self.assertEqual(ref.location_id, self.location.pk)
        draft.refresh_from_db()
        reviewed, _ = operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)
        confirmed = confirm_movement(
            draft.pk,
            actor=self.admin,
            review_token=reviewed.review_token,
            validation="signed",
            signature_data=signature_png(),
        )
        ref.refresh_from_db()
        self.assertEqual((ref.current_stock, ref.location_id), (12, self.destination.pk))
        self.assertEqual(confirmed.lines.get().quantity, 0)
        self.assertTrue(confirmed.documents.filter(kind="signature").exists())
        self.assertTrue(confirmed.documents.filter(kind="pdf").exists())
        self.assertEqual(confirmed.location_changes.count(), 1)

    def test_individual_check_does_not_accept_concurrent_stock_change(self):
        draft = self.draft()
        line = draft.lines.get()
        self.edit(draft, **{"form-0-units": 12, "action": f"check:{line.pk}"})
        Reference.objects.filter(pk=self.refs["Alfa"].pk).update(current_stock=13, stock_version=1)
        self.assertEqual(self.edit(draft, action=f"check:{line.pk}").status_code, 400)
        self.assertEqual(Reference.objects.get(pk=self.refs["Alfa"].pk).current_stock, 13)

    def test_invalid_inventory_signature_rolls_back_stock_location_documents_and_number(self):
        draft = self.draft()
        self.edit(
            draft,
            **{
                "form-0-units": 0,
                "form-0-reason": "Zero fictício",
                "form-0-target_location": self.destination.pk,
                "form-0-target_sector": self.destination_sector.pk,
                "action": "review",
            },
        )
        draft.refresh_from_db()
        with self.assertRaises(ValidationError):
            confirm_movement(
                draft.pk,
                actor=self.admin,
                review_token=draft.review_token,
                validation="signed",
                signature_data=signature_png(blank=True),
            )
        reference = Reference.objects.get(pk=self.refs["Alfa"].pk)
        self.assertEqual((reference.current_stock, reference.location_id), (12, self.location.pk))
        self.assertFalse(draft.documents.exists())
        self.assertFalse(draft.location_changes.exists())
        self.assertFalse(ReportNumber.objects.exists())
