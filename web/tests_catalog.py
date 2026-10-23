from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse

from inventory.catalog import save_reference
from inventory.models import (
    AuditEvent,
    Location,
    LocationChange,
    Movement,
    MovementLine,
    Reference,
    Sector,
)


class CatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(username="synthetic-catalog-admin", role="admin")
        cls.viewer = get_user_model().objects.create_user(username="synthetic-catalog-viewer", role="viewer")
        cls.location = Location.objects.create(name="Localização de teste Alfa")
        cls.other_location = Location.objects.create(name="Localização de teste Beta")
        cls.sector = Sector.objects.create(name="Setor de teste Alfa", location=cls.location)
        cls.other_sector = Sector.objects.create(name="Setor de teste Beta", location=cls.other_location)
        cls.reference = Reference.objects.create(
            code="GAR-0007", name="Referência sintética Alfa", location=cls.location,
            sector=cls.sector, box_capacity=6, current_stock=13,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def url(self, name, obj=None):
        return reverse("web:" + name, args=[obj.pk] if obj else None)

    def ref_data(self, **changes):
        data = {
            "name": "Referência sintética Beta", "box_capacity": "6",
            "location": str(self.location.pk), "sector": str(self.sector.pk),
        }
        return {**data, **changes}

    def test_reference_created_with_generated_code_and_zero_stock(self):
        response = self.client.post(self.url("reference-create"), self.ref_data(code="FORGED", current_stock="999", active="0"))
        self.assertEqual(response.status_code, 302)
        created = Reference.objects.get(name="Referência sintética Beta")
        self.assertEqual(created.code, "GAR-0008")
        self.assertEqual(created.current_stock, 0)
        self.assertTrue(created.active)
        self.assertIsNone(created.minimum)
        self.assertEqual(AuditEvent.objects.get().action, "reference.created")

    def test_new_reference_unknown_capacity_and_sector_remain_unknown(self):
        response = self.client.post(self.url("reference-create"), self.ref_data(box_capacity="", sector=""))
        self.assertEqual(response.status_code, 302)
        created = Reference.objects.get(name="Referência sintética Beta")
        self.assertIsNone(created.box_capacity)
        self.assertIsNone(created.sector)

    def test_alert_requires_selected_minimum_and_can_use_zero(self):
        invalid = self.client.post(self.url("reference-edit", self.reference), self.ref_data(alert_enabled="on", minimum=""))
        self.assertEqual(invalid.status_code, 400)
        self.reference.refresh_from_db()
        self.assertIsNone(self.reference.minimum)
        valid = self.client.post(self.url("reference-edit", self.reference), self.ref_data(alert_enabled="on", minimum="0"))
        self.assertEqual(valid.status_code, 302)
        self.reference.refresh_from_db()
        self.assertEqual(self.reference.minimum, 0)

    def test_disabling_alert_removes_minimum_without_affecting_other_reference(self):
        other = Reference.objects.create(code="SYN-009", name="Outra ficha sintética", location=self.location, minimum=5)
        self.reference.minimum = 9
        self.reference.save()
        response = self.client.post(self.url("reference-edit", self.reference), self.ref_data(minimum="999"))
        self.assertEqual(response.status_code, 302)
        self.reference.refresh_from_db()
        other.refresh_from_db()
        self.assertIsNone(self.reference.minimum)
        self.assertEqual(other.minimum, 5)

    def test_inactive_alert_discards_forged_invalid_minimum(self):
        response = self.client.post(self.url("reference-create"), self.ref_data(minimum="-90"))
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(Reference.objects.get(name="Referência sintética Beta").minimum)

    def test_invalid_capacity_minimum_and_mismatched_sector_are_rejected(self):
        for changes in [
            {"box_capacity": "0"}, {"box_capacity": "1.5"},
            {"alert_enabled": "on", "minimum": "-1"},
            {"sector": self.other_sector.pk},
        ]:
            with self.subTest(changes=changes):
                response = self.client.post(self.url("reference-create"), self.ref_data(**changes))
                self.assertEqual(response.status_code, 400)
        self.assertEqual(Reference.objects.count(), 1)
        self.assertFalse(AuditEvent.objects.exists())

    def test_editing_name_capacity_location_keeps_stock_and_historical_snapshots(self):
        movement = Movement.objects.create(kind="inventory", reason="Teste sintético")
        line = MovementLine.objects.create(
            movement=movement, reference=self.reference, quantity=0,
            reference_name=self.reference.name, box_capacity=6,
        )
        movement.status = "confirmed"
        movement.save(update_fields=["status"])
        response = self.client.post(self.url("reference-edit", self.reference), self.ref_data(
            box_capacity="12", location=self.other_location.pk, sector=self.other_sector.pk,
            current_stock="1000", code="FORGED",
        ))
        self.assertEqual(response.status_code, 302)
        self.reference.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual((self.reference.code, self.reference.current_stock), ("GAR-0007", 13))
        self.assertEqual(self.reference.box_capacity, 12)
        self.assertEqual((line.reference_name, line.box_capacity), ("Referência sintética Alfa", 6))
        change = LocationChange.objects.get()
        self.assertEqual((change.location_before_id, change.location_after_id), (self.location.pk, self.other_location.pk))
        self.assertEqual((change.sector_before_id, change.sector_after_id), (self.sector.pk, self.other_sector.pk))

    def test_get_edit_and_toggle_never_modify_and_deactivation_is_idempotent(self):
        self.assertEqual(self.client.get(self.url("reference-edit", self.reference)).status_code, 200)
        self.assertEqual(self.client.get(self.url("reference-toggle", self.reference)).status_code, 200)
        self.reference.refresh_from_db()
        self.assertTrue(self.reference.active)
        self.assertFalse(AuditEvent.objects.exists())
        for _ in range(2):
            self.assertEqual(self.client.post(self.url("reference-toggle", self.reference), {"active": "0"}).status_code, 302)
        self.reference.refresh_from_db()
        self.assertFalse(self.reference.active)
        self.assertEqual(self.reference.current_stock, 13)
        self.assertEqual(AuditEvent.objects.filter(action="reference.state_changed").count(), 1)

    def test_inactive_references_can_be_found_and_reactivated(self):
        self.reference.active = False
        self.reference.save()
        response = self.client.get(self.url("references"), {"state": "inactive", "q": "GAR-0007"})
        self.assertContains(response, "Referência sintética Alfa")
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertEqual(self.client.post(self.url("reference-toggle", self.reference), {"active": "1"}).status_code, 302)
        self.reference.refresh_from_db()
        self.assertTrue(self.reference.active)

    def test_location_and_sector_create_edit_and_free_removal(self):
        response = self.client.post(self.url("location-create"), {"name": "  Novo   local sintético "})
        self.assertEqual(response.status_code, 302)
        location = Location.objects.get(name="Novo local sintético")
        self.assertEqual(self.client.post(self.url("sector-create"), {"name": "Novo setor sintético", "location": location.pk}).status_code, 302)
        sector = location.sectors.get()
        self.assertEqual(self.client.post(self.url("location-edit", location), {"name": "Local sintético renomeado"}).status_code, 302)
        self.assertEqual(self.client.post(self.url("sector-edit", sector), {"name": "Setor sintético renomeado", "location": location.pk}).status_code, 302)
        self.assertEqual(self.client.get(self.url("sector-delete", sector)).status_code, 200)
        self.assertTrue(Sector.objects.filter(pk=sector.pk).exists())
        self.assertEqual(self.client.post(self.url("sector-delete", sector)).status_code, 302)
        self.assertEqual(self.client.get(self.url("location-delete", location)).status_code, 200)
        self.assertTrue(Location.objects.filter(pk=location.pk).exists())
        self.assertEqual(self.client.post(self.url("location-delete", location)).status_code, 302)
        self.assertFalse(Location.objects.filter(pk=location.pk).exists())
        self.assertEqual(AuditEvent.objects.count(), 6)

    def test_removing_free_location_removes_its_unused_sectors(self):
        location = Location.objects.create(name="Local vazio sintético")
        sector = Sector.objects.create(name="Setor vazio sintético", location=location)
        self.assertEqual(self.client.post(self.url("location-delete", location)).status_code, 302)
        self.assertFalse(Location.objects.filter(pk=location.pk).exists())
        self.assertFalse(Sector.objects.filter(pk=sector.pk).exists())

    def test_referenced_location_and_sector_are_protected_even_if_reference_inactive(self):
        self.reference.active = False
        self.reference.save()
        self.assertEqual(self.client.post(self.url("location-delete", self.location)).status_code, 400)
        self.assertEqual(self.client.post(self.url("sector-delete", self.sector)).status_code, 400)
        self.assertTrue(Location.objects.filter(pk=self.location.pk).exists())
        self.assertTrue(Sector.objects.filter(pk=self.sector.pk).exists())
        self.assertFalse(AuditEvent.objects.exists())

    def test_history_prevents_removing_old_location_after_reference_transfer(self):
        self.client.post(self.url("reference-edit", self.reference), self.ref_data(location=self.other_location.pk, sector=self.other_sector.pk))
        self.assertFalse(self.location.references.exists())
        self.assertEqual(self.client.post(self.url("location-delete", self.location)).status_code, 400)
        self.assertTrue(Sector.objects.filter(pk=self.sector.pk).exists())
        self.assertEqual(self.client.post(self.url("sector-delete", self.sector)).status_code, 400)

    def test_used_sector_cannot_move_to_another_location(self):
        response = self.client.post(self.url("sector-edit", self.sector), {"name": self.sector.name, "location": self.other_location.pk})
        self.assertEqual(response.status_code, 400)
        self.sector.refresh_from_db()
        self.assertEqual(self.sector.location_id, self.location.pk)

    def test_unused_sector_can_move_and_names_cannot_duplicate_by_case(self):
        free = Sector.objects.create(name="Livre sintético", location=self.location)
        self.assertEqual(self.client.post(self.url("sector-edit", free), {"name": free.name, "location": self.other_location.pk}).status_code, 302)
        free.refresh_from_db()
        self.assertEqual(free.location_id, self.other_location.pk)
        self.assertEqual(self.client.post(self.url("location-create"), {"name": self.location.name.upper()}).status_code, 400)
        self.assertEqual(self.client.post(self.url("sector-create"), {"name": self.sector.name.upper(), "location": self.location.pk}).status_code, 400)

    def test_catalogue_pages_and_all_mutations_require_administrator(self):
        targets = [
            ("references", None), ("reference-create", None), ("reference-edit", self.reference),
            ("reference-toggle", self.reference), ("locations", None), ("location-create", None),
            ("location-edit", self.location), ("location-delete", self.location),
            ("sector-create", None), ("sector-edit", self.sector), ("sector-delete", self.sector),
        ]
        self.client.force_login(self.viewer)
        for name, obj in targets:
            with self.subTest(name=name):
                url = self.url(name, obj)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, self.ref_data()).status_code, 403)
                self.assertEqual(Client().get(url).status_code, 302)
        self.assertEqual(Reference.objects.count(), 1)
        self.assertFalse(AuditEvent.objects.exists())

    def test_catalogue_mutation_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(self.url("reference-create"), self.ref_data()).status_code, 403)
        self.assertEqual(client.post(self.url("location-delete", self.location)).status_code, 403)

    def test_service_also_refuses_consultation_user(self):
        with self.assertRaises(PermissionDenied):
            save_reference(actor=self.viewer, data={"name": "Tentativa sintética", "location": self.location})
        self.assertEqual(Reference.objects.count(), 1)
