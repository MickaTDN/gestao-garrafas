import secrets
from importlib import import_module

from django.apps import apps
from django.contrib.auth.hashers import make_password
from django.db import connection
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from accounts.models import AccessProfile, User
from accounts.permissions import SUBSTITUTE
from inventory.documents import verified_bytes
from inventory.models import Document, Location, Reference, ReportNumber
from inventory.reporting import delete_pdf, regenerate_pdf
from tests.document_fixtures import confirmed_operation


class A3MigrationCompatibilityTests(TransactionTestCase):
    def test_a2_accounts_profiles_and_deleted_signed_pdf_survive_upgrade(self):
        password_hash = make_password(secrets.token_urlsafe(32))
        actor = User.objects.create(
            username="a3-old-schema-admin", role="admin", password=password_hash
        )
        profile, _ = AccessProfile.objects.get_or_create(
            name="Substituto", defaults={"capabilities": SUBSTITUTE}
        )
        sub = User.objects.create(
            username="a3-old-schema-sub",
            role="custom",
            access_profile=profile,
            password=password_hash,
        )
        location = Location.objects.create(name="Local migração A3 fictício")
        reference = Reference.objects.create(
            code="A3-MIGRATION",
            name="Garrafa migração fictícia",
            location=location,
            current_stock=10,
        )
        movement = confirmed_operation(actor, reference, signed=True)
        document = movement.documents.get(kind="pdf")
        original = verified_bytes(document)
        identity = str(movement.report_number)
        delete_pdf(actor=actor, document_id=document.pk)
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([("accounts", "0004_substitute_profile")])
            old = executor.loader.project_state([("accounts", "0004_substitute_profile")]).apps
            old_user = old.get_model("accounts", "User").objects.get(pk=sub.pk)
            self.assertEqual(old_user.password, password_hash)
            self.assertEqual(old_user.access_profile_id, profile.pk)
            MigrationExecutor(connection).migrate(latest)
            actor.refresh_from_db()
            sub.refresh_from_db()
            self.assertFalse(actor.must_change_password)
            self.assertFalse(sub.must_change_password)
            self.assertEqual(sub.password, password_hash)
            self.assertEqual(sub.access_profile_id, profile.pk)
            regenerate_pdf(actor=actor, document_id=document.pk)
            self.assertEqual(verified_bytes(Document.objects.get(pk=document.pk)), original)
            self.assertEqual(str(ReportNumber.objects.get(movement=movement)), identity)
            self.assertEqual(Reference.objects.get(pk=reference.pk).current_stock, 8)
        finally:
            MigrationExecutor(connection).migrate(latest)

    def test_pending_forced_password_change_blocks_destructive_schema_reverse(self):
        User.objects.create(username="a3-required-migration", must_change_password=True)
        migration = import_module("accounts.migrations.0005_required_password_change")
        with self.assertRaises(IrreversibleError):
            migration.protect(apps, None)
        self.assertTrue(User.objects.get(username="a3-required-migration").must_change_password)
