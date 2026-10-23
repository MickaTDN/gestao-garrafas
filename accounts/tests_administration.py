import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.administration import change_account, create_account
from accounts.models import LoginLimit
from accounts.security import reserve_login_attempt
from inventory.models import AuditEvent

User = get_user_model()


class AccountAdministrationTests(TestCase):
    def setUp(self):
        self.password = secrets.token_urlsafe(32)
        self.admin = User.objects.create_user(
            username="security-admin", role="admin", password=self.password
        )
        self.viewer = User.objects.create_user(username="security-viewer")
        self.other = User.objects.create_user(username="security-other", role="admin")
        self.client.force_login(self.admin)

    def test_create_account_validated_password_role_and_audit(self):
        password = secrets.token_urlsafe(32)
        account = create_account(
            actor=self.admin,
            username="new-synthetic",
            password=password,
            role="viewer",
            current_password=self.password,
        )
        self.assertTrue(account.check_password(password))
        self.assertFalse(account.is_staff)
        self.assertFalse(account.is_superuser)
        self.assertEqual(account.role, "viewer")
        self.assertTrue(
            AuditEvent.objects.filter(action="account.created", actor=self.admin).exists()
        )
        self.assertNotIn(password, str(AuditEvent.objects.last().details))

    def test_weak_or_duplicate_or_unknown_role_account_is_not_created(self):
        for username, password, role in (
            ("weak", "password", "admin"),
            ("SECURITY-VIEWER", secrets.token_urlsafe(32), "viewer"),
            ("invalid", secrets.token_urlsafe(32), "owner"),
        ):
            with self.subTest(username=username), self.assertRaises(ValidationError):
                create_account(
                    actor=self.admin,
                    username=username,
                    password=password,
                    role=role,
                    current_password=self.password,
                )
        self.assertEqual(User.objects.count(), 3)

    def test_critical_changes_require_current_password_and_reason(self):
        for password, reason in (("wrong", "Motivo"), (self.password, "")):
            with self.assertRaises(ValidationError):
                change_account(
                    actor=self.admin,
                    account_id=self.viewer.pk,
                    role="admin",
                    active=True,
                    current_password=password,
                    reason=reason,
                )
        self.viewer.refresh_from_db()
        self.assertEqual(self.viewer.role, "viewer")

    def test_disable_preserves_account_identity_and_records_actor(self):
        change_account(
            actor=self.admin,
            account_id=self.viewer.pk,
            role="viewer",
            active=False,
            current_password=self.password,
            reason="Desativação sintética",
        )
        self.viewer.refresh_from_db()
        self.assertFalse(self.viewer.is_active)
        self.assertEqual(self.viewer.username, "security-viewer")
        event = AuditEvent.objects.get(action="account.updated")
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.details["user_id"], self.viewer.pk)

    def test_self_disable_or_demotion_rejected(self):
        for role, active in (("admin", False), ("viewer", True)):
            with self.assertRaises(ValidationError):
                change_account(
                    actor=self.admin,
                    account_id=self.admin.pk,
                    role=role,
                    active=active,
                    current_password=self.password,
                    reason="Teste",
                )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_administrator)

    def test_viewer_cannot_escalate_even_with_forged_http(self):
        self.client.force_login(self.viewer)
        for name, args in (("users", []), ("user-create", []), ("user-edit", [self.viewer.pk])):
            for method in (self.client.get, self.client.post):
                with self.subTest(name=name):
                    self.assertEqual(
                        method(
                            reverse(f"web:{name}", args=args),
                            {"role": "admin", "is_superuser": "on", "is_staff": "on"},
                        ).status_code,
                        403,
                    )
        with self.assertRaises(PermissionDenied):
            change_account(
                actor=self.viewer,
                account_id=self.viewer.pk,
                role="admin",
                active=True,
                current_password="",
                reason="Teste",
            )
        self.viewer.refresh_from_db()
        self.assertFalse(self.viewer.is_administrator)

    def test_create_form_ignores_forged_superuser_and_active_fields(self):
        password = secrets.token_urlsafe(32)
        response = self.client.post(
            reverse("web:user-create"),
            {
                "username": "form-synthetic",
                "role": "viewer",
                "password1": password,
                "password2": password,
                "current_password": self.password,
                "is_superuser": "on",
                "is_staff": "on",
            },
        )
        self.assertRedirects(response, reverse("web:users"))
        account = User.objects.get(username="form-synthetic")
        self.assertFalse(account.is_staff)
        self.assertFalse(account.is_superuser)

    def test_user_list_only_admin_and_private_no_password_values(self):
        response = self.client.get(reverse("web:users"))
        self.assertContains(response, "security-viewer")
        self.assertNotContains(response, self.admin.password)
        self.assertIn("no-store", response["Cache-Control"])


