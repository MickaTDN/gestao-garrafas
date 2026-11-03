from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature

from consultation.test_sheets import SheetFixtures
from inventory import operations
from inventory.models import Movement, Reference
from inventory.proposals import add_to_entry, remove_from_entry
from inventory.services import confirm_movement


class DirectEntryProposalTests(SheetFixtures, TestCase):
    def setUp(self):
        self.prepare()
        self.data = {
            "name": "Proposta direta fictícia",
            "box_capacity": 6,
            "location": self.ref.location,
            "sector": None,
            "boxes": 2,
            "units": 3,
        }
        self.draft = operations.create_draft(actor=self.admin, kind="entry")
        self.draft = operations.save_draft(
            self.draft.pk, actor=self.admin, revision=0, header={"person_name": "Pessoa fictícia"}
        )

    def added(self):
        self.draft.refresh_from_db()
        return add_to_entry(
            self.draft.pk, actor=self.admin, revision=self.draft.revision, data=self.data
        )

    def test_quantities_and_auto_code_materialize_only_after_explicit_confirmation(self):
        draft = self.added()
        self.assertEqual(Reference.objects.count(), 1)
        reviewed, _ = operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)
        self.assertEqual(Reference.objects.count(), 1)
        result = confirm_movement(
            draft.pk, actor=self.admin, review_token=reviewed.review_token, report_requested=True
        )
        ref = Reference.objects.exclude(pk=self.ref.pk).get()
        self.assertEqual(ref.current_stock, 15)
        self.assertEqual((result.lines.get().boxes, result.lines.get().units), (2, 3))
        with self.assertRaises(ValidationError):
            confirm_movement(
                draft.pk,
                actor=self.admin,
                review_token=reviewed.review_token,
                report_requested=True,
            )
        self.assertEqual(Reference.objects.count(), 2)

    def test_failure_after_materialization_rolls_back_new_reference_and_stock(self):
        draft = self.added()
        reviewed, _ = operations.review_draft(draft.pk, actor=self.admin, revision=draft.revision)
        with patch("inventory.documents.render_pdf", side_effect=RuntimeError("Synthetic failure")):
            with self.assertRaises(RuntimeError):
                confirm_movement(
                    draft.pk,
                    actor=self.admin,
                    review_token=reviewed.review_token,
                    report_requested=True,
                )
        self.assertEqual(Reference.objects.count(), 1)
        self.assertFalse(Movement.objects.filter(status="confirmed").exists())
        self.assertFalse(self.draft.lines.exists())

    def test_edit_remove_cancel_and_permissions_never_create_stock_or_references(self):
        draft = self.added()
        line = draft.source_metadata["reference_proposals"][0]
        draft = add_to_entry(
            draft.pk,
            actor=self.admin,
            revision=draft.revision,
            data={**self.data, "proposal_id": line["reference_id"], "units": 4},
        )
        self.assertEqual(len(draft.source_metadata["reference_proposals"]), 1)
        draft = remove_from_entry(
            draft.pk, actor=self.admin, revision=draft.revision, identity=line["reference_id"]
        )
        self.assertEqual(draft.source_metadata["reference_proposals"], [])
        operations.cancel_draft(draft.pk, actor=self.admin, revision=draft.revision)
        with self.assertRaises(PermissionDenied):
            add_to_entry(draft.pk, actor=self.viewer, revision=draft.revision, data=self.data)
        self.assertEqual(Reference.objects.count(), 1)

    def test_unknown_capacity_empty_zero_duplicates_and_exit_are_rejected_safely(self):
        for changes in (
            {"boxes": None, "units": None},
            {"boxes": 0, "units": 0},
            {"box_capacity": None},
            {"name": "  REFERÊNCIA SINTÉTICA "},
        ):
            with self.subTest(changes=list(changes)), self.assertRaises(ValidationError):
                add_to_entry(
                    self.draft.pk,
                    actor=self.admin,
                    revision=self.draft.revision,
                    data={**self.data, **changes},
                )
        self.data.update(box_capacity=None, boxes=None, units=3)
        self.added()
        out = operations.create_draft(actor=self.admin, kind="exit")
        with self.assertRaises(ValidationError):
            add_to_entry(out.pk, actor=self.admin, revision=0, data=self.data)
        self.assertEqual(Reference.objects.count(), 1)

    def test_existing_custom_entry_and_catalogue_permissions_are_preserved(self):
        from accounts.models import AccessProfile, User

        profile = AccessProfile.objects.create(
            name="Entrada e catálogo fictícios", capabilities=["entry", "catalog_manage"]
        )
        user = User.objects.create_user(
            username="synthetic-proposal-custom", role="custom", access_profile=profile
        )
        draft = operations.create_draft(actor=user, kind="entry")
        draft = operations.save_draft(
            draft.pk, actor=user, revision=0, header={"person_name": "Pessoa fictícia"}
        )
        draft = add_to_entry(draft.pk, actor=user, revision=draft.revision, data=self.data)
        reviewed, _ = operations.review_draft(draft.pk, actor=user, revision=draft.revision)
        confirm_movement(
            draft.pk, actor=user, review_token=reviewed.review_token, report_requested=False
        )
        self.assertEqual(Reference.objects.count(), 2)
        # This grants no access to the administrative pending-sheet workflow.
        from accounts.permissions import require_access

        with self.assertRaises(PermissionDenied):
            require_access(user, "admin")


@skipUnlessDBFeature("has_select_for_update")
class DirectProposalConcurrencyTests(SheetFixtures, TransactionTestCase):
    def setUp(self):
        self.prepare()

    def test_two_different_entries_cannot_allocate_duplicate_designations(self):
        drafts = []
        for name in ("Proposta concorrente", "  PROPOSTA   CONCORRENTE "):
            draft = operations.create_draft(actor=self.admin, kind="entry")
            draft = operations.save_draft(
                draft.pk,
                actor=self.admin,
                revision=0,
                header={"person_name": "Pessoa fictícia concorrente"},
            )
            draft = add_to_entry(
                draft.pk,
                actor=self.admin,
                revision=draft.revision,
                data={
                    "name": name,
                    "location": self.ref.location,
                    "box_capacity": None,
                    "boxes": None,
                    "units": 3,
                },
            )
            reviewed, _ = operations.review_draft(
                draft.pk, actor=self.admin, revision=draft.revision
            )
            drafts.append(reviewed)
        barrier = Barrier(2)

        def worker(draft):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return confirm_movement(
                        draft.pk,
                        actor=self.admin,
                        review_token=draft.review_token,
                        report_requested=False,
                    ).pk
                except ValidationError:
                    return "blocked"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, drafts))
        self.assertEqual(results.count("blocked"), 1)
        self.assertEqual(Reference.objects.count(), 2)
        self.assertEqual(Movement.objects.filter(status="confirmed").count(), 1)
        self.assertEqual(Reference.objects.exclude(pk=self.ref.pk).get().current_stock, 3)
