from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(NATIVE_BACKUP_CHANNEL="synthetic")
class NativeBackupLinkTests(TestCase):
    def test_admin_can_open_fixed_local_wizard_without_server_side_filesystem_actions(self):
        admin = get_user_model().objects.create_user(
            username="synthetic-backup-admin", role="admin"
        )
        self.client.force_login(admin)
        response = self.client.get(reverse("web:settings"))
        self.assertContains(response, 'href="gva-backup-synthetic:"')
        self.assertContains(response, 'href="gva-recover-synthetic:"')
        self.assertEqual(
            self.client.post(
                reverse("web:settings"), {"action": "restore", "path": "C:/private"}
            ).status_code,
            405,
        )

    def test_consulta_and_anonymous_do_not_receive_maintenance_controls(self):
        self.assertEqual(self.client.get(reverse("web:settings")).status_code, 302)
        viewer = get_user_model().objects.create_user(
            username="synthetic-backup-viewer", role="viewer"
        )
        self.client.force_login(viewer)
        self.assertNotContains(self.client.get(reverse("web:settings")), 'href="gva-backup-')

    def test_other_profiles_never_offer_a_nonexistent_native_handler(self):
        admin = get_user_model().objects.create_user(
            username="synthetic-backup-admin", role="admin"
        )
        self.client.force_login(admin)
        for value in (None, "untrusted:payload"):
            with self.settings(NATIVE_BACKUP_CHANNEL=value):
                self.assertNotContains(
                    self.client.get(reverse("web:settings")), 'href="gva-backup-'
                )