@override_settings(LOGIN_ACCOUNT_LIMIT=3, LOGIN_ADDRESS_LIMIT=5, LOGIN_WINDOW_SECONDS=60)
class LoginProtectionTests(TestCase):
    def setUp(self):
        self.password = secrets.token_urlsafe(32)
        self.user = User.objects.create_user(username="limited-synthetic", password=self.password)

    def login(self, username=None, password="wrong", **extra):
        return self.client.post(
            reverse("login"),
            {"username": username or self.user.username, "password": password},
            **extra,
        )

    def test_account_throttled_after_limit_even_with_correct_password(self):
        for _ in range(3):
            self.assertEqual(self.login().status_code, 200)
        response = self.login(password=self.password)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_address_limit_applies_across_usernames(self):
        for index in range(5):
            self.assertEqual(self.login(username=f"nonexistent-{index}").status_code, 200)
        self.assertEqual(self.login(username="another-missing").status_code, 429)

    def test_forwarded_header_cannot_bypass_untrusted_peer_address(self):
        for index in range(5):
            self.login(username=f"absent-{index}", HTTP_X_FORWARDED_FOR=f"192.0.2.{index}")
        self.assertEqual(
            self.login(username="missing-other", HTTP_X_FORWARDED_FOR="198.51.100.2").status_code,
            429,
        )

    @override_settings(LOGIN_TRUSTED_PROXY_ADDRESSES={"127.0.0.1"})
    def test_explicit_trusted_proxy_can_supply_single_valid_client_address(self):
        for index in range(6):
            self.assertEqual(
                self.login(
                    username=f"proxy-{index}", HTTP_X_FORWARDED_FOR=f"192.0.2.{index}"
                ).status_code,
                200,
            )

    def test_expired_window_allows_login_and_success_resets_account_bucket(self):
        for _ in range(3):
            self.login()
        LoginLimit.objects.update(window_started=timezone.now() - timedelta(seconds=61))
        self.assertEqual(self.login(password=self.password).status_code, 302)
        self.assertEqual(LoginLimit.objects.count(), 1)

    def test_bucket_records_have_no_plaintext_credentials_or_addresses(self):
        reserve_login_attempt("PERSON-SYNTHETIC", "192.0.2.23")
        for bucket in LoginLimit.objects.all():
            self.assertEqual(len(bucket.key), 64)
            self.assertNotIn("PERSON", bucket.key)
            self.assertNotIn("192.0.2", bucket.key)
        self.assertEqual(LoginLimit.objects.count(), 2)

    def test_inactive_account_stays_denied_and_unknown_user_errors_are_generic(self):
        self.user.is_active = False
        self.user.save()
        known = self.login(password=self.password)
        unknown = self.login(username="absent")
        self.assertEqual(
            known.context["form"].non_field_errors(), unknown.context["form"].non_field_errors()
        )

    def test_oversized_request_rejected_before_password_validation(self):
        response = self.client.post(
            reverse("login"), {"username": "synthetic", "password": "x" * 1100000}
        )
        self.assertEqual(response.status_code, 400)
