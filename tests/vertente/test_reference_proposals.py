import json
import uuid

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase

from consultation.review import confirm_sheet, correct_sheet, review_sheet
from consultation.sheets import receive_sheet
from inventory.models import Location, Movement, Reference
from tests.vertente import test_offline_sheets as offline
from tests.vertente.browser import VertenteBrowserBase
from tests.vertente.fixtures import wait_offline_shell


class OfflineProposalBrowserTests(
    offline.SheetBrowserMixin, VertenteBrowserBase, TransactionTestCase
):
    databases = {"default"}
    database_reception = True
    browser_per_test = True

    def verify_received(self, wire):
        self.context.close()
        self.stop_browser()
        admin = get_user_model().objects.create_user(
            username="synthetic-proposal-office", role="admin"
        )
        location = Location.objects.create(name="Localização fictícia aprovada")
        receipt = receive_sheet(json.dumps(wire).encode(), actor=admin)
        self.assertEqual(Reference.objects.count(), 0)
        self.assertEqual(Movement.objects.count(), 0)
        payload = receipt.sheet.payload
        line = payload["lines"][0]
        corrected = {
            **line,
            "proposal": {**line["proposal"], "location_id": location.pk, "sector_id": None},
        }
        correction = correct_sheet(
            receipt.sheet_id,
            actor=admin,
            sequence=0,
            reason="Aprovação da proposta offline",
            values={
                **{k: payload[k] for k in ("person", "physical_date", "notes")},
                "lines": [corrected],
            },
        )
        review, _ = review_sheet(receipt.sheet_id, actor=admin, sequence=correction.sequence)
        self.assertEqual(Reference.objects.count(), 0)
        result = confirm_sheet(
            receipt.sheet_id,
            actor=admin,
            sequence=review.sequence,
            token=review.data["token"],
            confirmed=True,
            report_requested=True,
        )
        self.assertEqual(Reference.objects.get().current_stock, 8)
        self.assertEqual(result.lines.get().boxes, 1)
        self.assertEqual(receive_sheet(json.dumps(wire).encode(), actor=admin).outcome, "duplicate")

    def test_employee_mobile_proposes_offline_without_codes_or_locations_and_office_confirms(self):
        self.provision_sheets("employee")
        wait_offline_shell(self.page)
        self.context.set_offline(True)
        self.page.get_by_role("button", name="Preparar folhas", exact=True).click()
        self.page.get_by_role("button", name="Preparar entrada", exact=True).click()
        self.page.get_by_label("Quem entregou", exact=True).fill("Pessoa fictícia Daniel")
        self.page.get_by_text("Propor nova referência", exact=True).click()
        self.page.get_by_label("Designação a propor", exact=True).fill(
            "Nova proposta offline fictícia"
        )
        self.page.get_by_label("Garrafas por caixa (se conhecida)", exact=True).fill("6")
        self.page.get_by_role("button", name="Adicionar proposta de referência", exact=True).click()
        self.assertEqual(self.page.get_by_label("Caixas", exact=True).input_value(), "")
        self.assertEqual(self.page.get_by_label("Garrafas soltas", exact=True).input_value(), "")
        self.page.get_by_label("Caixas", exact=True).fill("1")
        self.page.get_by_label("Garrafas soltas", exact=True).fill("2")
        self.assertEqual(
            self.page.locator('select[name$="location"], input[name="code"]').count(), 0
        )
        self.page.get_by_role("button", name="Guardar rascunho", exact=True).click()
        self.page.get_by_role("status").filter(has_text="Rascunho guardado").wait_for()
        self.page.reload()
        self.sheets("unlockSheets", self.password)
        saved = self.sheets("sheetState")["sheets"][0]
        self.assertEqual(saved["lines"][0]["proposal"]["name"], "Nova proposta offline fictícia")
        wire = self.sheets("exportSheet", saved["id"], saved["revision"])
        self.assertEqual(wire["version"], 2)
        self.assertNotIn("Pessoa fictícia", json.dumps(wire))
        self.verify_received(wire)

    def test_owner_vault_backup_legacy_file_unknown_capacity_and_exit_rejection(self):
        self.provision_sheets("owner")
        identity = "proposal:" + str(uuid.uuid4())
        row = {
            "reference_id": identity,
            "boxes": 1,
            "units": 2,
            "proposal": {"name": "Proposta fictícia de Fábio", "box_capacity": 6},
        }
        id = self.new_sheet(lines=[row])
        backup = self.sheets("backupSheets", self.password)
        self.sheets("restoreSheets", backup, self.password)
        wire = self.sheets("exportSheet", id, 2)
        self.assertEqual(self.sheets("exportSheet", id, 2), wire)
        with self.assertRaises(Exception):
            self.new_sheet("exit", lines=[row])
        legacy = self.new_sheet(lines=[{"reference_id": "1", "boxes": None, "units": 2}])
        self.assertEqual(self.sheets("exportSheet", legacy, 2)["version"], 1)
        self.verify_received(wire)
