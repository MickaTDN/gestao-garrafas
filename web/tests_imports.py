import io
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase
from django.urls import reverse

from imports.reconciliation import build_preview, publish_preview
from imports.tests.test_excel import synthetic_workbook
from inventory.models import ImportBatch, ImportPreview, Movement, Reference


class ImportConfirmationTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-reconciled-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        workbook = synthetic_workbook(self.directory / "synthetic.xlsx")
        call_command("inspect_stock_excel", workbook, stage=True,
                     report=str(self.directory / "inspection.json"), stdout=io.StringIO())
        self.batch = ImportBatch.objects.get()
        self.admin = get_user_model().objects.create_user(username="synthetic-import-admin", role="admin")
        self.viewer = get_user_model().objects.create_user(username="synthetic-import-reader", role="viewer")
        self.decisions = {
            "schema_version": 1, "expected_total": 12, "expected_references": 1,
            "blank_opening_policy": "unknown_derived", "annotations": {}, "document_headers": {},
        }
        self.preview = build_preview(self.batch.pk, self.decisions, actor=self.admin)
        self.url = reverse("web:import-preview", args=[self.preview.pk])
        self.publish_url = reverse("web:import-publish", args=[self.preview.pk])
        self.client.force_login(self.admin)

    def confirmation(self, **overrides):
        return {"confirmation_token": str(self.preview.confirmation_token),
                "confirm": "on", "total": 12, **overrides}

    def test_preview_and_download_do_not_publish_and_are_private(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Stock ainda não publicado")
        self.assertContains(response, "REFERÊNCIA FICTÍCIA ALFA")
        self.assertIn("no-store", response.headers["Cache-Control"])
        report = self.client.get(reverse("web:import-report", args=[self.preview.pk]))
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()["summary"]["total_stock"], 12)
        self.assertFalse(report.json()["published"])
        self.assertIn("attachment", report.headers["Content-Disposition"])
        self.assertFalse(Reference.objects.exists())
        self.assertFalse(Movement.objects.exists())

    def test_guest_and_consultation_cannot_read_or_publish_imports(self):
        for client, status in [(Client(), 302), (self.client, 403)]:
            if client is self.client:
                client.force_login(self.viewer)
            for url in (self.url, reverse("web:import-list"),
                        reverse("web:import-report", args=[self.preview.pk])):
                self.assertEqual(client.get(url).status_code, status)
            self.assertEqual(client.post(self.publish_url, self.confirmation()).status_code, status)
        self.assertFalse(Reference.objects.exists())

    def test_publication_requires_post_checkbox_total_and_correct_token(self):
        self.assertEqual(self.client.get(self.publish_url).status_code, 405)
        for data in [self.confirmation(confirm=""), self.confirmation(total=99),
                     self.confirmation(confirmation_token=str(uuid4()))]:
            with self.subTest(data_keys=list(data)):
                self.assertEqual(self.client.post(self.publish_url, data).status_code, 400)
                self.assertFalse(Reference.objects.exists())

    def test_csrf_is_required_even_for_an_administrator(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.publish_url, self.confirmation()).status_code, 403)
        self.assertFalse(Reference.objects.exists())

    def test_explicit_confirmation_publishes_once_and_report_validates_total(self):
        response = self.client.post(self.publish_url, self.confirmation())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Reference.objects.get().current_stock, 12)
        self.preview.refresh_from_db()
        self.assertTrue(self.preview.validation_report["published"])
        self.assertEqual(self.preview.validation_report["individual_mismatches"], 0)
        self.assertEqual(self.client.post(self.publish_url, self.confirmation()).status_code, 302)
        self.assertEqual(Reference.objects.count(), 1)
        self.assertEqual(Movement.objects.count(), 1)

    def test_preview_cli_creates_private_report_without_publication(self):
        decisions_path = self.directory / "decisions.json"
        decisions_path.write_text(json.dumps(self.decisions))
        destination = self.directory / "preview.json"
        output = io.StringIO()
        call_command("preview_stock_import", self.batch.pk, actor=self.admin.username,
                     decisions=decisions_path, report=str(destination), stdout=output)
        report = json.loads(destination.read_text())
        self.assertEqual(report["summary"]["total_stock"], 12)
        self.assertFalse(report["published"])
        self.assertNotIn("REFERÊNCIA FICTÍCIA", output.getvalue())
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertFalse(Reference.objects.exists())

    def test_publish_cli_invalid_confirmation_and_report_paths_do_not_publish(self):
        with self.assertRaises(CommandError):
            call_command("publish_stock_import", str(self.preview.pk), actor=self.admin.username,
                         confirmation=str(uuid4()), report=str(self.directory / "refused.json"))
        self.assertFalse(Reference.objects.exists())
        with self.assertRaises(CommandError):
            call_command("publish_stock_import", str(self.preview.pk), actor=self.admin.username,
                         confirmation=str(self.preview.confirmation_token),
                         report=str(Path(__file__).parent / "private.json"))
        self.assertFalse(Reference.objects.exists())

    def test_publish_cli_writes_full_validation_and_is_repeatable(self):
        for iteration in (1, 2):
            destination = self.directory / f"published-{iteration}.json"
            call_command("publish_stock_import", str(self.preview.pk), actor=self.admin.username,
                         confirmation=str(self.preview.confirmation_token), report=str(destination),
                         stdout=io.StringIO())
            report = json.loads(destination.read_text())
            self.assertEqual(report["total_stock"], 12)
            self.assertEqual(report["individual_mismatches"], 0)
            self.assertEqual(report["already_published"], iteration == 2)
        self.assertEqual(Reference.objects.count(), 1)

    def test_missing_accounts_batches_and_previews_return_command_errors(self):
        destination = str(self.directory / "invalid.json")
        with self.assertRaises(CommandError):
            call_command("publish_stock_import", str(uuid4()), actor=self.admin.username,
                         confirmation=str(uuid4()), report=destination)
        with self.assertRaises(CommandError):
            call_command("preview_stock_import", self.batch.pk, actor="missing-synthetic-account",
                         decisions=self.directory / "missing.json", report=destination)
        self.assertEqual(ImportPreview.objects.count(), 1)

    def test_history_shows_document_annotation_and_unknown_opening_separately(self):
        row = self.batch.rows.get()
        raw = row.raw_data
        raw["cells"]["E"]["value"] = None
        raw["movements"][0]["cell"]["value"] = "OBSERVAÇÃO SINTÉTICA"
        row.opening_stock = None
        row.raw_data = raw
        row.save()
        decisions = {**self.decisions,
            "annotations": {"G5": {"original_value": "OBSERVAÇÃO SINTÉTICA",
                                     "reason": "Anotação confirmada sem quantidade."}},
            "document_headers": {"G": {"original_value": "Pessoa fictícia",
                                        "document_number": "DOC-SYNTH-17",
                                        "reason": "Identificador documental de teste."}},
        }
        preview = build_preview(self.batch.pk, decisions, actor=self.admin)
        publish_preview(preview.pk, actor=self.admin, confirmation_token=preview.confirmation_token)
        response = self.client.get(reverse("web:history"), {"q": "DOC-SYNTH-17"})
        self.assertContains(response, "DOC-SYNTH-17")
        self.assertContains(response, "Pessoa não identificada na fonte")
        self.assertContains(response, "OBSERVAÇÃO SINTÉTICA")
        self.assertContains(response, "Anotação sem impacto")
        self.assertNotContains(response, "00:00")
        reference = Reference.objects.get()
        detail = self.client.get(reverse("web:reference-detail", args=[reference.pk]))
        self.assertContains(detail, "Contagem desconhecida na fonte")
        self.assertContains(detail, "Saldo inferido para reconciliação: 12")
