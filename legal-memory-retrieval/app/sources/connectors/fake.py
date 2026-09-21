"""In-memory connector for Phase 0 tests and local demos."""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.sources.models import (
    AccountInfo,
    ChangeItem,
    ChangeType,
    FileMetadata,
    Permission,
    Scope,
    SyncPage,
    WebhookHandle,
)


@dataclass
class _FakeBlob:
    metadata: FileMetadata
    content: bytes
    permissions: list[Permission] = field(default_factory=list)


class FakeConnector:
    """Deterministic provider: seed files, then mutate to emit incremental changes."""

    def __init__(
        self,
        *,
        account_id: str = "fake-account-1",
        display_name: str = "Fake Drive",
        page_size: int = 50,
    ) -> None:
        self._account_id = account_id
        self._display_name = display_name
        self._page_size = max(1, page_size)
        self._files: dict[str, _FakeBlob] = {}
        self._change_log: list[ChangeItem] = []
        self._authenticated = False

    def seed_file(
        self,
        provider_file_id: str,
        name: str,
        content: bytes,
        *,
        mime_type: str = "text/plain",
        path: str | None = None,
        etag: str | None = None,
        content_hash: str | None = None,
        permissions: list[Permission] | None = None,
        parent_provider_file_id: str | None = None,
    ) -> FileMetadata:
        import hashlib

        now = datetime.now(timezone.utc)
        meta = FileMetadata(
            provider_file_id=provider_file_id,
            name=name,
            mime_type=mime_type,
            size_bytes=len(content),
            parent_provider_file_id=parent_provider_file_id,
            path=path or name,
            etag=etag or f"etag-{provider_file_id}-1",
            content_hash=content_hash or hashlib.sha256(content).hexdigest(),
            created_at=now,
            modified_at=now,
            is_folder=False,
        )
        self._files[provider_file_id] = _FakeBlob(
            metadata=meta,
            content=content,
            permissions=list(permissions or []),
        )
        self._change_log.append(
            ChangeItem(
                change_type=ChangeType.created,
                provider_file_id=provider_file_id,
                metadata=meta,
            )
        )
        return meta

    def mutate_file(self, provider_file_id: str, content: bytes) -> FileMetadata:
        import hashlib

        blob = self._files[provider_file_id]
        now = datetime.now(timezone.utc)
        prev = blob.metadata
        meta = FileMetadata(
            provider_file_id=prev.provider_file_id,
            name=prev.name,
            mime_type=prev.mime_type,
            size_bytes=len(content),
            parent_provider_file_id=prev.parent_provider_file_id,
            path=prev.path,
            web_url=prev.web_url,
            created_at=prev.created_at,
            modified_at=now,
            etag=f"etag-{provider_file_id}-{len(self._change_log) + 1}",
            content_hash=hashlib.sha256(content).hexdigest(),
            is_folder=False,
        )
        blob.metadata = meta
        blob.content = content
        self._change_log.append(
            ChangeItem(
                change_type=ChangeType.modified,
                provider_file_id=provider_file_id,
                metadata=meta,
            )
        )
        return meta

    def delete_file(self, provider_file_id: str) -> None:
        self._files.pop(provider_file_id, None)
        self._change_log.append(
            ChangeItem(
                change_type=ChangeType.deleted,
                provider_file_id=provider_file_id,
                metadata=None,
            )
        )

    def set_permissions(
        self, provider_file_id: str, permissions: list[Permission]
    ) -> None:
        blob = self._files[provider_file_id]
        blob.permissions = list(permissions)
        self._change_log.append(
            ChangeItem(
                change_type=ChangeType.permission_only,
                provider_file_id=provider_file_id,
                metadata=blob.metadata,
            )
        )

    def reemit_unchanged(self, provider_file_id: str) -> None:
        """Emit a modified change with the same content hash (idempotency tests)."""
        blob = self._files[provider_file_id]
        self._change_log.append(
            ChangeItem(
                change_type=ChangeType.modified,
                provider_file_id=provider_file_id,
                metadata=blob.metadata,
            )
        )

    # ── DocumentConnector ───────────────────────────────────────────────

    def authenticate(self) -> None:
        self._authenticated = True

    def get_account(self) -> AccountInfo:
        return AccountInfo(
            provider_account_id=self._account_id,
            display_name=self._display_name,
        )

    def list_files(self, cursor: str | None, scope: Scope) -> SyncPage:
        ids = sorted(self._files.keys())
        start = int(cursor) if cursor else 0
        end = start + self._page_size
        slice_ids = ids[start:end]
        items = [
            ChangeItem(
                change_type=ChangeType.created,
                provider_file_id=fid,
                metadata=self._files[fid].metadata,
            )
            for fid in slice_ids
        ]
        done = end >= len(ids)
        return SyncPage(
            items=items,
            next_cursor=None if done else str(end),
            done=done,
            cursor_kind="page_token",
        )

    def get_file(self, provider_file_id: str) -> FileMetadata:
        return self._files[provider_file_id].metadata

    def download_file(self, provider_file_id: str) -> Iterator[bytes]:
        yield self._files[provider_file_id].content

    def get_changes(self, cursor: str | None, scope: Scope) -> SyncPage:
        """Cursor is an integer index into the change log.

        Empty cursor → full discovery via list_files semantics, then
        advance cursor to end of current change log.
        """
        if cursor is None or cursor == "":
            page = self.list_files(None, scope)
            # After initial discovery, next incremental cursor is log length.
            if page.done:
                return SyncPage(
                    items=page.items,
                    next_cursor=str(len(self._change_log)),
                    done=True,
                    cursor_kind="page_token",
                )
            return page

        start = int(cursor)
        end = min(start + self._page_size, len(self._change_log))
        items = self._change_log[start:end]
        done = end >= len(self._change_log)
        return SyncPage(
            items=items,
            next_cursor=str(end),
            done=done,
            cursor_kind="page_token",
        )

    def get_permissions(self, provider_file_id: str) -> list[Permission]:
        blob = self._files.get(provider_file_id)
        if not blob:
            return []
        return list(blob.permissions)

    def create_webhook(self, callback_url: str) -> WebhookHandle | None:
        return None

    def disconnect(self) -> None:
        self._authenticated = False
