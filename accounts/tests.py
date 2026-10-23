import io
import os
import secrets
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User


class AuthenticationTests(TestCase):
    def setUp(self):
        self.password = secrets.token_urlsafe(32)
        self.user = User.objects.create_user(username="synthetic-reader", password=self.password)

    def test_default_is_consultation_and_password_is_hashed(self):
        self.assertEqual(self.user.role, User.Role.VIEWER)
        self.assertFalse(self.user.is_administrator)
        self.assertNotEqual(self.user.password, self.password)
        self.assertTrue(self.user.check_password(self.password))

    def test_login_logout_and_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get("/").status_code, 302)
        self.assertEqual(client.post(reverse("login"), {
            "username": self.user.username, "password": self.password,
        }).status_code, 403)
        client.get(reverse("login"))
        token = client.cookies["csrftoken"].value
        response = client.post(reverse("login"), {
            "username": self.user.username, "password": self.password,
            "csrfmiddlewaretoken": token,
        })
        self.assertRedirects(response, "/")
        self.assertEqual(client.get(reverse("logout")).status_code, 405)
        self.assertEqual(client.post(reverse("logout")).status_code, 403)
        token = client.cookies["csrftoken"].value
        self.assertEqual(client.post(reverse("logout"), {
            "csrfmiddlewaretoken": token,
        }).status_code, 302)
        self.assertEqual(client.get("/").status_code, 302)

    def test_inactive_account_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        self.assertFalse(self.client.login(username=self.user.username, password=self.password))

    def test_role_constraint_rejects_unknown_value(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.filter(pk=self.user.pk).update(role="owner")

    def test_user_command_uses_injected_password_and_preserves_existing_user(self):
        password = secrets.token_urlsafe(32)
        with patch.dict(os.environ, {"TEST_ACCOUNT_PASSWORD": password}):
            call_command("create_user", "synthetic-admin", role="admin",
                         password_env="TEST_ACCOUNT_PASSWORD", stdout=io.StringIO())
            admin = User.objects.get(username="synthetic-admin")
            self.assertTrue(admin.check_password(password))
            self.assertTrue(admin.is_administrator)
            with self.assertRaises(CommandError):
                call_command("create_user", "synthetic-admin", role="viewer",
                             password_env="TEST_ACCOUNT_PASSWORD", stdout=io.StringIO())
            admin.refresh_from_db()
            self.assertEqual(admin.role, User.Role.ADMIN)

    def test_user_command_rejects_missing_password(self):
        with patch.dict(os.environ, {"TEST_ACCOUNT_PASSWORD": ""}):
            with self.assertRaises(CommandError):
                call_command("create_user", "synthetic-missing", password_env="TEST_ACCOUNT_PASSWORD")
        self.assertFalse(User.objects.filter(username="synthetic-missing").exists())
