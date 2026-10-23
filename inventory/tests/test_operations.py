"""Synthetic lifecycle, stock invariants, physical counts and audit contracts."""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from inventory import catalog, operations
from inventory.models import AuditEvent, Location, LocationChange, Reference, Sector
from inventory.services import confirm_movement, reference_state


class OperationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(username="ops-admin", role="admin")
        cls.other = get_user_model().objects.create_user(username="ops-other", role="admin")
        cls.viewer = get_user_model().objects.create_user(username="ops-viewer")
        cls.location = Location.objects.create(name="Operações sintéticas")
        cls.destination = Location.objects.create(name="Destino sintético")
        cls.sector = Sector.objects.create(name="Setor sintético", location=cls.destination)
        cls.first = Reference.objects.create(
            code="OPS-1",
            name="Produto sintético um",
            location=cls.location,
            box_capacity=6,
            current_stock=20,
        )
        cls.second = Reference.objects.create(
            code="OPS-2", name="Produto sintético dois", location=cls.location, current_stock=10
        )

    def draft(self, kind="entry", refs=None, **kwargs):
        return operations.create_draft(
            actor=self.admin, kind=kind, references=refs or [self.first], **kwargs
        )

    def fill(self, draft, counts=None, **kwargs):
        draft.refresh_from_db()
        rows = []
        for line, (boxes, units) in zip(
            draft.lines.order_by("reference_id"), counts or [(1, 2)], strict=True
        ):
            rows.append(
                {
                    "id": line.pk,
                    "boxes": boxes,
                    "units": units,
                    "reason": kwargs.pop("line_reason", "Contagem sintética"),
                    "target_location": kwargs.get("target_location", line.target_location),
                    "target_sector": kwargs.get("target_sector", line.target_sector),
                }
            )
        return operations.save_draft(
            draft.pk,
            actor=self.admin,
            revision=draft.revision,
            header={"person_name": "Pessoa sintética", "reason": draft.reason},
            rows=rows,
            recheck=kwargs.get("recheck", False),
        )

    def confirm(self, draft, **kwargs):
        draft.refresh_from_db()
        reviewed, plans = operations.review_draft(
            draft.pk, actor=self.admin, revision=draft.revision
        )
        return confirm_movement(
            draft.pk,
            actor=self.admin,
            review_token=reviewed.review_token,
            report_requested=kwargs.get("report_requested", False),
        )

    def stock(self, ref=None):
        return Reference.objects.get(pk=(ref or self.first).pk).current_stock

    def test_entry_single_reference_preserves_noncanonical_input_and_snapshot(self):
        draft = self.fill(self.draft(), [(1, 8)])
        confirmed = self.confirm(draft, report_requested=True)
        line = confirmed.lines.get()
        self.assertEqual((line.boxes, line.units, line.box_capacity, line.quantity), (1, 8, 6, 14))
        self.assertEqual((line.stock_before, line.stock_after, self.stock()), (20, 34, 34))
        self.assertTrue(confirmed.report_requested)
        self.assertEqual(confirmed.confirmed_by, self.admin)
        self.assertFalse(confirmed.documents.exists())

    def test_entry_multiple_references_and_unknown_capacity(self):
        draft = self.fill(self.draft(refs=[self.first, self.second]), [(2, None), (None, 3)])
        self.confirm(draft)
        self.assertEqual((self.stock(), self.stock(self.second)), (32, 13))
        line = draft.lines.get(reference=self.second)
        self.assertIsNone(line.boxes)
        self.assertIsNone(line.box_capacity)

    def test_exit_single_reference_requires_simple_review_and_mandatory_report(self):
        draft = self.fill(self.draft("exit"), [(1, 2)])
        self.confirm(draft)
        draft.refresh_from_db()
        self.assertEqual(
            (self.stock(), draft.validation, draft.lines.get().quantity), (12, "simple", -8)
        )
        self.assertTrue(draft.report_requested)
        self.assertFalse(draft.documents.exists())

    def test_exit_multiple_references(self):
        self.confirm(self.fill(self.draft("exit", [self.first, self.second]), [(1, 2), (0, 4)]))
        self.assertEqual((self.stock(), self.stock(self.second)), (12, 6))

    def test_unknown_capacity_boxes_rejected(self):
        draft = self.draft(refs=[self.second])
        with self.assertRaisesMessage(ValidationError, "Capacidade"):
            self.fill(draft, [(1, 0)])
        self.assertEqual(self.stock(self.second), 10)

    def test_unknown_capacity_explicit_zero_boxes_and_units_accepted(self):
        self.confirm(self.fill(self.draft(refs=[self.second]), [(0, 2)]))
        self.assertEqual(self.stock(self.second), 12)

    def test_empty_quantities_preserved_on_save_and_cannot_confirm(self):
        draft = self.fill(self.draft(), [(None, None)])
        line = draft.lines.get()
        self.assertEqual((line.boxes, line.units, line.quantity), (None, None, None))
        with self.assertRaises(ValidationError):
            self.confirm(draft)
        self.assertEqual(self.stock(), 20)

    def test_zero_entry_or_exit_cannot_confirm(self):
        for kind in ("entry", "exit"):
            with self.subTest(kind=kind):
                draft = self.fill(self.draft(kind), [(0, None)])
                self.assertEqual(draft.lines.get().boxes, 0)
                with self.assertRaises(ValidationError):
                    self.confirm(draft)
        self.assertEqual(self.stock(), 20)

    def test_negative_fractional_bool_or_oversized_quantities_rejected(self):
        for invalid in (-1, 0.5, True, 2147483648):
            with self.subTest(value=invalid), self.assertRaises(ValidationError):
                self.fill(self.draft(), [(None, invalid)])
        self.assertEqual(self.stock(), 20)

    def test_draft_edit_and_cancel_never_affect_stock_or_create_quantitative_audit(self):
        draft = self.fill(self.draft(), [(None, 3)])
        draft = self.fill(draft, [(0, None)])
        operations.cancel_draft(draft.pk, actor=self.admin, revision=draft.revision)
        draft.refresh_from_db()
        self.assertEqual((self.stock(), draft.status), (20, "cancelled"))
        self.assertIsNone(draft.lines.get().stock_before)
        self.assertEqual(
            set(draft.audit_events.values_list("action", flat=True)),
            {"movement.created", "movement.draft_saved", "movement.cancelled"},
        )
        with self.assertRaises(ValidationError):
            self.confirm(draft)
        with self.assertRaises(ValidationError):
            self.fill(draft)

    def test_stale_revision_cannot_overwrite_or_cancel(self):
        draft = self.fill(self.draft())
        for operation in (
            lambda: operations.save_draft(draft.pk, actor=self.admin, revision=0, header={}),
            lambda: operations.cancel_draft(draft.pk, actor=self.admin, revision=0),
        ):
            with self.assertRaisesMessage(ValidationError, "noutra janela"):
                operation()

    def test_person_required_but_incomplete_draft_allowed(self):
        draft = self.draft()
        operations.save_draft(
            draft.pk,
            actor=self.admin,
            revision=0,
            header={},
            rows=[{"id": draft.lines.get().pk, "units": 1}],
        )
        with self.assertRaisesMessage(ValidationError, "pessoa"):
            self.confirm(draft)

    def test_repeated_confirmation_cannot_change_stock_twice(self):
        draft = self.fill(self.draft())
        confirmed = self.confirm(draft)
        with self.assertRaises(ValidationError):
            confirm_movement(
                draft.pk,
                actor=self.admin,
                review_token=confirmed.review_token,
                report_requested=False,
            )
        self.assertEqual(self.stock(), 28)
        self.assertEqual(draft.audit_events.filter(action="movement.confirmed").count(), 1)

    def test_review_required_and_entry_report_choice_explicit(self):
        draft = self.fill(self.draft())
        with self.assertRaises(ValidationError):
            confirm_movement(draft.pk, actor=self.admin, report_requested=False)
        reviewed, _ = operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)
        with self.assertRaisesMessage(ValidationError, "relatório"):
            confirm_movement(draft.pk, actor=self.admin, review_token=reviewed.review_token)

    def test_edit_invalidates_review_token(self):
        draft = self.fill(self.draft())
        reviewed, _ = operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)
        self.fill(draft, [(None, 1)])
        with self.assertRaises(ValidationError):
            confirm_movement(
                draft.pk,
                actor=self.admin,
                review_token=reviewed.review_token,
                report_requested=False,
            )
        self.assertEqual(self.stock(), 20)

    def test_exit_stock_changes_after_review_revalidated_and_insufficient_second_line_rolls_back(
        self,
    ):
        draft = self.fill(self.draft("exit", [self.first, self.second]), [(0, 2), (0, 9)])
        reviewed, _ = operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)
        self.confirm(self.fill(self.draft("exit", [self.second]), [(None, 3)]))
        with self.assertRaises(ValidationError):
            confirm_movement(draft.pk, actor=self.admin, review_token=reviewed.review_token)
        self.assertEqual((self.stock(), self.stock(self.second)), (20, 7))
        self.assertFalse(draft.lines.filter(stock_before__isnull=False).exists())

    def test_inactive_reference_rejected_at_selection_and_confirmation(self):
        self.first.active = False
        self.first.save()
        with self.assertRaises(ValidationError):
            self.draft()
        self.first.active = True
        self.first.save()
        draft = self.fill(self.draft())
        self.first.active = False
        self.first.save()
        with self.assertRaises(ValidationError):
            self.confirm(draft)
        self.assertEqual(self.stock(), 20)

    def test_reactivation_preserves_identity_and_duplicate_guard(self):
        self.second.active = False
        self.second.save()
        original_code = self.second.code
        with self.assertRaises(catalog.DuplicateReferenceError):
            catalog.save_reference(
                actor=self.admin,
                data={"name": "  PRODUTO   SINTÉTICO DOIS ", "location": self.destination},
            )
        catalog.set_reference_active(actor=self.admin, reference_id=self.second.pk, active=True)
        self.second.refresh_from_db()
        self.assertEqual(self.second.code, original_code)
        self.confirm(self.fill(self.draft(refs=[self.second]), [(None, 2)]))
        self.assertEqual(Reference.objects.count(), 2)

    def test_partial_inventory_positive_negative_and_zero_differences(self):
        for count in (25, 17, 17):
            with self.subTest(count=count):
                draft = self.fill(self.draft("inventory"), [(None, count)])
                before = self.stock()
                self.confirm(draft)
                line = draft.lines.get()
                self.assertEqual(
                    (line.counted_quantity, line.quantity, line.stock_before, line.stock_after),
                    (count, count - before, before, count),
                )
        self.assertEqual(self.stock(self.second), 10)

    def test_inventory_boxes_represent_physical_count_not_adjustment(self):
        draft = self.fill(self.draft("inventory"), [(2, 1)])
        self.confirm(draft)
        line = draft.lines.get()
        self.assertEqual(
            (line.boxes, line.units, line.counted_quantity, line.quantity), (2, 1, 13, -7)
        )

    def test_full_inventory_requires_every_reference_counted(self):
        draft = operations.create_draft(actor=self.admin, kind="inventory", inventory_scope="full")
        self.assertEqual(draft.lines.count(), 2)
        with self.assertRaisesMessage(ValidationError, "ainda não contado"):
            self.confirm(draft)
        self.assertEqual((self.stock(), self.stock(self.second)), (20, 10))
        self.confirm(self.fill(draft, [(None, 0), (None, 10)]))
        self.assertEqual((self.stock(), self.stock(self.second)), (0, 10))

    def test_explicit_zero_count_distinct_from_empty(self):
        draft = self.fill(self.draft("inventory"), [(None, None)])
        self.assertIsNone(draft.lines.get().counted_quantity)
        with self.assertRaises(ValidationError):
            self.confirm(draft)
        self.confirm(self.fill(draft, [(None, 0)]))
        self.assertEqual(self.stock(), 0)
        self.assertIsNone(draft.lines.get().boxes)
        self.assertEqual(draft.lines.get().units, 0)

    def test_inventory_difference_requires_reason_and_zero_does_not(self):
        draft = self.fill(self.draft("inventory"), [(None, 19)], line_reason="")
        with self.assertRaisesMessage(ValidationError, "motivo"):
            self.confirm(draft)
        draft = self.fill(draft, [(None, 20)], line_reason="")
        self.confirm(draft)
        self.assertEqual(self.stock(), 20)

    def test_inventory_conflict_requires_explicit_recheck_even_when_count_unchanged(self):
        draft = self.fill(self.draft("inventory"), [(None, 20)])
        self.confirm(self.fill(self.draft(), [(None, 2)]))
        with self.assertRaisesMessage(ValidationError, "stock na contagem 20, stock atual 22"):
            self.confirm(draft)
        self.fill(draft, [(None, 20)])
        with self.assertRaises(ValidationError):
            self.confirm(draft)
        self.confirm(self.fill(draft, [(None, 20)], recheck=True))
        self.assertEqual(self.stock(), 20)
        self.assertEqual(draft.lines.get().quantity, -2)

    def test_inventory_detects_stock_changed_then_restored(self):
        draft = self.fill(self.draft("inventory"), [(None, 20)])
        self.confirm(self.fill(self.draft(), [(None, 1)]))
        self.confirm(self.fill(self.draft("exit"), [(None, 1)]))
        self.assertEqual(self.stock(), 20)
        with self.assertRaises(ValidationError):
            self.confirm(draft)

    def test_location_change_with_no_quantity_difference_audited(self):
        draft = self.fill(
            self.draft("inventory"),
            [(None, 20)],
            target_location=self.destination,
            target_sector=self.sector,
            line_reason="Transferência sintética",
        )
        self.assertFalse(LocationChange.objects.exists())
        self.confirm(draft)
        self.first.refresh_from_db()
        self.assertEqual(
            (self.first.location_id, self.first.sector_id, self.first.current_stock),
            (self.destination.pk, self.sector.pk, 20),
        )
        self.assertEqual(draft.lines.get().quantity, 0)
        self.assertEqual(draft.location_changes.get().reason, "Transferência sintética")
        self.assertTrue(
            AuditEvent.objects.filter(action="movement.location_changed", movement=draft).exists()
        )

    def test_sector_mismatch_rejected_before_any_stock_or_location_change(self):
        draft = self.draft("inventory")
        with self.assertRaises(ValidationError):
            self.fill(draft, [(None, 22)], target_sector=self.sector)
        self.assertEqual(self.stock(), 20)
        self.assertFalse(LocationChange.objects.exists())

    def test_capacity_change_since_draft_requires_editing_and_review(self):
        draft = self.fill(self.draft())
        Reference.objects.filter(pk=self.first.pk).update(box_capacity=12)
        with self.assertRaisesMessage(ValidationError, "capacidade mudou"):
            self.confirm(draft)
        self.confirm(self.fill(draft))
        self.assertEqual(self.stock(), 34)

    def test_correction_is_new_related_count_adjustment_preserving_original(self):
        original = self.confirm(self.fill(self.draft(), [(None, 4)]))
        original_line = original.lines.get()
        draft = self.draft(
            "inventory", correction_of=original, reason="Corrigir contagem sintética"
        )
        self.confirm(self.fill(draft, [(None, 22)]))
        original_line.refresh_from_db()
        self.assertEqual((original_line.quantity, original_line.stock_after), (4, 24))
        self.assertEqual((draft.lines.get().quantity, self.stock()), (-2, 22))
        self.assertEqual(draft.correction_of_id, original.pk)
        self.assertEqual(
            draft.audit_events.get(action="movement.confirmed").details["correction_of"],
            original.pk,
        )

    def test_correction_requires_reason_and_original_reference(self):
        original = self.confirm(self.fill(self.draft()))
        with self.assertRaises(ValidationError):
            self.draft("inventory", correction_of=original)
        with self.assertRaises(ValidationError):
            self.draft("inventory", [self.second], correction_of=original, reason="Motivo")

    def test_other_admin_and_viewer_cannot_edit_review_cancel_confirm_owned_draft(self):
        draft = self.fill(self.draft())
        for actor in (self.other, self.viewer):
            for action in (
                lambda: operations.save_draft(
                    draft.pk, actor=actor, revision=draft.revision, header={}
                ),
                lambda: operations.review_draft(draft.pk, actor=actor, revision=draft.revision),
                lambda: operations.cancel_draft(draft.pk, actor=actor, revision=draft.revision),
                lambda: confirm_movement(draft.pk, actor=actor),
            ):
                with self.subTest(actor=actor.pk), self.assertRaises(PermissionDenied):
                    action()
        with self.assertRaises(PermissionDenied):
            operations.create_draft(actor=self.viewer, kind="entry")
        self.assertEqual(self.stock(), 20)

    def test_signed_validation_is_unavailable_even_with_forged_document(self):
        draft = self.fill(self.draft("exit"))
        draft.validation = "signed"
        draft.save()
        with self.assertRaisesMessage(ValidationError, "Etapa 4"):
            confirm_movement(draft.pk, actor=self.admin)

    def test_forged_line_id_or_inactive_add_and_full_remove_rejected(self):
        draft = self.draft()
        with self.assertRaises(ValidationError):
            operations.save_draft(
                draft.pk, actor=self.admin, revision=0, header={}, rows=[{"id": 999999, "units": 1}]
            )
        self.second.active = False
        self.second.save()
        with self.assertRaises(ValidationError):
            operations.save_draft(
                draft.pk, actor=self.admin, revision=0, header={}, add_ids=[self.second.pk]
            )
        full = self.draft("inventory", inventory_scope="full")
        with self.assertRaises(ValidationError):
            operations.save_draft(
                full.pk, actor=self.admin, revision=0, header={}, remove_ids=[full.lines.get().pk]
            )

    def test_signed_count_basis_cannot_accept_stock_changed_while_counting(self):
        draft = self.draft("inventory")
        basis = reference_state(self.first)
        self.confirm(self.fill(self.draft(), [(None, 2)]))
        with self.assertRaises(ValidationError):
            operations.save_draft(
                draft.pk,
                actor=self.admin,
                revision=0,
                header={},
                rows=[{"id": draft.lines.get().pk, "units": 20, "basis": basis}],
            )
        self.assertIsNone(draft.lines.get().counted_quantity)
        self.assertEqual(self.stock(), 22)
