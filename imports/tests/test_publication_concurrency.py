"""Concurrent publication uses an isolated database and synthetic source data only."""

import io
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection, connections
from django.db.models import Sum
from django.test import TransactionTestCase

from imports.reconciliation import build_preview, publish_preview
from imports.tests.test_excel import synthetic_workbook
from inventory.catalog import save_reference
from inventory.models import (
    AuditEvent,
    ImportBatch,
    ImportPreview,
    Location,
    Movement,
    MovementLine,
    MovementLineSource,
    OpeningBalance,
    Reference,
)


@skipUnless(connection.vendor == "postgresql", "Publication locks require PostgreSQL")
class PublicationConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.private = tempfile.TemporaryDirectory(prefix="synthetic-concurrent-import-")
        self.addCleanup(self.private.cleanup)
        self.actor = get_user_model().objects.create_user(
            username="synthetic-concurrent-publisher", role="admin",
        )
        # TransactionTestCase flushes data between tests, including migration seeds.
        self.location, _ = Location.objects.get_or_create(name="Corredor Esquerdo")
        source = synthetic_workbook(Path(self.private.name) / "synthetic.xlsx")
        call_command(
            "inspect_stock_excel", source, stage=True,
            report=str(Path(self.private.name) / "inspection.json"), stdout=io.StringIO(),
        )
        self.batch = ImportBatch.objects.get()
        self.decisions = {
            "schema_version": 1, "expected_total": 12, "expected_references": 1,
            "blank_opening_policy": "unknown_derived", "annotations": {}, "document_headers": {},
        }
        self.preview = build_preview(self.batch.pk, self.decisions, actor=self.actor)

    def concurrently(self, operations):
        barrier = Barrier(len(operations))

        def run(operation):
            connections.close_all()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '10s'")
                    cursor.execute("SET lock_timeout = '8s'")
                barrier.wait(timeout=5)
                return operation(actor)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            futures = [pool.submit(run, operation) for operation in operations]
            return [future.result(timeout=15) for future in futures]

    def publication(self, preview):
        return lambda actor: publish_preview(
            preview.pk, actor=actor, confirmation_token=preview.confirmation_token,
        )

    def assert_single_import(self):
        self.assertEqual(Movement.objects.count(), 1)
        self.assertEqual(MovementLine.objects.count(), 1)
        self.assertEqual(MovementLineSource.objects.count(), 1)
        self.assertEqual(OpeningBalance.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="import.published").count(), 1)
        self.assertEqual(Reference.objects.aggregate(total=Sum("current_stock"))["total"], 12)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, ImportBatch.Status.IMPORTED)

    def test_simultaneous_confirmation_of_same_preview_imports_only_once(self):
        reports = self.concurrently([self.publication(self.preview), self.publication(self.preview)])
        self.assertCountEqual([report["already_published"] for report in reports], [False, True])
        self.assertEqual({report["preview_id"] for report in reports}, {str(self.preview.pk)})
        self.assertEqual(Reference.objects.count(), 1)
        self.assert_single_import()

    def test_simultaneous_confirmation_of_two_previews_of_same_batch_imports_only_once(self):
        second = build_preview(self.batch.pk, self.decisions, actor=self.actor)
        reports = self.concurrently([self.publication(self.preview), self.publication(second)])
        self.assertCountEqual([report["already_published"] for report in reports], [False, True])
        self.assertEqual(len({report["preview_id"] for report in reports}), 1)
        self.assertEqual(ImportPreview.objects.filter(published_at__isnull=False).count(), 1)
        self.assertEqual(Reference.objects.count(), 1)
        self.assert_single_import()

    def test_catalogue_creation_and_publication_leave_only_complete_consistent_results(self):
        def create_reference(actor):
            reference = save_reference(actor=actor, data={
                "name": "Referência manual sintética", "box_capacity": None,
                "location": Location.objects.get(pk=self.location.pk), "sector": None,
                "alert_enabled": False, "minimum": None,
            })
            return reference.pk

        def publish(actor):
            try:
                self.publication(self.preview)(actor)
                return "published"
            except ValidationError as error:
                self.assertIn("desatualizada", " ".join(error.messages))
                return "stale"

        reference_pk, publication = self.concurrently([create_reference, publish])
        manual = Reference.objects.get(pk=reference_pk)
        self.assertEqual(manual.current_stock, 0)
        if publication == "published":
            self.assertEqual(Reference.objects.count(), 2)
            self.assert_single_import()
        else:
            self.assertEqual(Reference.objects.count(), 1)
            self.assertEqual(manual.code, "GAR-0001")
            self.assertFalse(Movement.objects.exists())
            self.assertFalse(MovementLine.objects.exists())
            self.assertFalse(MovementLineSource.objects.exists())
            self.assertFalse(OpeningBalance.objects.exists())
            self.assertFalse(AuditEvent.objects.filter(action="import.published").exists())
            self.assertFalse(ImportPreview.objects.filter(published_at__isnull=False).exists())
            self.assertTrue(self.batch.rows.filter(reference__isnull=True).exists())
