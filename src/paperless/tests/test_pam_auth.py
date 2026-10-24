from unittest.mock import patch

from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.test import TestCase
from django.test import override_settings
from django_pam.auth.backends import PAMBackend

from paperless.pam_auth import PaperlessPAMBackend
from paperless.adapter import CustomAccountAdapter


@override_settings(
    PAPERLESS_PAM_SERVICE="paperless",
    PAPERLESS_PAM_GROUP_MARKER="paperless-group-marker",
    PAPERLESS_PAM_ADMIN_GROUP="paperless-admins",
)
class TestPaperlessPAMBackend(TestCase):
    def setUp(self):
        self.backend = PaperlessPAMBackend()

    @override_settings(PAM_AUTH_ENABLED=True)
    def test_empty_database_does_not_allow_owner_signup(self):
        self.assertFalse(CustomAccountAdapter().is_open_for_signup(None))

    @override_settings(
        AUTHENTICATION_BACKENDS=[
            "paperless.pam_auth.PaperlessPAMBackend",
            "guardian.backends.ObjectPermissionBackend",
        ]
    )
    @patch.object(PaperlessPAMBackend, "_managed_groups", return_value={"paperless-users"})
    @patch.object(PaperlessPAMBackend, "_system_groups", return_value={"paperless-users"})
    @patch.object(PAMBackend, "authenticate", return_value=None)
    def test_native_password_does_not_bypass_failed_pam(self, pam_authenticate, *_):
        User.objects.create_user(username="admin", password="paperless-only-password")
        self.assertIsNone(authenticate(username="admin", password="paperless-only-password"))
        pam_authenticate.assert_called_once()

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
        for group_name in ("hr", "management"):
            group = Group.objects.get(name=group_name)
            self.assertEqual(
                set(group.permissions.values_list("codename", flat=True)),
                {"view_document", "view_uisettings"},
            )

    @patch.object(PaperlessPAMBackend, "_managed_groups")
    @patch.object(PaperlessPAMBackend, "_system_groups")
    @patch.object(PAMBackend, "authenticate")
    def test_existing_managed_group_permissions_are_preserved(
        self,
        pam_authenticate,
        system_groups,
        managed_groups,
    ):
        user = User.objects.create_user(username="alice")
        group = Group.objects.create(name="hr")
        custom_permission = Permission.objects.get(
            content_type__app_label="auth",
            codename="view_user",
        )
        group.permissions.add(custom_permission)

        system_groups.return_value = {"hr"}
        managed_groups.return_value = {"hr"}
        pam_authenticate.return_value = user

        self.backend.authenticate(
            request=None,
            username="alice",
            password="secret",
        )

        self.assertEqual(
            set(
                group.permissions.values_list(
                    "content_type__app_label",
                    "codename",
                ),
            ),
            {("auth", "view_user")},
        )

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
