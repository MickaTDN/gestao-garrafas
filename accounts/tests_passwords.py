import json
import secrets

from django.contrib.auth import SESSION_KEY
from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from accounts.models import AccessProfile, User
from accounts.passwords import change_own_password, reset_password
from accounts.permissions import SUBSTITUTE, capabilities
from inventory import operations
from inventory.models import AuditEvent


class PasswordManagementTests(TestCase):
    def setUp(self):
        self.old = secrets.token_urlsafe(32)
        self.new = secrets.token_urlsafe(32)
        self.admin = User.objects.create_user(
            username="a3-password-admin", password=self.old, role="admin"
        )
        self.viewer = User.objects.create_user(username="a3-password-viewer", password=self.old)
        self.profile, _ = AccessProfile.objects.get_or_create(
            name="Substituto", defaults={"capabilities": SUBSTITUTE}
        )
        self.sub = User.objects.create_user(
            username="a3-password-sub",
            password=self.old,
            role="custom",
            access_profile=self.profile,
        )
        self.client.force_login(self.viewer)
        self.url = reverse("web:my-account")

    def own_data(self, **changes):
        data = {"old_password": self.old, "new_password1": self.new, "new_password2": self.new}
        data.update(changes)
        return data

    def reset_data(self, **changes):
        data = {
            "current_password": self.old,
            "new_password1": self.new,
            "new_password2": self.new,
            "confirm": "on",
        }
        data.update(changes)
        return data

    def reset(self, account=None, **changes):
        self.client.force_login(self.admin)
        return self.client.post(
            reverse("web:user-password-reset", args=[(account or self.viewer).pk]),
            self.reset_data(**changes),
        )

    def test_all_profiles_can_find_my_account_without_admin_access(self):
        for user in (self.admin, self.viewer, self.sub):
            self.client.force_login(user)
            settings = self.client.get(reverse("web:settings"))
            self.assertContains(settings, self.url)
            self.assertEqual(self.client.get(self.url).status_code, 200)
            if user != self.admin:
                self.assertNotContains(settings, reverse("web:users"))
                self.assertEqual(self.client.get(reverse("web:users")).status_code, 403)

    def test_change_own_password_preserves_current_session_and_invalidates_other_sessions(self):
        other = Client()
        other.force_login(self.viewer)
        old_session = self.client.session.session_key
        self.assertEqual(self.client.post(self.url, self.own_data()).status_code, 302)
        self.viewer.refresh_from_db()
        self.assertTrue(self.viewer.check_password(self.new))
        self.assertNotEqual(self.viewer.password, self.new)
        self.assertNotEqual(self.client.session.session_key, old_session)
        self.assertIn(SESSION_KEY, self.client.session)
        self.assertEqual(self.client.get(reverse("web:stock")).status_code, 200)
        self.assertEqual(other.get(reverse("web:stock")).status_code, 302)
        events = AuditEvent.objects.filter(action="account.password_changed")
        self.assertEqual(events.count(), 1)
        text = json.dumps(list(events.values("details")))
        for secret in (self.old, self.new, self.viewer.password):
            self.assertNotIn(secret, text)

    def test_wrong_current_password_does_not_mutate(self):
        response = self.client.post(self.url, self.own_data(old_password="incorrect-synthetic"))
        self.assertEqual(response.status_code, 400)
        self.viewer.refresh_from_db()
        self.assertTrue(self.viewer.check_password(self.old))
        self.assertFalse(AuditEvent.objects.filter(action="account.password_changed").exists())
        self.assertNotContains(response, self.new, status_code=400)

    def test_existing_long_password_remains_usable_for_change(self):
        old = secrets.token_urlsafe(192)
        self.viewer.set_password(old)
        self.viewer.save(update_fields=["password"])
        self.client.force_login(self.viewer)
        self.assertEqual(
            self.client.post(self.url, self.own_data(old_password=old)).status_code, 302
        )
        self.viewer.refresh_from_db()
        self.assertTrue(self.viewer.check_password(self.new))

    def test_django_validation_mismatch_and_password_reuse_rejected(self):
        for changes in (
            {"new_password1": "123", "new_password2": "123"},
            {"new_password2": "different-synthetic"},
            {"new_password1": self.old, "new_password2": self.old},
        ):
            self.assertEqual(self.client.post(self.url, self.own_data(**changes)).status_code, 400)
        self.viewer.refresh_from_db()
        self.assertTrue(self.viewer.check_password(self.old))

    def test_forged_target_and_privileged_fields_only_change_logged_in_user(self):
        self.client.post(
            self.url,
            self.own_data(
                user_id=self.admin.pk,
                account_id=self.admin.pk,
                role="admin",
                is_active="on",
                must_change_password="false",
            ),
        )
        self.admin.refresh_from_db()
        self.viewer.refresh_from_db()
        self.assertTrue(self.admin.check_password(self.old))
        self.assertTrue(self.viewer.check_password(self.new))
        self.assertEqual(self.viewer.role, "viewer")

    def test_admin_reset_requires_current_password_confirmation_and_safe_temporary_password(self):
        for changes in (
            {"current_password": "wrong-synthetic"},
            {"confirm": ""},
            {"new_password1": "123", "new_password2": "123"},
            {"new_password2": "different-synthetic"},
        ):
            self.assertEqual(self.reset(**changes).status_code, 400)
        self.viewer.refresh_from_db()
        self.assertTrue(self.viewer.check_password(self.old))
        self.assertFalse(self.viewer.must_change_password)

    def test_reset_forces_change_after_login_and_invalidates_preexisting_session(self):
        previous = Client()
        previous.force_login(self.viewer)
        self.assertEqual(self.reset().status_code, 302)
        self.viewer.refresh_from_db()
        self.assertTrue(self.viewer.must_change_password)
        self.assertFalse(capabilities(self.viewer))
        self.assertTrue(self.viewer.check_password(self.new))
        self.assertEqual(previous.get(reverse("web:stock")).status_code, 302)
        fresh = Client()
        response = fresh.post(
            reverse("login"),
            {"username": self.viewer.username, "password": self.new, "next": reverse("web:stock")},
        )
        self.assertRedirects(response, self.url)
        for route in (
            "home",
            "stock",
            "history",
            "reports",
            "settings",
            "export",
            "entry",
            "inventory",
        ):
            self.assertRedirects(fresh.get(reverse("web:" + route)), self.url)
            self.assertEqual(fresh.post(reverse("web:" + route), {}).status_code, 403)
        self.assertEqual(
            fresh.post(
                self.url,
                self.own_data(
                    old_password=self.new, new_password1=self.old, new_password2=self.old
                ),
            ).status_code,
            302,
        )
        self.viewer.refresh_from_db()
        self.assertFalse(self.viewer.must_change_password)
        self.assertEqual(fresh.get(reverse("web:stock")).status_code, 200)

    def test_required_change_cannot_reuse_temporary_password_or_bypass_domain_guard(self):
        self.reset(account=self.sub)
        with self.assertRaises(PermissionDenied):
            operations.create_draft(actor=self.sub, kind="entry")
        self.sub.refresh_from_db()
        self.client.force_login(self.sub)
        self.assertEqual(
            self.client.post(self.url, self.own_data(old_password=self.new)).status_code, 400
        )
        self.sub.refresh_from_db()
        self.assertTrue(self.sub.must_change_password)

    def test_viewer_and_substitute_cannot_reset_other_accounts_through_http_or_service(self):
        for user in (self.viewer, self.sub):
            self.client.force_login(user)
            url = reverse("web:user-password-reset", args=[self.admin.pk])
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, self.reset_data()).status_code, 403)
            with self.assertRaises(PermissionDenied):
                reset_password(actor=user, account_id=self.admin.pk, data=self.reset_data())

    def test_reset_does_not_reactivate_inactive_account(self):
        self.viewer.is_active = False
        self.viewer.save(update_fields=["is_active"])
        self.assertEqual(self.reset().status_code, 302)
        self.viewer.refresh_from_db()
        self.assertFalse(self.viewer.is_active)
        fresh = Client()
        self.assertEqual(
            fresh.post(
                reverse("login"), {"username": self.viewer.username, "password": self.new}
            ).status_code,
            200,
        )
        self.assertNotIn(SESSION_KEY, fresh.session)

    def test_csrf_required_for_both_password_mutations(self):
        for user, url in (
            (self.viewer, self.url),
            (self.admin, reverse("web:user-password-reset", args=[self.viewer.pk])),
        ):
            client = Client(enforce_csrf_checks=True)
            client.force_login(user)
            self.assertEqual(client.post(url, self.reset_data()).status_code, 403)

    @override_settings(LOGIN_ACCOUNT_LIMIT=2)
    def test_failed_sensitive_attempts_persist_and_do_not_lock_login_namespace(self):
        for _ in range(2):
            self.assertEqual(
                self.client.post(
                    self.url, self.own_data(old_password="wrong-synthetic")
                ).status_code,
                400,
            )
        self.assertEqual(self.client.post(self.url, self.own_data()).status_code, 429)
        fresh = Client()
        self.assertEqual(
            fresh.post(
                reverse("login"), {"username": self.viewer.username, "password": self.old}
            ).status_code,
            302,
        )
        self.assertEqual(self.client.post(self.url, self.own_data()).status_code, 429)

    def test_reset_audit_contains_only_nonsecret_identifiers(self):
        self.reset()
        event = AuditEvent.objects.get(action="account.password_reset")
        self.assertEqual(event.details, {"user_id": self.viewer.pk, "change_required": True})
        self.assertEqual(event.actor_id, self.admin.pk)
        self.assertNotIn(self.new, json.dumps(event.details))

    def test_admin_self_reset_redirects_to_current_password_change(self):
        self.client.force_login(self.admin)
        self.assertRedirects(
            self.client.get(reverse("web:user-password-reset", args=[self.admin.pk])), self.url
        )


class PasswordConcurrencyTests(TransactionTestCase):
    @override_settings(LOGIN_ACCOUNT_LIMIT=1)
    def test_real_concurrent_password_changes_share_the_attempt_limit(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        from django.db import connections

        from accounts.passwords import PasswordAttemptsExceeded

        old = secrets.token_urlsafe(32)
        new = secrets.token_urlsafe(32)
        account = User.objects.create_user(username="a3-concurrent-password", password=old)
        barrier = Barrier(2)

        def change():
            connections.close_all()
            try:
                actor = User.objects.get(pk=account.pk)
                barrier.wait(timeout=10)
                try:
                    result = change_own_password(
                        actor=actor,
                        data={"old_password": old, "new_password1": new, "new_password2": new},
                    )
                    return result.is_valid()
                except PasswordAttemptsExceeded:
                    return False
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: change(), range(2)))
        self.assertEqual(sorted(results), [False, True])
        account.refresh_from_db()
        self.assertTrue(account.check_password(new))
        self.assertEqual(AuditEvent.objects.filter(action="account.password_changed").count(), 1)
