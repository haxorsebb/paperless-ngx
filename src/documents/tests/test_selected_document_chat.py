from __future__ import annotations

from unittest import mock

from django.contrib.auth.models import Permission
from django.contrib.auth.models import User
from guardian.shortcuts import assign_perm
from rest_framework import status
from rest_framework.test import APITestCase

from documents.models import Document


class TestChatStreamingViewDocumentIds(APITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.user = User.objects.create_user(username="document_scope_user")
        self.user.user_permissions.add(
            *Permission.objects.filter(codename="view_document"),
        )
        self.client.force_authenticate(user=self.user)

    def _document(self, title: str, checksum: str) -> Document:
        return Document.objects.create(title=title, checksum=checksum)

    def test_document_ids_restrict_chat_to_exact_requested_documents(self) -> None:
        first = self._document("First", "chat-scope-first")
        second = self._document("Second", "chat-scope-second")
        excluded = self._document("Excluded", "chat-scope-excluded")

        for document in (first, second, excluded):
            assign_perm("view_document", self.user, document)

        with (
            mock.patch("documents.views.AIConfig") as ai_config,
            mock.patch(
                "documents.views.stream_chat_with_documents",
                return_value=iter(()),
            ) as stream_chat,
        ):
            ai_config.return_value.ai_enabled = True
            response = self.client.post(
                "/api/documents/chat/",
                {
                    "q": "Compare these documents",
                    "document_ids": [first.pk, second.pk],
                },
                format="json",
            )

        assert response.status_code == status.HTTP_200_OK
        call_kwargs = stream_chat.call_args.kwargs
        assert set(call_kwargs["documents"].values_list("pk", flat=True)) == {
            first.pk,
            second.pk,
        }
        assert excluded.pk not in set(
            call_kwargs["documents"].values_list("pk", flat=True),
        )
        assert call_kwargs["unrestricted"] is False

    def test_document_ids_reject_missing_document(self) -> None:
        visible = self._document("Visible", "chat-scope-visible")
        assign_perm("view_document", self.user, visible)
        missing_id = visible.pk + 100000

        with (
            mock.patch("documents.views.AIConfig") as ai_config,
            mock.patch(
                "documents.views.stream_chat_with_documents",
                return_value=iter(()),
            ) as stream_chat,
        ):
            ai_config.return_value.ai_enabled = True
            response = self.client.post(
                "/api/documents/chat/",
                {
                    "q": "Compare these documents",
                    "document_ids": [visible.pk, missing_id],
                },
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert b"Document not found" in response.content
        stream_chat.assert_not_called()

    def test_document_ids_reject_unauthorized_document(self) -> None:
        visible = self._document("Visible", "chat-scope-authorized")
        hidden = self._document("Hidden", "chat-scope-hidden")
        assign_perm("view_document", self.user, visible)

        with (
            mock.patch("documents.views.AIConfig") as ai_config,
            mock.patch(
                "documents.views.stream_chat_with_documents",
                return_value=iter(()),
            ) as stream_chat,
        ):
            ai_config.return_value.ai_enabled = True
            response = self.client.post(
                "/api/documents/chat/",
                {
                    "q": "Compare these documents",
                    "document_ids": [visible.pk, hidden.pk],
                },
                format="json",
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert b"Insufficient permissions" in response.content
        stream_chat.assert_not_called()

    def test_document_id_and_document_ids_are_mutually_exclusive(self) -> None:
        document = self._document("Document", "chat-scope-ambiguous")
        assign_perm("view_document", self.user, document)

        with (
            mock.patch("documents.views.AIConfig") as ai_config,
            mock.patch(
                "documents.views.stream_chat_with_documents",
                return_value=iter(()),
            ) as stream_chat,
        ):
            ai_config.return_value.ai_enabled = True
            response = self.client.post(
                "/api/documents/chat/",
                {
                    "q": "Question",
                    "document_id": document.pk,
                    "document_ids": [document.pk],
                },
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        stream_chat.assert_not_called()

    def test_document_ids_must_not_be_empty(self) -> None:
        with mock.patch("documents.views.AIConfig") as ai_config:
            ai_config.return_value.ai_enabled = True
            response = self.client.post(
                "/api/documents/chat/",
                {"q": "Question", "document_ids": []},
                format="json",
            )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
