import hashlib
import io
from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from reportlab.pdfgen.canvas import Canvas


class A2MigrationCompatibilityTests(TransactionTestCase):
    def test_upgrade_keeps_previous_accounts_stock_history_and_original_pdf(self):
        old_targets = [("accounts", "0002_login_limits"), ("inventory", "0010_document_identity")]
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate(old_targets)
            old = executor.loader.project_state(old_targets).apps
            User = old.get_model("accounts", "User")
            Location = old.get_model("inventory", "Location")
            Reference = old.get_model("inventory", "Reference")
            Movement = old.get_model("inventory", "Movement")
            Line = old.get_model("inventory", "MovementLine")
            Document = old.get_model("inventory", "Document")
            actor = User.objects.create(
                username="migration-fictitious-admin",
                role="admin",
                is_active=True,
                password="!unusable",
            )
            location = Location.objects.create(name="Local histórico fictício")
            reference = Reference.objects.create(
                code="OLD-SYN",
                name="Referência anterior fictícia",
                current_stock=13,
                box_capacity=6,
                location=location,
            )
            movement = Movement.objects.create(
                kind="exit",
                created_by=actor,
                date=date(2025, 1, 2),
                person_name="Cliente original fictício",
                reason="Observação original fictícia",
            )
            line = Line.objects.create(
                movement=movement,
                reference=reference,
                quantity=-2,
                stock_before=15,
                stock_after=13,
                reference_name=reference.name,
                box_capacity=6,
                units=2,
            )
            output = io.BytesIO()
            canvas = Canvas(output)
            canvas.drawString(50, 800, "Exemplar anterior ficticio")
            canvas.save()
            payload = output.getvalue()
            metadata = {"presentation": 2, "legacy_number": "MOV-synthetic-original"}
            document = Document.objects.create(
                movement=movement,
                kind="pdf",
                payload=payload,
                sha256=hashlib.sha256(payload).hexdigest(),
                byte_size=len(payload),
                content_type="application/pdf",
                storage_key="old-synthetic-original.pdf",
                metadata=metadata,
            )
            movement.status = "confirmed"
            movement.save(update_fields=["status"])
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            from accounts.models import AccessProfile
            from accounts.models import User as CurrentUser
            from inventory.documents import verified_bytes
            from inventory.models import (
                Document as CurrentDocument,
            )
            from inventory.models import (
                Movement as CurrentMovement,
            )
            from inventory.models import (
                Reference as CurrentReference,
            )
            from inventory.models import (
                ReportNumber,
            )

            self.assertEqual(CurrentUser.objects.get(pk=actor.pk).role, "admin")
            self.assertIsNone(CurrentUser.objects.get(pk=actor.pk).access_profile_id)
            self.assertEqual(CurrentReference.objects.get(pk=reference.pk).current_stock, 13)
            current = CurrentDocument.objects.get(pk=document.pk)
            self.assertEqual(verified_bytes(current), payload)
            self.assertEqual(current.metadata, metadata)
            self.assertEqual(CurrentMovement.objects.get(pk=movement.pk).date, date(2025, 1, 2))
            self.assertEqual(CurrentMovement.objects.get(pk=movement.pk).lines.get().quantity, -2)
            self.assertEqual(CurrentMovement.objects.get(pk=movement.pk).lines.get().pk, line.pk)
            self.assertFalse(ReportNumber.objects.exists())
            self.assertTrue(AccessProfile.objects.filter(name="Substituto", active=True).exists())
        finally:
            MigrationExecutor(connection).migrate(latest)
