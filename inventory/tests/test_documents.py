import hashlib
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from pypdf import PdfReader

from inventory import operations
from inventory.documents import DocumentIntegrityError, validate_signature, verified_bytes
from inventory.models import AuditEvent, Document, Location, Reference
from inventory.services import confirm_movement
from tests.document_fixtures import confirmed_operation, signature_png


class DocumentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(username="docs-synthetic", role="admin")
        cls.location = Location.objects.create(name="Local documental sintético")
        cls.destination = Location.objects.create(name="Destino documental sintético")
        cls.ref = Reference.objects.create(
            code="PDF-SYN",
            name="Garrafa histórica sintética",
            box_capacity=6,
            current_stock=50,
            location=cls.location,
        )

    def pdf(self, movement):
        document = movement.documents.get(kind="pdf")
        payload = verified_bytes(document)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), document.sha256)
        reader = PdfReader(io.BytesIO(payload))
        self.assertEqual(tuple(round(float(v)) for v in reader.pages[0].mediabox), (0, 0, 595, 842))
        return document, payload, "\n".join(page.extract_text() for page in reader.pages)

    def test_entry_report_optional_no_does_not_create_document(self):
        movement = confirmed_operation(self.admin, self.ref, kind="entry", report=False)
        self.assertEqual(movement.status, "confirmed")
        self.assertFalse(movement.documents.exists())
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 52)

    def test_entry_yes_creates_private_a4_pdf_with_historical_fields(self):
        movement = confirmed_operation(self.admin, self.ref, kind="entry", report=True)
        document, payload, text = self.pdf(movement)
        self.assertIn("Garrafa histórica sintética", text)
        self.assertIn("Pessoa documental sintética", text)
        self.assertIn("docs-synthetic", text)
        self.assertIn("PDF-SYN", text)
        self.assertEqual(document.metadata["lines"][0]["capacity"], 6)
        self.assertEqual(document.content_type, "application/pdf")
        self.assertTrue(
            AuditEvent.objects.filter(action="document.created", movement=movement).exists()
        )

    def test_exit_always_generates_report_and_simple_never_signature(self):
        movement = confirmed_operation(self.admin, self.ref)
        _, _, text = self.pdf(movement)
        self.assertIn("confirmação simples", text)
        self.assertTrue(movement.report_requested)
        self.assertFalse(movement.documents.filter(kind="signature").exists())

    def test_signed_exit_stores_valid_png_and_embeds_image(self):
        movement = confirmed_operation(self.admin, self.ref, signed=True)
        document, payload, text = self.pdf(movement)
        self.assertEqual(movement.validation, "signed")
        signature = movement.documents.get(kind="signature")
        self.assertTrue(verified_bytes(signature).startswith(b"\x89PNG"))
        self.assertIn("não constitui assinatura digital qualificada", text)
        self.assertTrue(any(list(page.images) for page in PdfReader(io.BytesIO(payload)).pages))
        self.assertEqual(document.metadata["validation"], "signed")

    def test_inventory_includes_counts_difference_reason_before_after_and_transfer(self):
        movement = confirmed_operation(
            self.admin, self.ref, kind="inventory", units=48, location=self.destination
        )
        document, _, text = self.pdf(movement)
        self.assertIn("Contagem", text)
        self.assertIn("Transferência PDF-SYN", text)
        self.assertIn("Destino documental sintético", text)
        line = document.metadata["lines"][0]
        self.assertEqual(
            (line["counted"], line["before"], line["quantity"], line["after"]), (48, 50, -2, 48)
        )

    def test_pdf_bytes_unchanged_after_catalogue_person_or_user_edit(self):
        movement = confirmed_operation(self.admin, self.ref, report=True)
        document, before, _ = self.pdf(movement)
        self.ref.name = "Nome posterior sintético"
        self.ref.box_capacity = 12
        self.ref.save()
        movement.person.name = "Pessoa posterior sintética"
        movement.person.save()
        self.admin.username = "Conta posterior sintética"
        self.admin.save()
        document.refresh_from_db()
        self.assertEqual(verified_bytes(document), before)
        self.assertNotIn("posterior", self.pdf(movement)[2])

    def test_pdf_preserves_exact_noncanonical_boxes_and_units(self):
        draft = operations.create_draft(actor=self.admin, kind="entry", references=[self.ref])
        draft = operations.save_draft(
            draft.pk,
            actor=self.admin,
            revision=0,
            header={"person_name": "Pessoa sintética"},
            rows=[{"id": draft.lines.get().pk, "boxes": 1, "units": 8}],
        )
        reviewed, _ = operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)
        movement = confirm_movement(
            draft.pk, actor=self.admin, review_token=reviewed.review_token, report_requested=True
        )
        line = movement.documents.get(kind="pdf").metadata["lines"][0]
        self.assertEqual((line["boxes"], line["units"], line["quantity"]), (1, 8, 14))

    def test_unknown_capacity_and_blank_boxes_preserved_in_pdf(self):
        self.ref.box_capacity = None
        self.ref.save()
        movement = confirmed_operation(self.admin, self.ref)
        document, _, text = self.pdf(movement)
        self.assertIsNone(document.metadata["lines"][0]["capacity"])
        self.assertIsNone(document.metadata["lines"][0]["boxes"])
        self.assertIn("por definir", text)

    def test_invalid_or_blank_oversized_or_wrong_type_signature_rejected(self):
        for value in (
            None,
            "",
            "data:image/svg+xml;base64,PHN2Zz4=",
            "data:image/png;base64,!!!!",
            signature_png(blank=True),
            signature_png(size=(50, 50)),
            signature_png(size=(2050, 50)),
            "data:image/png;base64," + "A" * 400000,
        ):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValidationError):
                validate_signature(value)

    def test_invalid_signature_rolls_back_stock_and_documents(self):
        draft = operations.create_draft(actor=self.admin, kind="exit", references=[self.ref])
        draft = operations.save_draft(
            draft.pk,
            actor=self.admin,
            revision=0,
            header={"person_name": "Pessoa"},
            rows=[{"id": draft.lines.get().pk, "units": 2}],
        )
        reviewed, _ = operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)
        with self.assertRaises(ValidationError):
            confirm_movement(
                draft.pk,
                actor=self.admin,
                review_token=reviewed.review_token,
                validation="signed",
                signature_data=signature_png(blank=True),
            )
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 50)
        self.assertFalse(Document.objects.exists())
        self.assertFalse(draft.audit_events.filter(action="movement.confirmed").exists())

    def test_pdf_failure_rolls_back_stock_signature_audit_and_confirmation(self):
        draft = operations.create_draft(actor=self.admin, kind="exit", references=[self.ref])
        draft = operations.save_draft(
            draft.pk,
            actor=self.admin,
            revision=0,
            header={"person_name": "Pessoa"},
            rows=[{"id": draft.lines.get().pk, "units": 2}],
        )
        reviewed, _ = operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)
        with (
            patch("inventory.documents.render_pdf", side_effect=RuntimeError("Synthetic failure")),
            self.assertRaises(RuntimeError),
        ):
            confirm_movement(
                draft.pk,
                actor=self.admin,
                review_token=reviewed.review_token,
                validation="signed",
                signature_data=signature_png(),
            )
        self.ref.refresh_from_db()
        draft.refresh_from_db()
        self.assertEqual((self.ref.current_stock, draft.status), (50, "draft"))
        self.assertFalse(Document.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action="document.created").exists())
        self.assertIsNone(draft.lines.get().stock_before)

    def test_document_corruption_fails_integrity_check(self):
        movement = confirmed_operation(self.admin, self.ref)
        document = movement.documents.get()
        document.payload = b"corrupted"
        with self.assertRaises(DocumentIntegrityError):
            verified_bytes(document)

    def test_confirmed_documents_are_immutable_through_orm_and_sql(self):
        movement = confirmed_operation(self.admin, self.ref)
        document = movement.documents.get()
        with self.assertRaises(ValidationError):
            document.save()
        with self.assertRaises(ValidationError):
            document.delete()
        with self.assertRaises(ValidationError):
            movement.documents.update(payload=b"rewritten")
        if connection.vendor == "postgresql":
            for statement in (
                "UPDATE inventory_document SET sha256='fake' WHERE id=%s",
                "DELETE FROM inventory_document WHERE id=%s",
            ):
                with (
                    self.assertRaises(IntegrityError),
                    transaction.atomic(),
                    connection.cursor() as cursor,
                ):
                    cursor.execute(statement, [document.pk])

    def test_related_correction_preserves_original_pdf(self):
        original = confirmed_operation(self.admin, self.ref)
        before = verified_bytes(original.documents.get())
        self.ref.refresh_from_db()
        draft = operations.create_draft(
            actor=self.admin,
            kind="inventory",
            references=[self.ref],
            correction_of=original,
            reason="Correção sintética",
        )
        draft = operations.save_draft(
            draft.pk,
            actor=self.admin,
            revision=0,
            header={"reason": "Correção sintética"},
            rows=[{"id": draft.lines.get().pk, "units": 49}],
        )
        reviewed, _ = operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)
        correction = confirm_movement(
            draft.pk, actor=self.admin, review_token=reviewed.review_token
        )
        self.assertEqual(verified_bytes(original.documents.get()), before)
        self.assertEqual(correction.documents.get().metadata["correction_of"], original.pk)

    def test_large_multi_page_report_has_repeated_header_and_all_references(self):
        references = [
            Reference.objects.create(
                code=f"PDF-{i:03}",
                name="Referência sintética longa " * 3 + str(i),
                location=self.location,
                current_stock=4,
            )
            for i in range(70)
        ]
        draft = operations.create_draft(actor=self.admin, kind="exit", references=references)
        draft = operations.save_draft(
            draft.pk,
            actor=self.admin,
            revision=0,
            header={"person_name": "Pessoa multipágina"},
            rows=[{"id": line.pk, "units": 1} for line in draft.lines.all()],
        )
        reviewed, _ = operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)
        movement = confirm_movement(draft.pk, actor=self.admin, review_token=reviewed.review_token)
        document, payload, text = self.pdf(movement)
        self.assertGreater(len(PdfReader(io.BytesIO(payload)).pages), 1)
        self.assertEqual(len(document.metadata["lines"]), 70)
        self.assertIn("PDF-069", text)
        self.assertTrue(
            all(
                "Stock final" in page.extract_text()
                for page in PdfReader(io.BytesIO(payload)).pages
            )
        )
