import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from inventory.documents import DocumentIntegrityError
from inventory.models import (
    Document,
    ImportBatch,
    Location,
    Movement,
    MovementLine,
    Reference,
    Sector,
)
from tests.document_fixtures import confirmed_operation


class DeliveryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(username="delivery-admin", role="admin")
        cls.viewer = get_user_model().objects.create_user(username="delivery-viewer")
        cls.location = Location.objects.create(name="Local entrega sintética")
        cls.destination = Location.objects.create(name="Destino entrega sintética")
        cls.sector = Sector.objects.create(location=cls.destination, name="Setor entrega sintética")
        cls.ref = Reference.objects.create(
            code="DEL-1",
            name="Produto entrega sintética",
            box_capacity=6,
            current_stock=20,
            location=cls.location,
        )
        cls.other = Reference.objects.create(
            code="DEL-2",
            name="Outra entrega sintética",
            current_stock=0,
            active=False,
            location=cls.destination,
            sector=cls.sector,
        )

    def setUp(self):
        self.client.force_login(self.viewer)

    def workbook(self, **filters):
        response = self.client.get(reverse("web:export"), filters)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("no-store", response["Cache-Control"])
        book = load_workbook(io.BytesIO(response.content), data_only=False)
        return list(book["Dados"].values), book

    def test_viewer_can_open_download_and_print_real_pdf_only(self):
        movement = confirmed_operation(self.admin, self.ref)
        document = movement.documents.get(kind="pdf")
        url = reverse("web:document-content", args=[document.pk])
        response = self.client.get(url)
        self.assertTrue(b"".join(response.streaming_content).startswith(b"%PDF"))
        self.assertIn("inline", response["Content-Disposition"])
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("attachment", self.client.get(url + "?download=1")["Content-Disposition"])
        self.assertContains(self.client.get(reverse("web:reports")), "Abrir / imprimir PDF")
        self.assertContains(
            self.client.get(reverse("web:operation-detail", args=[movement.pk])),
            "Descarregar PDF guardado",
        )

    def test_anonymous_cannot_access_pdf_signature_or_exports(self):
        movement = confirmed_operation(self.admin, self.ref, signed=True)
        self.client.logout()
        for document in movement.documents.all():
            self.assertEqual(
                self.client.get(reverse("web:document-content", args=[document.pk])).status_code,
                302,
            )
        self.assertEqual(
            self.client.get(reverse("web:export"), {"dataset": "stock"}).status_code, 302
        )

    def test_documents_have_no_public_media_or_storage_key_route(self):
        movement = confirmed_operation(self.admin, self.ref, signed=True)
        for document in movement.documents.all():
            self.assertEqual(self.client.get("/media/" + document.storage_key).status_code, 404)
            self.assertEqual(self.client.get("/static/" + document.storage_key).status_code, 404)
            self.assertEqual(
                self.client.post(reverse("web:document-content", args=[document.pk])).status_code,
                405,
            )

    def test_missing_or_metadata_only_or_draft_document_not_listed(self):
        draft = Movement.objects.create(kind="entry")
        document = Document.objects.create(
            movement=draft, kind="pdf", storage_key="synthetic-metadata-only", sha256="a" * 64
        )
        self.assertEqual(
            self.client.get(reverse("web:document-content", args=[document.pk])).status_code, 404
        )
        self.assertNotContains(self.client.get(reverse("web:reports")), "Abrir / imprimir PDF")
        self.assertEqual(
            self.client.get(reverse("web:document-content", args=[999999])).status_code, 404
        )

    def test_imported_history_never_creates_or_pretends_pdf(self):
        batch = ImportBatch.objects.create(source_name="synthetic.xlsx", sha256="f" * 64)
        mov = Movement.objects.create(kind="legacy", import_batch=batch, source_column=5)
        MovementLine.objects.create(
            movement=mov, reference=self.ref, quantity=-1, reference_name="Nome legado"
        )
        mov.status = "confirmed"
        mov.save()
        response = self.client.get(reverse("web:operation-detail", args=[mov.pk]))
        self.assertContains(response, "Não existe PDF guardado")
        self.assertFalse(mov.documents.exists())
        self.assertNotContains(self.client.get(reverse("web:reports")), "Abrir / imprimir PDF")

    def test_integrity_failure_returns_503_without_document_bytes(self):
        mov = confirmed_operation(self.admin, self.ref)
        with patch("web.reports.verified_bytes", side_effect=DocumentIntegrityError):
            response = self.client.get(
                reverse("web:document-content", args=[mov.documents.get().pk])
            )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b"%PDF", response.content)

    def test_report_filters_reference_and_period(self):
        movement = confirmed_operation(self.admin, self.ref)
        response = self.client.get(
            reverse("web:reports"),
            {"q": "DEL-1", "start": movement.date.isoformat(), "end": movement.date.isoformat()},
        )
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertEqual(
            self.client.get(reverse("web:reports"), {"q": "absent"})
            .context["page_obj"]
            .paginator.count,
            0,
        )

    def test_stock_export_active_and_canonical_box_equivalence(self):
        rows, _ = self.workbook(dataset="stock")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], "DEL-1")
        self.assertEqual(rows[1][5:9], (6, 20, 3, 2))

    def test_reference_export_includes_inactive_unknown_capacity_not_zero(self):
        rows, _ = self.workbook(dataset="references")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2][2], "Inativa")
        self.assertIsNone(rows[2][5])
        self.assertEqual(rows[2][6], 0)
        self.assertEqual(rows[2][7:9], (None, None))

    def test_export_filters_code_location_sector_and_state(self):
        rows, _ = self.workbook(
            dataset="references",
            q="DEL-2",
            location=self.destination.pk,
            sector=self.sector.pk,
            state="inactive",
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], "DEL-2")
        rows, _ = self.workbook(dataset="references", q="missing")
        self.assertEqual(len(rows), 1)

    def test_location_export_includes_sectors_and_empty_locations(self):
        rows, _ = self.workbook(dataset="locations", location=self.destination.pk)
        self.assertEqual(rows[1][:3], (self.destination.name, True, self.sector.name))
        rows, _ = self.workbook(dataset="locations", location=self.location.pk)
        self.assertIsNone(rows[1][2])

    def test_historical_export_keeps_original_inputs_names_and_capacity(self):
        mov = confirmed_operation(self.admin, self.ref)
        self.ref.name = "Nome posterior"
        self.ref.box_capacity = 12
        self.ref.save()
        rows, _ = self.workbook(
            dataset="history",
            q="DEL-1",
            start=mov.date.isoformat(),
            end=mov.date.isoformat(),
            location=self.location.pk,
        )
        self.assertEqual(rows[1][7:15], ("Produto entrega sintética", 6, None, 2, None, -2, 20, 18))
        self.assertNotIn("Nome posterior", str(rows))
        self.assertIsNone(rows[1][20])

    def test_transfers_export_before_and_after_filters_and_zero_impact(self):
        confirmed_operation(
            self.admin, self.ref, kind="inventory", units=20, location=self.destination
        )
        for location in (self.location, self.destination):
            rows, _ = self.workbook(dataset="transfers", location=location.pk)
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                (rows[1][4], rows[1][6], rows[1][9]), (self.location.name, self.destination.name, 0)
            )

    def test_formula_injection_text_is_escaped_but_negative_quantities_numeric(self):
        self.ref.name = '  =HYPERLINK("https://example.invalid")'
        self.ref.save()
        confirmed_operation(self.admin, self.ref)
        rows, book = self.workbook(dataset="history")
        self.assertTrue(rows[1][7].startswith("'"))
        self.assertEqual(rows[1][12], -2)
        self.assertTrue(all(cell.data_type != "f" for row in book["Dados"] for cell in row))

    def test_invalid_filters_rejected_and_no_secrets_in_exports(self):
        for filters in (
            {"dataset": "stock", "state": "inactive"},
            {"dataset": "stock", "start": "2026-01-01"},
            {"dataset": "history", "start": "2026-12-01", "end": "2026-01-01"},
            {"dataset": "references", "location": self.location.pk, "sector": self.sector.pk},
        ):
            self.assertEqual(self.client.get(reverse("web:export"), filters).status_code, 400)
        rows, _ = self.workbook(dataset="references")
        self.assertNotIn("password", str(rows).lower())
        self.assertNotIn(self.admin.password, str(rows))
        self.assertNotIn("signature", str(rows))

    def test_private_pages_exports_and_documents_have_no_store_and_csp(self):
        for name in ("home", "stock", "history", "reports", "export"):
            response = self.client.get(reverse("web:" + name))
            self.assertIn("no-store", response["Cache-Control"])
            self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
            self.assertIn("Cookie", response["Vary"])

    def test_manifest_has_scope_standalone_and_valid_icons(self):
        response = self.client.get(reverse("manifest"))
        data = response.json()
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        self.assertEqual(
            (data["display"], data["scope"], data["start_url"]), ("standalone", "/", "/")
        )
        self.assertEqual({icon["sizes"] for icon in data["icons"]}, {"192x192", "512x512"})

    def test_service_worker_only_whitelists_public_cache_and_never_posts(self):
        response = self.client.get(reverse("service-worker"))
        source = response.content.decode()
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn("request.method !== 'GET'", source)
        self.assertIn("cache: 'no-store'", source)
        self.assertNotIn("'/stock/'", source)
        self.assertNotIn("'/documentos/'", source)
        self.assertEqual(response["Cache-Control"], "no-cache")

    def test_public_offline_page_contains_no_user_or_stock(self):
        response = self.client.get(reverse("offline"))
        self.assertContains(response, "Sem ligação")
        self.assertNotContains(response, self.viewer.username)
        self.assertNotContains(response, self.ref.name)
        self.assertNotContains(response, "csrfmiddlewaretoken")

    def test_formula_prefixes_are_text_and_preserve_numeric_signs(self):
        from web.exports import text_cell

        for value in (
            "=SUM(1,2)",
            "+SUM(1,2)",
            "-SUM(1,2)",
            "@SUM(1,2)",
            "  =1+1",
            "\t=1+1",
            "\r=1+1",
        ):
            self.assertTrue(text_cell(value).startswith("'"))
        self.assertEqual(text_cell(-3), -3)

    def test_production_manifest_hashes_are_used_by_offline_worker(self):
        import tempfile

        from django.core.management import call_command
        from django.templatetags.static import static
        from django.test import override_settings

        with (
            tempfile.TemporaryDirectory(prefix="gg-public-static-") as directory,
            override_settings(
                STATIC_ROOT=directory,
                STORAGES={
                    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                    "staticfiles": {
                        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
                    },
                },
            ),
        ):
            call_command("collectstatic", interactive=False, verbosity=0)
            response = self.client.get(reverse("service-worker"))
            self.assertContains(response, static("css/app.css"))
            from web.branding import icon_asset

            self.assertContains(response, static(icon_asset(512)))
            self.assertNotEqual(static("css/app.css"), "/static/css/app.css")
