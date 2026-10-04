from unittest.mock import patch

from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.test import TestCase
from django.test import override_settings
from django_pam.auth.backends import PAMBackend

from paperless.pam_auth import PaperlessPAMBackend


@override_settings(
    PAPERLESS_PAM_SERVICE="paperless",
    PAPERLESS_PAM_GROUP_MARKER="paperless-group-marker",
    PAPERLESS_PAM_ADMIN_GROUP="paperless-admins",
)
class TestPaperlessPAMBackend(TestCase):
    def setUp(self):
        self.backend = PaperlessPAMBackend()

    @patch.object(PaperlessPAMBackend, "_managed_groups")
    @patch.object(PaperlessPAMBackend, "_system_groups")
    @patch.object(PAMBackend, "authenticate")
    def test_requires_at_least_one_managed_group(
        self,
        pam_authenticate,
        system_groups,
        managed_groups,
    ):
        system_groups.return_value = {"users", "hr"}
        managed_groups.return_value = set()

        user = self.backend.authenticate(
            request=None,
            username="alice",
            password="secret",
        )

        self.assertIsNone(user)
        pam_authenticate.assert_not_called()

    @patch("paperless.pam_auth.grp.getgrnam")
    def test_marker_selects_managed_groups(self, getgrnam):
        def group(name):
            members = {
                "hr": ["alice", "paperless-group-marker"],
                "management": ["alice"],
                "accounting": ["paperless-group-marker"],
            }
            result = type("Group", (), {})()
            result.gr_mem = members[name]
            return result

        getgrnam.side_effect = group

        managed = self.backend._managed_groups(
            {"hr", "management", "accounting"},
        )

        self.assertEqual(managed, {"hr", "accounting"})

    @patch.object(PaperlessPAMBackend, "_managed_groups")
    @patch.object(PaperlessPAMBackend, "_system_groups")
    @patch.object(PAMBackend, "authenticate")
    def test_jit_creates_and_syncs_managed_groups(
        self,
        pam_authenticate,
        system_groups,
        managed_groups,
    ):
        user = User.objects.create_user(username="alice")
        stale = Group.objects.create(name="old-team")
        user.groups.add(stale)

        system_groups.return_value = {"users", "hr", "management"}
        managed_groups.return_value = {"hr", "management"}
        pam_authenticate.return_value = user

        result = self.backend.authenticate(
            request=None,
            username="alice",
            password="secret",
        )

        self.assertEqual(result, user)
        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {"hr", "management"},
        )
        self.assertTrue(Group.objects.filter(name="hr").exists())
        self.assertTrue(Group.objects.filter(name="management").exists())

    @patch.object(PaperlessPAMBackend, "_managed_groups")
    @patch.object(PaperlessPAMBackend, "_system_groups")
    @patch.object(PAMBackend, "authenticate")
    def test_admin_group_grants_staff_and_superuser(
        self,
        pam_authenticate,
        system_groups,
        managed_groups,
    ):
        user = User.objects.create_user(
            username="alice",
            is_staff=False,
            is_superuser=False,
        )

        system_groups.return_value = {"paperless-admins"}
        managed_groups.return_value = {"paperless-admins"}
        pam_authenticate.return_value = user

        self.backend.authenticate(
            request=None,
            username="alice",
            password="secret",
        )

        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.groups.filter(name="paperless-admins").exists())

    @patch.object(PaperlessPAMBackend, "_managed_groups")
    @patch.object(PaperlessPAMBackend, "_system_groups")
    @patch.object(PAMBackend, "authenticate")
    def test_login_resynchronizes_groups_and_admin_role(
        self,
        pam_authenticate,
        system_groups,
        managed_groups,
    ):
        user = User.objects.create_user(
            username="alice",
            is_staff=True,
            is_superuser=True,
        )
        stale = Group.objects.create(name="management")
        user.groups.add(stale)

        system_groups.return_value = {"hr"}
        managed_groups.return_value = {"hr"}
        pam_authenticate.return_value = user

        self.backend.authenticate(
            request=None,
            username="alice",
            password="secret",
        )

        user.refresh_from_db()
        self.assertEqual(
            set(user.groups.values_list("name", flat=True)),
            {"hr"},
        )
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    @patch.object(PaperlessPAMBackend, "_managed_groups")
    @patch.object(PaperlessPAMBackend, "_system_groups")
    @patch.object(PAMBackend, "authenticate")
    def test_failed_pam_authentication_does_not_change_authorization(
        self,
        pam_authenticate,
        system_groups,
        managed_groups,
    ):
        user = User.objects.create_user(
            username="alice",
            is_staff=True,
            is_superuser=True,
        )
        existing = Group.objects.create(name="management")
        user.groups.add(existing)

        system_groups.return_value = {"hr"}
        managed_groups.return_value = {"hr"}
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
