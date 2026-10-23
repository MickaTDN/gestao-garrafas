from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from inventory.models import ImportBatch, Location, Movement, MovementLine, Reference, Sector


class WebTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.admin = users.objects.create_user(username="test-admin", role="admin")
        cls.viewer = users.objects.create_user(username="test-viewer", role="viewer")
        cls.location = Location.objects.create(name="Local sintético")
        cls.other_location = Location.objects.create(name="Outro local sintético")
        cls.sector = Sector.objects.create(location=cls.location, name="Setor de teste")
        cls.reference = Reference.objects.create(
            code="TEST-001", name="Referência sintética", location=cls.location,
            sector=cls.sector, current_stock=13, box_capacity=6, minimum=13,
        )
        Reference.objects.create(
            code="TEST-002", name="Outra referência sintética", location=cls.other_location,
            current_stock=2, box_capacity=None,
        )

    def setUp(self):
        self.client.force_login(self.viewer)

    def test_all_read_views_require_authentication(self):
        guest = Client()
        for name in ("home", "stock", "history", "settings", "entry", "exit", "inventory", "references"):
            with self.subTest(name=name):
                response = guest.get(reverse(f"web:{name}"))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response.url)

    def test_viewer_can_consult_real_database_totals(self):
        response = self.client.get(reverse("web:home"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_stock"], 15)
        self.assertEqual(response.context["reference_count"], 2)
        self.assertEqual(response.context["alert_count"], 1)
        self.assertContains(response, "Consulta")
        self.assertNotContains(response, reverse("web:settings"))

    def test_viewer_cannot_access_management_even_with_direct_url(self):
        for name in ("settings", "entry", "exit", "inventory", "references"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"web:{name}")).status_code, 403)
                self.assertEqual(self.client.post(reverse(f"web:{name}")).status_code, 403)

    def test_admin_can_start_operational_drafts_but_read_views_are_get_only(self):
        self.client.force_login(self.admin)
        for name in ("settings", "entry", "exit", "inventory", "references"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(f"web:{name}")).status_code, 200)
                self.assertEqual(self.client.post(reverse(f"web:{name}")).status_code, 302 if name in ("entry", "exit", "inventory") else 405)

    def test_search_by_code_and_location(self):
        response = self.client.get(reverse("web:stock"), {"q": "test-001", "location": self.location.pk})
        self.assertContains(response, "Referência sintética")
        self.assertNotContains(response, "Outra referência sintética")
        self.assertContains(response, "2 cx + 1 un.")
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_sector_filter_and_invalid_location_sector_combination(self):
        response = self.client.get(reverse("web:stock"), {"sector": self.sector.pk})
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        invalid = self.client.get(reverse("web:stock"), {"sector": self.sector.pk, "location": self.other_location.pk})
        self.assertEqual(invalid.status_code, 400)
        self.assertContains(invalid, "O setor não pertence", status_code=400)

    def test_empty_search_does_not_show_unrelated_rows(self):
        response = self.client.get(reverse("web:stock"), {"q": "ausente-xyz"})
        self.assertContains(response, "Não foram encontradas referências.")
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_missing_capacity_and_inactive_reference(self):
        response = self.client.get(reverse("web:stock"), {"q": "TEST-002"})
        self.assertContains(response, "Caixa não definida")
        self.reference.active = False
        self.reference.save()
        response = self.client.get(reverse("web:stock"), {"q": "TEST-001"})
        self.assertEqual(response.context["page_obj"].paginator.count, 0)
        self.assertContains(self.client.get(reverse("web:reference-detail", args=[self.reference.pk])), "Inativa")

    def test_stock_is_paginated_without_losing_filter(self):
        Reference.objects.bulk_create([
            Reference(code=f"PAGE-{index:03}", name=f"Página {index:03}", location=self.location)
            for index in range(45)
        ])
        response = self.client.get(reverse("web:stock"), {"q": "PAGE", "page": 2})
        self.assertEqual(len(response.context["page_obj"]), 5)
        self.assertContains(response, "q=PAGE")
        self.assertContains(response, "Página 2 de 2")

    def test_user_supplied_name_is_escaped(self):
        self.reference.name = "<script>alert('synthetic')</script>"
        self.reference.save()
        response = self.client.get(reverse("web:reference-detail", args=[self.reference.pk]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>")

    def test_history_handles_empty_and_invalid_dates(self):
        response = self.client.get(reverse("web:history"))
        self.assertContains(response, "Ainda não existem movimentos confirmados")
        invalid = self.client.get(reverse("web:history"), {"start": "2026-12-01", "end": "2026-01-01"})
        self.assertEqual(invalid.status_code, 400)
        self.assertContains(invalid, "A data final deve ser igual ou posterior", status_code=400)

    def test_legacy_history_preserves_label_sign_snapshot_and_date_without_time(self):
        batch = ImportBatch.objects.create(source_name="synthetic.xlsx", sha256="0" * 64)
        movement = Movement.objects.create(
            kind="legacy", date=date(2025, 1, 6), import_batch=batch,
            original_label="Correção sintética", source_column=8,
        )
        MovementLine.objects.create(
            movement=movement, reference=self.reference, quantity=-2,
            reference_name="Designação histórica sintética",
        )
        movement.status = "confirmed"
        movement.save(update_fields=["status"])
        self.reference.name = "Designação atual sintética"
        self.reference.save()
        response = self.client.get(reverse("web:history"), {"q": "TEST-001", "start": "2025-01-06", "end": "2025-01-06"})
        self.assertContains(response, "Correção sintética")
        self.assertContains(response, "Designação histórica sintética")
        self.assertNotContains(response, "Designação atual sintética")
        self.assertContains(response, "06/01/2025")
        self.assertNotContains(response, "00:00")
        self.assertContains(response, ">-2<", html=False)
        self.assertEqual(response.context["page_obj"].paginator.count, 1)

    def test_read_views_reject_post(self):
        for name in ("home", "stock", "history"):
            with self.subTest(name=name):
                self.assertEqual(self.client.post(reverse(f"web:{name}")).status_code, 302 if name in ("entry", "exit", "inventory") else 405)
