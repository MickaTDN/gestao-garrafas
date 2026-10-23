from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from inventory import operations
from inventory.models import AuditEvent, Location, Movement, Person, Reference, Sector
from inventory.services import confirm_movement


class OperationWebTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(username="webops-admin", role="admin")
        cls.other = get_user_model().objects.create_user(username="webops-other", role="admin")
        cls.viewer = get_user_model().objects.create_user(username="webops-viewer")
        cls.location = Location.objects.create(name="Local web sintético")
        cls.destination = Location.objects.create(name="Destino web sintético")
        cls.sector = Sector.objects.create(name="Setor web", location=cls.destination)
        cls.ref = Reference.objects.create(
            code="WEBOP-1",
            name="Garrafa web sintética",
            box_capacity=6,
            current_stock=10,
            location=cls.location,
        )
        cls.unknown = Reference.objects.create(
            code="WEBOP-2", name="Sem capacidade sintética", location=cls.location
        )
        cls.inactive = Reference.objects.create(
            code="WEBOP-3", name="Inativa sintética", active=False, location=cls.location
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def draft(self, kind="entry", **kwargs):
        return operations.create_draft(actor=self.admin, kind=kind, references=[self.ref], **kwargs)

    @staticmethod
    def payload(response):
        context = response.context
        initial = context["header"].initial
        data = {
            "revision": initial["revision"],
            "date": initial["date"].isoformat(),
            "person_name": "Pessoa web sintética",
            "reason": initial["reason"],
            "action": "save",
        }
        fs = context["formset"]
        data.update(
            {
                "form-TOTAL_FORMS": len(fs),
                "form-INITIAL_FORMS": len(fs),
                "form-MIN_NUM_FORMS": 0,
                "form-MAX_NUM_FORMS": 30,
            }
        )
        for index, form in enumerate(fs):
            for key, value in form.initial.items():
                data[f"form-{index}-{key}"] = "" if value is None else value
        return data

    def post_edit(self, draft, **changes):
        url = reverse("web:operation-edit", args=[draft.pk])
        data = self.payload(self.client.get(url))
        data.update(changes)
        return self.client.post(url, data)

    def reviewed(self, kind="entry"):
        draft = self.draft(kind)
        response = self.post_edit(draft, **{"form-0-units": 2, "action": "review"})
        self.assertRedirects(response, reverse("web:operation-review", args=[draft.pk]))
        draft.refresh_from_db()
        return draft

    def test_start_all_three_types_and_drafts_owned_only(self):
        for name in ("entry", "exit", "inventory"):
            self.assertEqual(self.client.post(reverse(f"web:{name}")).status_code, 302)
        foreign = operations.create_draft(actor=self.other, kind="entry")
        response = self.client.get(reverse("web:drafts"))
        self.assertEqual(response.context["page_obj"].paginator.count, 3)
        self.assertNotContains(response, reverse("web:operation-edit", args=[foreign.pk]))

    def test_quantity_fields_initially_blank_and_draft_reopens_preserving_blanks(self):
        draft = self.draft()
        response = self.client.get(reverse("web:operation-edit", args=[draft.pk]))
        self.assertContains(response, 'name="form-0-boxes"')
        self.assertNotContains(response, 'name="form-0-boxes" value="0"')
        self.assertNotContains(response, 'name="form-0-units" value="0"')
        self.post_edit(draft, **{"form-0-boxes": "", "form-0-units": "0"})
        line = draft.lines.get()
        self.assertEqual((line.boxes, line.units, line.quantity), (None, 0, 0))
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 10)

    def test_entry_review_requires_explicit_report_choice_and_confirmation(self):
        draft = self.reviewed()
        url = reverse("web:operation-review", args=[draft.pk])
        self.assertEqual(
            self.client.post(url, {"token": draft.review_token, "confirm": "on"}).status_code, 400
        )
        self.assertEqual(
            self.client.post(
                url, {"token": draft.review_token, "report_requested": "yes"}
            ).status_code,
            400,
        )
        response = self.client.post(
            url, {"token": draft.review_token, "confirm": "on", "report_requested": "yes"}
        )
        self.assertRedirects(response, reverse("web:operation-detail", args=[draft.pk]))
        draft.refresh_from_db()
        self.ref.refresh_from_db()
        self.assertTrue(draft.report_requested)
        self.assertEqual(self.ref.current_stock, 12)
        self.assertEqual(
            self.client.post(
                url, {"token": draft.review_token, "confirm": "on", "report_requested": "yes"}
            ).status_code,
            404,
        )
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 12)

    def test_exit_simple_only_and_report_metadata_stored(self):
        draft = self.reviewed("exit")
        response = self.client.get(reverse("web:operation-review", args=[draft.pk]))
        self.assertNotContains(response, 'value="signed"')
        self.client.post(
            reverse("web:operation-review", args=[draft.pk]),
            {
                "token": draft.review_token,
                "confirm": "on",
                "validation": "signed",
                "report_requested": "no",
            },
        )
        draft.refresh_from_db()
        self.assertEqual(draft.validation, "simple")
        self.assertTrue(draft.report_requested)
        self.assertFalse(draft.documents.exists())

    def test_forged_stock_quantity_status_kind_actor_and_line_totals_ignored(self):
        draft = self.draft()
        self.post_edit(
            draft,
            **{
                "form-0-boxes": 1,
                "form-0-units": 2,
                "form-0-quantity": 999,
                "current_stock": 999,
                "status": "confirmed",
                "kind": "exit",
                "created_by": self.other.pk,
                "validation": "signed",
                "workflow_version": 0,
            },
        )
        draft.refresh_from_db()
        self.ref.refresh_from_db()
        self.assertEqual(
            (draft.kind, draft.status, draft.created_by_id, draft.workflow_version),
            ("entry", "draft", self.admin.pk, 1),
        )
        self.assertEqual(
            (draft.lines.get().quantity, self.ref.current_stock, draft.validation), (8, 10, "")
        )

    def test_forged_row_id_or_basis_token_or_formset_truncation_rejected(self):
        for changes in (
            {"form-0-id": 99999},
            {"form-0-basis_token": "forged"},
            {"form-TOTAL_FORMS": 0},
            {"form-TOTAL_FORMS": 100000},
        ):
            with self.subTest(changes=changes):
                draft = self.draft()
                response = self.post_edit(draft, **changes)
                self.assertEqual(response.status_code, 400)
                self.assertIsNone(draft.lines.get().quantity)
                self.assertEqual(draft.audit_events.count(), 1)

    def test_negative_fractional_and_capacity_unknown_boxes_rejected(self):
        for value in (-2, "0.5"):
            with self.subTest(value=value):
                response = self.post_edit(self.draft(), **{"form-0-units": value})
                self.assertEqual(response.status_code, 400)
        draft = operations.create_draft(actor=self.admin, kind="entry", references=[self.unknown])
        self.assertContains(
            self.post_edit(draft, **{"form-0-boxes": 1}), "Capacidade", status_code=400
        )

    def test_search_add_multiple_refs_and_remove_before_review(self):
        draft = operations.create_draft(actor=self.admin, kind="entry")
        self.post_edit(draft, add_reference=[self.ref.pk, self.unknown.pk])
        self.assertEqual(draft.lines.count(), 2)
        self.post_edit(draft, **{"form-0-remove": "on", "form-1-units": 2})
        self.assertEqual(draft.lines.count(), 1)
        self.assertEqual(draft.lines.get().reference_id, self.unknown.pk)

    def test_inactive_search_warning_and_explicit_reactivation_keeps_original(self):
        draft = self.draft()
        url = reverse("web:operation-edit", args=[draft.pk])
        response = self.client.get(url, {"q": "WEBOP-3"})
        self.assertContains(response, "Esta referência já existe e está inativa")
        self.assertContains(response, self.inactive.code)
        self.assertContains(response, self.location.name)
        activation = reverse("web:operation-reactivate", args=[draft.pk, self.inactive.pk])
        self.assertEqual(self.client.get(activation).status_code, 200)
        self.inactive.refresh_from_db()
        self.assertFalse(self.inactive.active)
        self.assertEqual(self.client.post(activation).status_code, 400)
        self.client.post(activation, {"confirm": "yes"})
        self.inactive.refresh_from_db()
        self.assertTrue(self.inactive.active)
        self.assertEqual(self.inactive.code, "WEBOP-3")
        self.assertEqual(Reference.objects.count(), 3)

    def test_save_before_new_reference_and_duplicate_guard_across_locations(self):
        draft = self.draft()
        response = self.post_edit(draft, **{"form-0-units": 3, "action": "new-reference"})
        url = reverse("web:operation-reference", args=[draft.pk])
        self.assertRedirects(response, url)
        self.assertEqual(draft.lines.get().units, 3)
        response = self.client.post(
            url, {"name": "  INATIVA   SINTÉTICA ", "location": self.destination.pk}
        )
        self.assertContains(response, self.inactive.code, status_code=400)
        self.assertContains(response, "Rever reativação", status_code=400)
        self.assertEqual(Reference.objects.count(), 3)
        response = self.client.post(
            url,
            {
                "name": "Nova garrafa sintética",
                "location": self.location.pk,
                "box_capacity": 6,
                "current_stock": 888,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Reference.objects.get(name="Nova garrafa sintética").current_stock, 0)
        self.assertEqual(draft.lines.get().units, 3)

    def test_exit_inventory_cannot_create_or_reactivate_references_even_forged_requests(self):
        for kind in ("exit", "inventory"):
            with self.subTest(kind=kind):
                draft = self.draft(kind)
                self.assertNotContains(
                    self.client.get(reverse("web:operation-edit", args=[draft.pk])),
                    "Guardar e criar nova referência",
                )
                self.assertEqual(
                    self.client.get(
                        reverse("web:operation-reference", args=[draft.pk])
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    self.client.post(
                        reverse("web:operation-reactivate", args=[draft.pk, self.inactive.pk]),
                        {"confirm": "yes"},
                    ).status_code,
                    403,
                )
                self.assertEqual(
                    self.post_edit(draft, add_reference=self.inactive.pk).status_code, 400
                )
                self.assertEqual(self.post_edit(draft, action="new-reference").status_code, 400)

    def test_incomplete_or_zero_entry_cannot_reach_review(self):
        for value in ("", 0):
            draft = self.draft()
            response = self.post_edit(draft, **{"form-0-units": value, "action": "review"})
            self.assertEqual(response.status_code, 302)
            draft.refresh_from_db()
            self.assertIsNone(draft.review_token)
            self.assertEqual(draft.status, "draft")
            self.assertEqual(
                self.client.get(reverse("web:operation-review", args=[draft.pk])).status_code, 302
            )

    def test_cancel_requires_explicit_post_and_preserves_lines(self):
        draft = self.draft()
        url = reverse("web:operation-cancel", args=[draft.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {"revision": draft.revision}).status_code, 400)
        self.client.post(url, {"revision": draft.revision, "confirm": "yes"})
        draft.refresh_from_db()
        self.assertEqual((draft.status, draft.lines.count()), ("cancelled", 1))
        self.assertEqual(
            self.client.get(reverse("web:operation-edit", args=[draft.pk])).status_code, 404
        )

    def test_inventory_explicit_zero_and_location_change_atomic_confirmation(self):
        draft = self.draft("inventory")
        response = self.post_edit(
            draft,
            **{
                "form-0-boxes": "",
                "form-0-units": 0,
                "form-0-reason": "Contagem zero sintética",
                "form-0-target_location": self.destination.pk,
                "form-0-target_sector": self.sector.pk,
                "action": "review",
            },
        )
        self.assertEqual(response.status_code, 302)
        draft.refresh_from_db()
        self.assertIsNotNone(draft.review_token)
        response = self.client.post(
            reverse("web:operation-review", args=[draft.pk]),
            {"token": draft.review_token, "confirm": "on"},
        )
        self.assertRedirects(response, reverse("web:operation-detail", args=[draft.pk]))
        self.ref.refresh_from_db()
        self.assertEqual(
            (self.ref.current_stock, self.ref.location_id, self.ref.sector_id),
            (0, self.destination.pk, self.sector.pk),
        )
        self.assertEqual((draft.lines.get().counted_quantity, draft.lines.get().quantity), (0, -10))

    def test_full_inventory_scope_filters_and_pagination_preserve_uncounted(self):
        Reference.objects.bulk_create(
            [
                Reference(
                    code=f"W-PAGE-{i:03}", name=f"Página sintética {i}", location=self.destination
                )
                for i in range(65)
            ]
        )
        response = self.client.post(
            reverse("web:inventory") + f"?location={self.destination.pk}",
            {"inventory_scope": "full"},
        )
        draft = Movement.objects.get(inventory_scope="full")
        self.assertEqual(draft.lines.count(), 65)
        self.assertEqual(draft.lines.filter(counted_quantity__isnull=True).count(), 65)
        url = reverse("web:operation-edit", args=[draft.pk])
        response = self.client.get(url, {"page": 2})
        self.assertEqual(len(response.context["pairs"]), 30)
        self.assertContains(response, "0 / 65 referências contadas")
        data = self.payload(response)
        data["form-0-units"] = 0
        self.assertEqual(self.client.post(url + "?page=2", data).status_code, 302)
        self.assertEqual(draft.lines.filter(counted_quantity=0).count(), 1)
        self.assertEqual(draft.lines.filter(counted_quantity__isnull=True).count(), 64)

    def test_stock_conflict_during_count_post_and_after_review_requires_new_conference(self):
        draft = self.draft("inventory")
        url = reverse("web:operation-edit", args=[draft.pk])
        data = self.payload(self.client.get(url))
        data["form-0-units"] = 10
        Reference.objects.filter(pk=self.ref.pk).update(current_stock=11, stock_version=1)
        self.assertContains(self.client.post(url, data), "mudou enquanto contava", status_code=400)
        self.assertIsNone(draft.lines.get().counted_quantity)
        self.post_edit(
            draft, **{"form-0-units": 10, "form-0-reason": "Diferença", "action": "review"}
        )
        draft.refresh_from_db()
        Reference.objects.filter(pk=self.ref.pk).update(current_stock=12, stock_version=2)
        response = self.client.post(
            reverse("web:operation-review", args=[draft.pk]),
            {"token": draft.review_token, "confirm": "on"},
        )
        self.assertContains(response, "stock na contagem 11, stock atual 12", status_code=400)
        draft.refresh_from_db()
        self.assertEqual(draft.status, "draft")
        self.assertEqual(self.ref.__class__.objects.get(pk=self.ref.pk).current_stock, 12)

    def test_person_names_are_searchable_and_normalized_without_duplicates(self):
        Person.objects.create(name="Pessoa web sintética")
        draft = self.draft()
        self.assertContains(
            self.client.get(reverse("web:operation-edit", args=[draft.pk])),
            '<option value="Pessoa web sintética">',
        )
        self.post_edit(draft, person_name="  PESSOA   WEB SINTÉTICA ")
        self.assertEqual(Person.objects.count(), 1)

    def test_viewer_read_confirmed_history_but_no_operational_writes_or_drafts(self):
        draft = self.reviewed()
        confirmed = confirm_movement(
            draft.pk, actor=self.admin, review_token=draft.review_token, report_requested=False
        )
        other_draft = self.draft()
        self.client.force_login(self.viewer)
        self.assertContains(
            self.client.get(reverse("web:operation-detail", args=[confirmed.pk])),
            "Stock antes / após",
        )
        self.assertContains(
            self.client.get(reverse("web:history")), "Caixas / garrafas introduzidas"
        )
        for name, args in (
            ("drafts", []),
            ("operation-edit", [other_draft.pk]),
            ("operation-review", [other_draft.pk]),
            ("operation-cancel", [other_draft.pk]),
            ("operation-reference", [other_draft.pk]),
            ("operation-correction", [confirmed.pk]),
        ):
            for method in (self.client.get, self.client.post):
                with self.subTest(name=name, method=method.__name__):
                    self.assertEqual(method(reverse(f"web:{name}", args=args)).status_code, 403)
        self.assertNotContains(
            self.client.get(reverse("web:operation-detail", args=[confirmed.pk])),
            "Registar correção relacionada",
        )
        self.assertEqual(
            self.client.get(reverse("web:operation-detail", args=[other_draft.pk])).status_code, 404
        )

    def test_other_admin_cannot_access_or_write_own_drafts(self):
        draft = self.draft()
        self.client.force_login(self.other)
        for name in (
            "operation-edit",
            "operation-review",
            "operation-cancel",
            "operation-reference",
        ):
            self.assertEqual(
                self.client.get(reverse(f"web:{name}", args=[draft.pk])).status_code, 404
            )
            self.assertEqual(
                self.client.post(reverse(f"web:{name}", args=[draft.pk])).status_code, 404
            )

    def test_csrf_is_enforced_for_all_mutations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post(reverse("web:entry")).status_code, 403)
        draft = self.draft()
        self.assertEqual(
            client.post(reverse("web:operation-edit", args=[draft.pk])).status_code, 403
        )
        self.assertEqual(
            client.post(reverse("web:operation-review", args=[draft.pk])).status_code, 403
        )
        self.assertEqual(
            client.post(reverse("web:operation-cancel", args=[draft.pk])).status_code, 403
        )
        self.assertEqual(AuditEvent.objects.filter(action="movement.confirmed").count(), 0)
