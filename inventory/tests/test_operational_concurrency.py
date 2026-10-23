"""Actual PostgreSQL connections, not mocked locks or SQLite threads."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, skipUnlessDBFeature

from inventory import operations
from inventory.models import AuditEvent, Location, LocationChange, Movement, Reference, Sector
from inventory.services import confirm_movement


@skipUnlessDBFeature("has_select_for_update")
class OperationalConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(username="ops-concurrent", role="admin")
        self.location = Location.objects.create(name="Local sintético concorrente")
        self.destination = Location.objects.create(name="Destino sintético concorrente")
        self.ref = Reference.objects.create(
            code="OC-1", name="Concorrência sintética", location=self.location, current_stock=10
        )
        self.second = Reference.objects.create(
            code="OC-2", name="Concorrência sintética 2", location=self.location, current_stock=10
        )

    def reviewed(self, kind="exit", refs=None, units=7, location=None):
        draft = operations.create_draft(actor=self.admin, kind=kind, references=refs or [self.ref])
        draft = operations.save_draft(
            draft.pk,
            actor=self.admin,
            revision=0,
            header={"person_name": "Pessoa concorrente sintética"},
            rows=[
                {
                    "id": line.pk,
                    "units": units,
                    "reason": "Contagem concorrente",
                    "target_location": location or self.location,
                }
                for line in draft.lines.all()
            ],
        )
        return operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)[0]

    def parallel(self, actions):
        barrier = Barrier(len(actions))

        def run(action):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.admin.pk)
                barrier.wait(timeout=10)
                try:
                    action(actor)
                    return "ok"
                except ValidationError:
                    return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            futures = [pool.submit(run, action) for action in actions]
            return [f.result(timeout=20) for f in futures]

    def confirm_action(self, draft):
        return lambda actor: confirm_movement(
            draft.pk, actor=actor, review_token=draft.review_token, report_requested=False
        )

    def test_two_reviewed_exits_cannot_oversell_multiple_references(self):
        drafts = [self.reviewed(refs=[self.ref, self.second]) for _ in range(2)]
        self.assertCountEqual(
            self.parallel([self.confirm_action(d) for d in drafts]), ["ok", "rejected"]
        )
        self.assertEqual(
            list(Reference.objects.order_by("pk").values_list("current_stock", flat=True)), [3, 3]
        )
        self.assertEqual(Movement.objects.filter(status="confirmed").count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="movement.confirmed").count(), 1)

    def test_simultaneous_confirmation_of_same_draft_changes_stock_once(self):
        draft = self.reviewed("entry", units=4)
        self.assertCountEqual(
            self.parallel([self.confirm_action(draft), self.confirm_action(draft)]),
            ["ok", "rejected"],
        )
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 14)
        self.assertEqual(draft.audit_events.filter(action="movement.confirmed").count(), 1)

    def test_inventory_and_entry_cannot_silently_overwrite_each_other(self):
        inventory, entry = self.reviewed("inventory", units=8), self.reviewed("entry", units=2)
        self.assertCountEqual(
            self.parallel([self.confirm_action(inventory), self.confirm_action(entry)]),
            ["ok", "rejected"],
        )
        self.ref.refresh_from_db()
        self.assertIn(self.ref.current_stock, (8, 12))
        self.assertEqual(Movement.objects.filter(status="confirmed").count(), 1)

    def test_two_inventories_detect_conflicting_counts(self):
        first, second = self.reviewed("inventory", units=8), self.reviewed("inventory", units=11)
        self.assertCountEqual(
            self.parallel([self.confirm_action(first), self.confirm_action(second)]),
            ["ok", "rejected"],
        )
        self.ref.refresh_from_db()
        self.assertIn(self.ref.current_stock, (8, 11))

    def test_confirmation_races_draft_edit_without_lost_updates(self):
        draft = self.reviewed("entry", units=2)
        line = draft.lines.get()

        def edit(actor):
            return operations.save_draft(
                draft.pk,
                actor=actor,
                revision=draft.revision,
                header={},
                rows=[{"id": line.pk, "units": 5}],
            )

        self.assertCountEqual(self.parallel([edit, self.confirm_action(draft)]), ["ok", "rejected"])
        draft.refresh_from_db()
        self.ref.refresh_from_db()
        self.assertIn(
            (draft.status, self.ref.current_stock, draft.lines.get().units),
            [("confirmed", 12, 2), ("draft", 10, 5)],
        )

    def test_cancel_races_confirmation_without_quantitative_cancellation(self):
        draft = self.reviewed("entry", units=2)

        def cancel(actor):
            return operations.cancel_draft(draft.pk, actor=actor, revision=draft.revision)

        self.assertCountEqual(
            self.parallel([cancel, self.confirm_action(draft)]), ["ok", "rejected"]
        )
        draft.refresh_from_db()
        self.ref.refresh_from_db()
        self.assertIn(
            (draft.status, self.ref.current_stock), [("confirmed", 12), ("cancelled", 10)]
        )

    def test_reference_row_lock_blocks_confirmation_until_released(self):
        draft = self.reviewed("entry", units=2)
        held, release, started = Event(), Event(), Event()

        def hold():
            close_old_connections()
            try:
                with transaction.atomic():
                    Reference.objects.select_for_update().get(pk=self.ref.pk)
                    held.set()
                    if not release.wait(timeout=10):
                        raise AssertionError("Lock test timed out")
            finally:
                close_old_connections()

        def confirm():
            close_old_connections()
            try:
                started.set()
                return self.confirm_action(draft)(get_user_model().objects.get(pk=self.admin.pk))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            holder = pool.submit(hold)
            self.assertTrue(held.wait(timeout=5))
            confirming = pool.submit(confirm)
            self.assertTrue(started.wait(timeout=5))
            # Observe PostgreSQL's actual lock wait instead of guessing with sleep.
            with connection.cursor() as cursor:
                for _ in range(100):
                    cursor.execute(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%inventory_reference%'"
                    )
                    if cursor.fetchone()[0]:
                        break
                    Event().wait(0.01)
                else:
                    release.set()
                    self.fail("Confirmation did not wait on the reference row lock")
            self.assertFalse(confirming.done())
            release.set()
            holder.result(timeout=5)
            confirming.result(timeout=5)
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 12)

    def test_late_write_failure_rolls_back_all_stock_locations_snapshots_and_audit(self):
        draft = self.reviewed(
            "inventory", [self.ref, self.second], units=12, location=self.destination
        )
        original_save = Reference.save

        def fail_second(ref, *args, **kwargs):
            if ref.pk == self.second.pk:
                raise IntegrityError(
                    "Synthetic failure after first stock and location were written"
                )
            return original_save(ref, *args, **kwargs)

        with patch.object(Reference, "save", fail_second), self.assertRaises(IntegrityError):
            self.confirm_action(draft)(self.admin)
        self.assertEqual(
            set(Reference.objects.values_list("current_stock", "location_id")),
            {(10, self.location.pk)},
        )
        self.assertFalse(LocationChange.objects.exists())
        self.assertFalse(
            AuditEvent.objects.filter(
                action__in=["movement.confirmed", "movement.location_changed"]
            ).exists()
        )
        self.assertFalse(draft.lines.filter(stock_before__isnull=False).exists())
        draft.refresh_from_db()
        self.assertEqual(draft.status, "draft")

    def test_confirmed_transfers_and_audit_events_are_immutable_in_postgresql(self):
        draft = self.reviewed("inventory", units=10, location=self.destination)
        self.confirm_action(draft)(self.admin)
        change = draft.location_changes.get()
        audit = draft.audit_events.get(action="movement.confirmed")
        for sql, params in (
            ("UPDATE inventory_locationchange SET reason=%s WHERE id=%s", ["Tamper", change.pk]),
            ("DELETE FROM inventory_locationchange WHERE id=%s", [change.pk]),
            ("UPDATE inventory_auditevent SET action=%s WHERE id=%s", ["Tamper", audit.pk]),
            ("DELETE FROM inventory_auditevent WHERE id=%s", [audit.pk]),
        ):
            with (
                self.subTest(sql=sql),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(sql, params)
        with self.assertRaises(ValidationError):
            change.delete()
        with self.assertRaises(ValidationError):
            draft.location_changes.update(reason="Tamper")
        with self.assertRaises(ValidationError):
            audit.delete()
        with self.assertRaises(ValidationError):
            AuditEvent.objects.filter(pk=audit.pk).update(action="Tamper")

    def test_invalid_sector_insert_cannot_leak_partial_stock_change(self):
        draft = self.reviewed(
            "inventory", [self.ref, self.second], units=12, location=self.destination
        )
        foreign = Sector.objects.create(name="Fora", location=self.location)
        draft.lines.filter(reference=self.second).update(target_sector=foreign)
        with self.assertRaises(ValidationError):
            self.confirm_action(draft)(self.admin)
        self.assertEqual(
            set(Reference.objects.values_list("current_stock", "location_id")),
            {(10, self.location.pk)},
        )
        self.assertFalse(LocationChange.objects.exists())
