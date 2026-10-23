from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from inventory.models import (
    AuditEvent,
    ImportBatch,
    LegacyRow,
    Location,
    LocationChange,
    Movement,
    MovementLine,
    OpeningBalance,
    Person,
    Reference,
    Sector,
)
from inventory.services import confirm_movement, resolve_person


class DomainTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(username="administrador_teste", role="admin")
        cls.viewer = get_user_model().objects.create_user(username="consulta_teste", role="viewer")
        cls.location = Location.objects.create(name="Local de teste")
        cls.other_location = Location.objects.create(name="Outro local de teste")
        cls.sector = Sector.objects.create(location=cls.location, name="Setor sintético")
        cls.person = Person.objects.create(name="Pessoa Sintética")

    def reference(self, *, code="TEST-001", **kwargs):
        return Reference.objects.create(code=code, name="Referência sintética", location=self.location, current_stock=10, **kwargs)

    def movement(self, kind=Movement.Kind.ENTRY, **kwargs):
        return Movement.objects.create(kind=kind, person=self.person, date=date(2026, 1, 2), **kwargs)

    def test_structure_seed_has_four_locations_and_twenty_seven_sectors(self):
        # Only structural locations are seeded; products and people remain empty.
        self.assertEqual(Location.objects.exclude(pk__in=[self.location.pk, self.other_location.pk]).count(), 4)
        self.assertEqual(Sector.objects.exclude(pk=self.sector.pk).count(), 27)
        self.assertEqual(Reference.objects.count(), 0)

    def test_unknown_capacity_and_disabled_alert_are_preserved(self):
        reference = self.reference()
        reference.full_clean()
        self.assertIsNone(reference.box_capacity)
        self.assertIsNone(reference.minimum)

    def test_sector_must_belong_to_reference_location(self):
        with self.assertRaises(ValidationError):
            Reference.objects.create(code="INVALID", name="Teste", location=self.other_location, sector=self.sector)

    def test_location_change_cannot_store_sector_of_another_location(self):
        with self.assertRaises(ValidationError):
            LocationChange.objects.create(
                reference=self.reference(), changed_by=self.admin,
                location_before=self.location, location_after=self.other_location,
                sector_before=self.sector, sector_after=self.sector,
            )
        self.assertFalse(LocationChange.objects.exists())

    def test_database_rejects_zero_capacity_and_negative_stock(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.reference(box_capacity=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reference.objects.create(code="NEG", name="Teste", location=self.location, current_stock=-1)

    def test_people_are_resolved_without_case_or_space_duplicates(self):
        first = resolve_person("  Pessoa   DE Teste  ")
        second = resolve_person("pessoa de teste")
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.name, "Pessoa DE Teste")

    def test_reference_and_location_with_history_cannot_be_deleted(self):
        reference = self.reference()
        movement = self.movement()
        MovementLine.objects.create(movement=movement, reference=reference, quantity=1)
        with self.assertRaises(ProtectedError):
            reference.delete()
        with self.assertRaises(ProtectedError):
            self.location.delete()

    def test_draft_does_not_change_stock(self):
        reference = self.reference()
        MovementLine.objects.create(movement=self.movement(), reference=reference, quantity=6)
        reference.refresh_from_db()
        self.assertEqual(reference.current_stock, 10)

    def test_consultation_user_cannot_confirm_or_change_stock(self):
        reference = self.reference()
        movement = self.movement()
        MovementLine.objects.create(movement=movement, reference=reference, quantity=2)
        with self.assertRaises(PermissionDenied):
            confirm_movement(movement.pk, actor=self.viewer)
        reference.refresh_from_db()
        self.assertEqual(reference.current_stock, 10)
        self.assertFalse(AuditEvent.objects.exists())

    def test_inactive_administrator_cannot_confirm(self):
        self.admin.is_active = False
        with self.assertRaises(PermissionDenied):
            confirm_movement(self.movement().pk, actor=self.admin)

    def test_confirmation_persists_exact_box_and_unit_input_and_capacity(self):
        reference = self.reference(box_capacity=6)
        movement = self.movement()
        line = MovementLine.objects.create(movement=movement, reference=reference, quantity=14, boxes=1, units=8)
        confirm_movement(movement.pk, actor=self.admin)
        reference.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(reference.current_stock, 24)
        self.assertEqual((line.stock_before, line.stock_after), (10, 24))
        self.assertEqual((line.boxes, line.units, line.box_capacity), (1, 8, 6))
        self.assertEqual(line.reference_name, "Referência sintética")
        reference.box_capacity = 12
        reference.name = "Novo nome sintético"
        reference.save()
        line.refresh_from_db()
        self.assertEqual((line.box_capacity, line.reference_name), (6, "Referência sintética"))
        self.assertEqual(AuditEvent.objects.get().action, "movement.confirmed")

    def test_exit_requires_validation_and_has_signed_quantity_and_report(self):
        reference = self.reference()
        movement = self.movement(Movement.Kind.EXIT)
        MovementLine.objects.create(movement=movement, reference=reference, quantity=-3)
        with self.assertRaises(ValidationError):
            confirm_movement(movement.pk, actor=self.admin)
        movement.validation = Movement.Validation.SIMPLE
        movement.save()
        confirmed = confirm_movement(movement.pk, actor=self.admin)
        reference.refresh_from_db()
        self.assertEqual(reference.current_stock, 7)
        self.assertTrue(confirmed.report_requested)
        self.assertIsNotNone(confirmed.occurred_at)

    def test_insufficient_second_line_rolls_back_entire_confirmation(self):
        first, second = self.reference(), self.reference(code="TEST-002")
        movement = self.movement(Movement.Kind.EXIT, validation=Movement.Validation.SIMPLE)
        line = MovementLine.objects.create(movement=movement, reference=first, quantity=-2)
        MovementLine.objects.create(movement=movement, reference=second, quantity=-11)
        with self.assertRaises(ValidationError):
            confirm_movement(movement.pk, actor=self.admin)
        first.refresh_from_db()
        second.refresh_from_db()
        movement.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual((first.current_stock, second.current_stock), (10, 10))
        self.assertEqual(movement.status, Movement.Status.DRAFT)
        self.assertIsNone(line.stock_before)
        self.assertFalse(AuditEvent.objects.exists())

    def test_invalid_entry_sign_is_rejected(self):
        movement = self.movement()
        MovementLine.objects.create(movement=movement, reference=self.reference(), quantity=-1)
        with self.assertRaises(ValidationError):
            confirm_movement(movement.pk, actor=self.admin)

    def test_unknown_capacity_rejects_boxes_but_accepts_loose_bottles(self):
        movement = self.movement()
        line = MovementLine.objects.create(movement=movement, reference=self.reference(), quantity=3, boxes=1, units=3)
        with self.assertRaises(ValidationError):
            confirm_movement(movement.pk, actor=self.admin)
        line.boxes = 0
        line.save()
        confirm_movement(movement.pk, actor=self.admin)
        line.refresh_from_db()
        self.assertIsNone(line.box_capacity)
        self.assertEqual(line.stock_after, 13)

    def test_inventory_difference_requires_reason(self):
        movement = self.movement(Movement.Kind.INVENTORY)
        MovementLine.objects.create(movement=movement, reference=self.reference(), quantity=-1)
        with self.assertRaises(ValidationError):
            confirm_movement(movement.pk, actor=self.admin)
        movement.reason = "Contagem física sintética"
        movement.save()
        confirm_movement(movement.pk, actor=self.admin)

    def test_confirmed_records_are_immutable_and_cannot_be_confirmed_twice(self):
        movement = self.movement()
        line = MovementLine.objects.create(movement=movement, reference=self.reference(), quantity=1)
        movement = confirm_movement(movement.pk, actor=self.admin)
        line.refresh_from_db()
        with self.assertRaises(ValidationError):
            confirm_movement(movement.pk, actor=self.admin)
        with self.assertRaises(ValidationError):
            movement.save()
        with self.assertRaises(ValidationError):
            line.delete()
        with self.assertRaises(ValidationError):
            Movement.objects.filter(pk=movement.pk).update(reason="Reescrita")
        with self.assertRaises(ValidationError):
            MovementLine.objects.filter(pk=line.pk).update(quantity=90)
        with self.assertRaises(ValidationError):
            MovementLine.objects.create(movement=movement, reference=self.reference(code="TEST-002"), quantity=1)

    def test_legacy_retains_dates_signed_corrections_and_source_rows(self):
        batch = ImportBatch.objects.create(source_name="ficheiro_sintetico.xlsx", sha256="a" * 64)
        reference = self.reference()
        row = LegacyRow.objects.create(import_batch=batch, row_number=5, reference=reference, raw_data={"label": "Correção sintética"}, opening_stock=11, reported_stock=10, reconciled_stock=10)
        OpeningBalance.objects.create(reference=reference, date=date(2025, 1, 6), quantity=11, legacy_row=row)
        movement = Movement.objects.create(kind=Movement.Kind.LEGACY, date=date(2025, 2, 1), import_batch=batch, source_column=8, original_label="Entrada corrigida")
        MovementLine.objects.create(movement=movement, reference=reference, quantity=-1, legacy_row=row)
        movement.status = Movement.Status.CONFIRMED
        movement.validation = Movement.Validation.IMPORT
        movement.save()
        self.assertIsNone(movement.occurred_at)
        self.assertEqual(reference.opening_balances.get().quantity + movement.lines.get().quantity, 10)
        with self.assertRaises(ValidationError):
            movement.delete()

    def test_legacy_cannot_be_confirmed_as_a_new_live_movement(self):
        batch = ImportBatch.objects.create(source_name="sintetico.xlsx", sha256="b" * 64)
        movement = self.movement(Movement.Kind.LEGACY, import_batch=batch)
        MovementLine.objects.create(movement=movement, reference=self.reference(), quantity=3)
        with self.assertRaises(ValidationError):
            confirm_movement(movement.pk, actor=self.admin)
