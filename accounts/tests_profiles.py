import secrets

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.administration import change_account, create_account, save_profile
from accounts.models import AccessProfile
from accounts.permissions import SUBSTITUTE, capabilities
from inventory import catalog, operations
from inventory.models import AuditEvent, Location, Reference
from inventory.reporting import delete_pdf, regenerate_pdf
from tests.document_fixtures import confirmed_operation


class AccessProfileTests(TestCase):
    def setUp(self):
        self.password = secrets.token_urlsafe(32)
        self.admin = get_user_model().objects.create_user(
            username="a2-admin", role="admin", password=self.password
        )
        self.viewer = get_user_model().objects.create_user(username="a2-viewer")
        self.profile, _ = AccessProfile.objects.get_or_create(
            name="Substituto", defaults={"capabilities": SUBSTITUTE}
        )
        self.sub = get_user_model().objects.create_user(
            username="a2-sub", role="custom", access_profile=self.profile
        )
        self.location = Location.objects.create(name="Local permissões fictício")
        self.ref = Reference.objects.create(
            code="A2-PERM",
            name="Garrafa permissões fictícia",
            current_stock=50,
            location=self.location,
            box_capacity=6,
        )

    def save(self, **changes):
        data = {
            "actor": self.admin,
            "profile_id": self.profile.pk,
            "name": self.profile.name,
            "active": True,
            "capabilities": SUBSTITUTE,
            "current_password": self.password,
            "reason": "Revisão fictícia de permissões",
        }
        data.update(changes)
        return save_profile(**data)

    def test_custom_account_assignment_and_audit(self):
        account = create_account(
            actor=self.admin,
            username="a2-created",
            password=secrets.token_urlsafe(32),
            role="custom",
            access_profile=self.profile,
            current_password=self.password,
        )
        self.assertEqual(account.access_profile_id, self.profile.pk)
        self.assertEqual(capabilities(account), set(SUBSTITUTE))
        self.assertTrue(
            AuditEvent.objects.filter(
                action="account.created", details__profile=self.profile.pk
            ).exists()
        )
        self.assertFalse(account.is_staff)
        self.assertFalse(account.is_superuser)

    def test_substitute_can_confirm_entries_and_exits(self):
        for kind in ("entry", "exit"):
            movement = confirmed_operation(self.sub, self.ref, kind=kind, report=True)
            self.assertEqual(movement.confirmed_by_id, self.sub.pk)
            self.assertTrue(movement.documents.filter(kind="pdf").exists())
        self.ref.refresh_from_db()
        self.assertEqual(self.ref.current_stock, 50)

    def test_substitute_denied_every_administrative_domain(self):
        for action in (
            lambda: operations.create_draft(actor=self.sub, kind="inventory"),
            lambda: catalog.save_reference(
                actor=self.sub, data={"name": "Não criar", "location": self.location}
            ),
            lambda: catalog.set_reference_active(
                actor=self.sub, reference_id=self.ref.pk, active=False
            ),
            lambda: catalog.save_location(actor=self.sub, data={"name": "Não criar"}),
            lambda: create_account(
                actor=self.sub,
                username="not-created",
                password=secrets.token_urlsafe(32),
                role="admin",
                current_password="wrong",
            ),
            lambda: self.save(actor=self.sub, capabilities=["inventory"]),
        ):
            with self.assertRaises(PermissionDenied):
                action()
        self.assertEqual(Reference.objects.count(), 1)
        self.assertEqual(self.ref.current_stock, 50)

    def test_substitute_http_permissions_and_hidden_menus(self):
        self.client.force_login(self.sub)
        for route in ("stock", "entry", "exit", "history", "reports"):
            self.assertEqual(self.client.get(reverse("web:" + route)).status_code, 200)
        for route in (
            "inventory",
            "users",
            "user-create",
            "profiles",
            "profile-create",
            "reference-create",
            "locations",
            "import-list",
            "export",
        ):
            for method in (self.client.get, self.client.post):
                self.assertEqual(method(reverse("web:" + route)).status_code, 403)
        home = self.client.get(reverse("web:home"))
        for hidden in ("web:inventory", "web:users", "web:references"):
            self.assertNotContains(home, reverse(hidden))
        self.assertContains(home, "Substituto")

    def test_revocation_takes_effect_in_existing_session_and_stale_actor(self):
        self.client.force_login(self.sub)
        self.assertEqual(self.client.get(reverse("web:entry")).status_code, 200)
        self.save(active=False)
        self.assertEqual(self.client.post(reverse("web:entry"), {}).status_code, 403)
        self.assertEqual(self.client.get(reverse("web:stock")).status_code, 403)
        with self.assertRaises(PermissionDenied):
            operations.create_draft(actor=self.sub, kind="entry")
        self.assertFalse(capabilities(self.sub))

    def test_individual_permission_edit_takes_effect_without_relogin(self):
        self.client.force_login(self.sub)
        self.save(capabilities=["stock_view", "exit", "reports_view"])
        self.assertEqual(self.client.get(reverse("web:entry")).status_code, 403)
        self.assertEqual(self.client.get(reverse("web:exit")).status_code, 200)
        with self.assertRaises(PermissionDenied):
            operations.create_draft(actor=self.sub, kind="entry")

    def test_profile_cannot_grant_administrator_or_unknown_permissions(self):
        for values in (["admin"], ["users_manage"], "entry"):
            with self.assertRaises(ValidationError):
                self.save(capabilities=values)
        self.assertEqual(capabilities(self.sub), set(SUBSTITUTE))

    def test_admin_can_grant_catalogue_permission_to_a_custom_profile_explicitly(self):
        self.save(capabilities=SUBSTITUTE + ["catalog_manage"])
        reference = catalog.save_reference(
            actor=self.sub,
            data={"name": "Nova fictícia autorizada", "location": self.location, "box_capacity": 6},
        )
        self.assertEqual(reference.current_stock, 0)

    def test_own_reports_only_and_authorized_regeneration(self):
        own = confirmed_operation(self.sub, self.ref, kind="entry", report=True)
        other = confirmed_operation(self.admin, self.ref, kind="entry", report=True)
        own_pdf = own.documents.get(kind="pdf")
        other_pdf = other.documents.get(kind="pdf")
        self.client.force_login(self.sub)
        self.assertEqual(
            self.client.get(reverse("web:document-content", args=[own_pdf.pk])).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("web:document-content", args=[other_pdf.pk])).status_code, 404
        )
        self.assertEqual(
            self.client.get(reverse("web:operation-detail", args=[other.pk])).status_code, 404
        )
        with self.assertRaises(PermissionDenied):
            delete_pdf(actor=self.sub, document_id=own_pdf.pk)
        delete_pdf(actor=self.admin, document_id=own_pdf.pk)
        regenerate_pdf(actor=self.sub, document_id=own_pdf.pk)
        with self.assertRaises(PermissionDenied):
            regenerate_pdf(actor=self.sub, document_id=other_pdf.pk)

    def test_inventory_permission_does_not_reveal_or_correct_another_users_history(self):
        other = confirmed_operation(self.admin, self.ref)
        self.save(capabilities=SUBSTITUTE + ["inventory"])
        self.client.force_login(self.sub)
        self.assertEqual(
            self.client.get(reverse("web:operation-correction", args=[other.pk])).status_code, 404
        )
        with self.assertRaises(PermissionDenied):
            operations.create_draft(
                actor=self.sub,
                kind="inventory",
                correction_of=other,
                reason="Correção fictícia não autorizada",
                references=[self.ref],
            )
        own = confirmed_operation(self.sub, self.ref, kind="entry", report=True)
        draft = operations.create_draft(
            actor=self.sub,
            kind="inventory",
            correction_of=own,
            reason="Correção fictícia autorizada",
            references=[self.ref],
        )
        self.assertEqual(draft.correction_of_id, own.pk)

    def test_self_access_and_last_admin_protected(self):
        with self.assertRaises(ValidationError):
            change_account(
                actor=self.admin,
                account_id=self.admin.pk,
                role="custom",
                access_profile=self.profile,
                active=True,
                current_password=self.password,
                reason="Não deve ser permitido",
            )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_administrator)
        self.assertEqual(get_user_model().objects.filter(role="admin", is_active=True).count(), 1)

    def test_inactive_profile_cannot_activate_account_and_account_deactivation_preserves_identity(
        self,
    ):
        self.save(active=False)
        with self.assertRaises(ValidationError):
            change_account(
                actor=self.admin,
                account_id=self.sub.pk,
                role="custom",
                access_profile=self.profile,
                active=True,
                current_password=self.password,
                reason="Perfil desligado",
            )
        change_account(
            actor=self.admin,
            account_id=self.sub.pk,
            role="custom",
            access_profile=self.profile,
            active=False,
            current_password=self.password,
            reason="Fim de substituição fictícia",
        )
        self.sub.refresh_from_db()
        self.assertFalse(self.sub.is_active)
        self.assertEqual(self.sub.access_profile_id, self.profile.pk)
