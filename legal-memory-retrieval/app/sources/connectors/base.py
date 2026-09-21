"""DocumentConnector protocol — provider-agnostic sync surface."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from app.sources.models import (
    AccountInfo,
    FileMetadata,
    Permission,
    Scope,
    SyncPage,
    WebhookHandle,
)


@runtime_checkable
class DocumentConnector(Protocol):
    """Sync engine talks only to this interface."""

    def authenticate(self) -> None: ...

    def get_account(self) -> AccountInfo: ...

    def list_files(self, cursor: str | None, scope: Scope) -> SyncPage: ...

    def get_file(self, provider_file_id: str) -> FileMetadata: ...

    def download_file(self, provider_file_id: str) -> Iterator[bytes]: ...

    def get_changes(self, cursor: str | None, scope: Scope) -> SyncPage: ...

    def get_permissions(self, provider_file_id: str) -> list[Permission]: ...

    def create_webhook(self, callback_url: str) -> WebhookHandle | None: ...

    def disconnect(self) -> None: ...
