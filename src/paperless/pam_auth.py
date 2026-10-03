from django.conf import settings
from django_pam.auth.backends import PAMBackend


class PaperlessPAMBackend(PAMBackend):
    """Authenticate Paperless users through an appliance-selected PAM service."""

    def authenticate(
        self,
        request,
        username=None,
        password=None,
        **kwargs,
    ):
        return super().authenticate(
            request,
            username=username,
            password=password,
            service=settings.PAPERLESS_PAM_SERVICE,
            **kwargs,
        )
