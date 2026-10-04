import grp
import os
import pwd

from django.conf import settings
from django_pam.auth.backends import PAMBackend


class PaperlessPAMBackend(PAMBackend):
    """Authenticate and authorize appliance users through PAM/NSS."""

    @staticmethod
    def _system_groups(username):
        account = pwd.getpwnam(username)
        gids = os.getgrouplist(username, account.pw_gid)
        return {grp.getgrgid(gid).gr_name for gid in gids}

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
            groups = self._system_groups(username)
        except KeyError:
            return None

        is_admin = settings.PAPERLESS_PAM_ADMIN_GROUP in groups
        if settings.PAPERLESS_PAM_USER_GROUP not in groups and not is_admin:
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

        changed = []
        if user.is_staff != is_admin:
            user.is_staff = is_admin
            changed.append("is_staff")
        if user.is_superuser != is_admin:
            user.is_superuser = is_admin
            changed.append("is_superuser")
        if changed:
            user.save(update_fields=changed)

        return user
