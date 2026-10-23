from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from inventory.models import Location, Movement, MovementLine, Person, Reference
from inventory.services import confirm_movement


@skipUnless(connection.vendor == "postgresql", "Ledger SQL guards are PostgreSQL-specific")
class PostgreSQLHistoryTests(TestCase):
    def setUp(self):
        actor = get_user_model().objects.create_user(username="guard_teste", role="admin")
        location = Location.objects.create(name="Local SQL sintético")
        reference = Reference.objects.create(code="SQL-001", name="Referência SQL sintética", location=location)
        person = Person.objects.create(name="Pessoa SQL sintética")
        self.movement = Movement.objects.create(kind="entry", person=person)
        self.line = MovementLine.objects.create(movement=self.movement, reference=reference, quantity=2)
        confirm_movement(self.movement.pk, actor=actor)

    def test_raw_sql_cannot_rewrite_or_delete_confirmed_movement(self):
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE inventory_movement SET reason = %s WHERE id = %s", ["alteração", self.movement.pk])
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM inventory_movement WHERE id = %s", [self.movement.pk])
        self.movement.refresh_from_db()
        self.assertEqual(self.movement.reason, "")

    def test_raw_sql_cannot_rewrite_delete_or_add_confirmed_line(self):
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE inventory_movementline SET quantity = 99 WHERE id = %s", [self.line.pk])
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("DELETE FROM inventory_movementline WHERE id = %s", [self.line.pk])
        # A distinct reference avoids the unique constraint masking a missing trigger.
        other_reference = Reference.objects.create(
            code="SQL-002", name="Outra referência sintética", location=self.line.reference.location,
        )
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO inventory_movementline (movement_id, reference_id, quantity, reference_name) VALUES (%s, %s, %s, %s)",
                [self.movement.pk, other_reference.pk, 1, "Nova linha"],
            )
        self.line.refresh_from_db()
        self.assertEqual(self.line.quantity, 2)
