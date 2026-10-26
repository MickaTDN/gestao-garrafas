import secrets

from django.contrib.auth.hashers import make_password
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone

from accounts.models import AccessProfile, User
from accounts.permissions import SUBSTITUTE
from inventory.documents import verified_bytes
from inventory.models import Document, Location, Movement, Reference, ReportNumber, ReportSequence
from inventory.reporting import delete_pdf, regenerate_pdf
from tests.document_fixtures import confirmed_operation


class A4MigrationCompatibilityTests(TransactionTestCase):
    def test_upgrade_keeps_a3_numbers_no_pdf_history_passwords_and_signed_evidence(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        actor = User.objects.create(
            username="a4-old-schema-admin",
            role="admin",
            password=make_password(secrets.token_urlsafe(32)),
        )
        profile, _ = AccessProfile.objects.get_or_create(
            name="Substituto", defaults={"capabilities": SUBSTITUTE}
        )
        sub = User.objects.create(
            username="a4-old-schema-sub",
            role="custom",
            access_profile=profile,
            password=make_password(secrets.token_urlsafe(32)),
            must_change_password=True,
        )
        hashes = (actor.password, sub.password)
        try:
            executor.migrate([("inventory", "0013_protect_a2_evidence_on_reverse")])
            old = executor.loader.project_state(
                [("inventory", "0013_protect_a2_evidence_on_reverse")]
            ).apps
            OldMovement = old.get_model("inventory", "Movement")
            OldLine = old.get_model("inventory", "MovementLine")
            location = Location.objects.create(name="Local A3 anterior fictício")
            reference = Reference.objects.create(
                code="A4-OLD",
                name="Garrafa histórica A3 fictícia",
                current_stock=32,
                box_capacity=6,
                location=location,
            )
            historical = OldMovement.objects.create(
                kind="entry",
                workflow_version=1,
                created_by_id=actor.pk,
                confirmed_by_id=actor.pk,
                date=timezone.localdate(),
                occurred_at=timezone.now(),
                person_name="Cliente histórico fictício",
            )
            OldLine.objects.create(
                movement_id=historical.pk,
                reference_id=reference.pk,
                quantity=2,
                units=2,
                box_capacity=6,
                reference_name=reference.name,
                stock_before=30,
                stock_after=32,
            )
            historical.status = "confirmed"
            historical.save(update_fields=["status"])
            # The A4 PDF path produces the same A2/A3 evidence on the old schema:
            # its number row still has a non-null document and immutable recipe.
            numbered = confirmed_operation(actor, reference, signed=True)
            document = numbered.documents.get(kind="pdf")
            original = verified_bytes(document)
            identity = (numbered.report_number.pk, str(numbered.report_number))
            metadata = document.metadata
            delete_pdf(actor=actor, document_id=document.pk)
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            self.assertFalse(ReportNumber.objects.filter(movement_id=historical.pk).exists())
            self.assertIn("Identificador técnico", str(Movement.objects.get(pk=historical.pk)))
            self.assertEqual(
                (
                    ReportNumber.objects.get(movement=numbered).pk,
                    str(ReportNumber.objects.get(movement=numbered)),
                ),
                identity,
            )
            self.assertEqual(ReportSequence.objects.get().last_number, 1)
            actor.refresh_from_db()
            sub.refresh_from_db()
            self.assertEqual((actor.password, sub.password), hashes)
            self.assertTrue(sub.must_change_password)
            self.assertEqual(sub.access_profile_id, profile.pk)
            regenerate_pdf(actor=actor, document_id=document.pk)
            self.assertEqual(verified_bytes(Document.objects.get(pk=document.pk)), original)
            self.assertEqual(Document.objects.get(pk=document.pk).metadata, metadata)
            self.assertTrue(numbered.documents.filter(kind="signature").exists())
            new = confirmed_operation(actor, reference, kind="entry", report=False)
            self.assertEqual(new.report_number.number, 2)
            self.assertIsNone(new.report_number.document_id)
            self.assertEqual(ReportSequence.objects.get().last_number, 2)
            self.assertEqual(Reference.objects.get(pk=reference.pk).current_stock, 32)
            self.assertFalse(ReportNumber.objects.filter(movement_id=historical.pk).exists())
        finally:
            MigrationExecutor(connection).migrate(latest)
