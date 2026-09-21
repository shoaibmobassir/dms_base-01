"""Shared dataclasses for the universal source sync engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ChangeType(str, Enum):
    created = "created"
    modified = "modified"
    deleted = "deleted"
    permission_only = "permission_only"


class Provider(str, Enum):
    fake = "fake"
    google_drive = "google_drive"
    microsoft_graph = "microsoft_graph"


@dataclass(frozen=True)
class Scope:
    key: str = "default"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountInfo:
    provider_account_id: str
    display_name: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class Permission:
    principal_type: str  # user | group | anyone | domain
    principal_id: str
    permission: str = "read"


@dataclass
class FileMetadata:
    provider_file_id: str
    name: str
    mime_type: str | None = None
    size_bytes: int | None = None
    parent_provider_file_id: str | None = None
    path: str | None = None
    web_url: str | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    etag: str | None = None
    content_hash: str | None = None
    is_folder: bool = False


@dataclass
class ChangeItem:
    change_type: ChangeType
    provider_file_id: str
    metadata: FileMetadata | None = None


@dataclass
class SyncPage:
    items: list[ChangeItem]
    next_cursor: str | None
    done: bool
    cursor_kind: str = "page_token"


@dataclass
class WebhookHandle:
    webhook_id: str
    expires_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectionRecord:
    connection_id: str
    organization_id: str
    provider: str
    provider_account_id: str | None
    display_name: str | None
    status: str
    config: dict[str, Any]
    created_by_member_id: str | None = None
    encrypted_access_token: str | None = None
    encrypted_refresh_token: str | None = None


@dataclass
class SyncStateRecord:
    connection_id: str
    scope_key: str
    cursor: str | None
    cursor_kind: str | None
    sync_status: str
    consecutive_failures: int = 0
    error_message: str | None = None
