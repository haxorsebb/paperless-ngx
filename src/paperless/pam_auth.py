import grp
import os
import pwd

from django.conf import settings
from django.contrib.auth.models import Group
from django_pam.auth.backends import PAMBackend


class PaperlessPAMBackend(PAMBackend):
    """Authenticate Paperless users through PAM and synchronize NSS groups."""

    @staticmethod
    def _system_groups(username):
        account = pwd.getpwnam(username)
        gids = os.getgrouplist(username, account.pw_gid)
        return {grp.getgrgid(gid).gr_name for gid in gids}

    @staticmethod
    def _sync_authorization(user, system_groups):
        groups = Group.objects.filter(name__in=system_groups)
        user.groups.set(groups, clear=True)

        is_admin = settings.PAPERLESS_PAM_ADMIN_GROUP in system_groups
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
        except KeyError:
            return None

        if (
            settings.PAPERLESS_PAM_USER_GROUP not in system_groups
            and settings.PAPERLESS_PAM_ADMIN_GROUP not in system_groups
        ):
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

        self._sync_authorization(user, system_groups)
        return user
