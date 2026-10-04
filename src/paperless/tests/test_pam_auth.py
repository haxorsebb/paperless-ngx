from unittest.mock import patch

from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings
from django_pam.auth.backends import PAMBackend

from paperless.pam_auth import PaperlessPAMBackend


@override_settings(
    PAPERLESS_PAM_SERVICE="paperless",
    PAPERLESS_PAM_USER_GROUP="paperless-users",
    PAPERLESS_PAM_ADMIN_GROUP="paperless-admins",
)
class TestPaperlessPAMBackend(TestCase):
    def setUp(self):
        self.backend = PaperlessPAMBackend()

    @patch.object(PaperlessPAMBackend, "_system_groups")
    @patch.object(PAMBackend, "authenticate")
    def test_requires_paperless_eligibility_group(self, pam_authenticate, system_groups):
        system_groups.return_value = {"users", "hr"}

        user = self.backend.authenticate(
            request=None,
            username="alice",
            password="secret",
        )

        self.assertIsNone(user)
        pam_authenticate.assert_not_called()

    @patch.object(PaperlessPAMBackend, "_system_groups")
    @patch.object(PAMBackend, "authenticate")
    def test_syncs_only_existing_paperless_groups(self, pam_authenticate, system_groups):
        user = User.objects.create_user(username="alice")
        paperless_users = Group.objects.create(name="paperless-users")
        hr = Group.objects.create(name="hr")
        Group.objects.create(name="management")

        system_groups.return_value = {
            "users",
            "paperless-users",
            "hr",
            "not-a-paperless-group",
        }
        pam_authenticate.return_value = user

        result = self.backend.authenticate(
            request=None,
            username="alice",
            password="secret",
        )

        self.assertEqual(result, user)
        self.assertEqual(set(user.groups.all()), {paperless_users, hr})

    @patch.object(PaperlessPAMBackend, "_system_groups")
    @patch.object(PAMBackend, "authenticate")
    def test_admin_group_grants_staff_and_superuser(self, pam_authenticate, system_groups):
        user = User.objects.create_user(
            username="alice",
            is_staff=False,
            is_superuser=False,
        )
        Group.objects.create(name="paperless-admins")

        system_groups.return_value = {"paperless-admins"}
        pam_authenticate.return_value = user

        self.backend.authenticate(
            request=None,
            username="alice",
            password="secret",
        )

        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    @patch.object(PaperlessPAMBackend, "_system_groups")
    @patch.object(PAMBackend, "authenticate")
    def test_login_resynchronizes_groups_and_admin_role(
        self,
        pam_authenticate,
        system_groups,
    ):
        user = User.objects.create_user(
            username="alice",
            is_staff=True,
            is_superuser=True,
        )
        stale = Group.objects.create(name="management")
        paperless_users = Group.objects.create(name="paperless-users")
        user.groups.add(stale)

        system_groups.return_value = {"paperless-users"}
        pam_authenticate.return_value = user

        self.backend.authenticate(
            request=None,
            username="alice",
            password="secret",
        )

        user.refresh_from_db()
        self.assertEqual(set(user.groups.all()), {paperless_users})
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    @patch.object(PaperlessPAMBackend, "_system_groups")
    @patch.object(PAMBackend, "authenticate")
    def test_failed_pam_authentication_does_not_change_authorization(
        self,
        pam_authenticate,
        system_groups,
    ):
        user = User.objects.create_user(
            username="alice",
            is_staff=True,
            is_superuser=True,
        )
        existing = Group.objects.create(name="management")
        user.groups.add(existing)

        system_groups.return_value = {"paperless-users"}
        pam_authenticate.return_value = None

        result = self.backend.authenticate(
            request=None,
            username="alice",
            password="wrong",
        )

        self.assertIsNone(result)
        user.refresh_from_db()
        self.assertEqual(set(user.groups.all()), {existing})
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
