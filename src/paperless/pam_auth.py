import grp
import os
import pwd

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.db import transaction
from django_pam.auth.backends import PAMBackend


class PaperlessPAMBackend(PAMBackend):
    """Authenticate through PAM and synchronize marker-selected NSS groups."""

    BASELINE_GROUP_PERMISSIONS = (
        ("documents", "view_document"),
        ("documents", "view_uisettings"),
    )

    @staticmethod
    def _system_groups(username):
        account = pwd.getpwnam(username)
        gids = os.getgrouplist(username, account.pw_gid)
        return {grp.getgrgid(gid).gr_name for gid in gids}

    @staticmethod
    def _managed_groups(system_groups):
        marker = settings.PAPERLESS_PAM_GROUP_MARKER
        managed_groups = set()

        for group_name in system_groups:
            try:
                group = grp.getgrnam(group_name)
            except KeyError:
                continue

            if marker in group.gr_mem:
                managed_groups.add(group_name)

        return managed_groups

    @classmethod
    def _get_or_create_managed_group(cls, group_name):
        with transaction.atomic():
            group, created = Group.objects.get_or_create(name=group_name)
            if created:
                permissions = [
                    Permission.objects.get(
                        content_type__app_label=app_label,
                        codename=codename,
                    )
                    for app_label, codename in cls.BASELINE_GROUP_PERMISSIONS
                ]
                group.permissions.add(*permissions)

        return group

    @classmethod
    def _sync_authorization(cls, user, managed_groups):
        groups = [
            cls._get_or_create_managed_group(group_name)
            for group_name in managed_groups
        ]
        user.groups.set(groups, clear=True)

        is_admin = settings.PAPERLESS_PAM_ADMIN_GROUP in managed_groups
        modified_fields = []

        if user.is_superuser != is_admin:
            user.is_superuser = is_admin
            modified_fields.append("is_superuser")

        if user.is_staff != is_admin:
            user.is_staff = is_admin
            modified_fields.append("is_staff")

        if modified_fields:
            user.save(update_fields=modified_fields)

    def authenticate(
        self,
        request,
        username=None,
        password=None,
        **kwargs,
    ):
        if not username:
            return None

        try:
            system_groups = self._system_groups(username)
            managed_groups = self._managed_groups(system_groups)
        except KeyError:
            return None

        if not managed_groups:
            return None

        user = super().authenticate(
            request,
            username=username,
            password=password,
            service=settings.PAPERLESS_PAM_SERVICE,
            **kwargs,
        )
        if user is None:
            return None

        self._sync_authorization(user, managed_groups)
        return user
