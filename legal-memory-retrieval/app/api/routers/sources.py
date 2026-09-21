"""Source connection + sync API (universal document sync Phase 0)."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.deps import resolve_member
from app.config import settings
from app.sources.connectors.fake import FakeConnector
from app.sources.crypto import encrypt_token
from app.sources.factory import register_fake_connector, unregister_fake_connector
from app.sources import store
from app.sources.sync_engine import run_sync

router = APIRouter(tags=["sources"])

SERVICE = "sources"


def _require_enabled() -> None:
    if not settings.sources_sync_enabled:
        raise HTTPException(
            status_code=503,
            detail="Source sync is disabled (set SOURCES_SYNC_ENABLED=true)",
        )


class FakeConnectRequest(BaseModel):
    matter_id: str
    display_name: str = "Fake Drive"
    files: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Optional seed files: {id, name, content_text, path?}",
    )


class SyncRequest(BaseModel):
    scope_key: str = "default"
    process_inline: Optional[bool] = None


@router.get("/health")
def sources_health() -> dict:
    return {
        "service": SERVICE,
        "status": "ok",
        "enabled": settings.sources_sync_enabled,
    }


@router.get("/connections")
def list_source_connections(
    member_id: str | None = Depends(resolve_member),
) -> dict:
    _require_enabled()
    rows = store.list_connections(organization_id=settings.tenant_id)
    return {"service": SERVICE, "connections": rows}


@router.post("/connections/fake")
def connect_fake(
    body: FakeConnectRequest,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    """Create a fake provider connection bound to one matter (Phase 0)."""
    _require_enabled()
    connection = store.create_connection(
        organization_id=settings.tenant_id,
        provider="fake",
        matter_id=body.matter_id,
        created_by_member_id=member_id,
        provider_account_id="fake-account-1",
        display_name=body.display_name,
        scopes=["fake.read"],
        encrypted_access_token=encrypt_token("fake-access-token"),
    )
    connector = FakeConnector(
        account_id="fake-account-1",
        display_name=body.display_name,
    )
    for f in body.files:
        fid = f.get("id") or f.get("provider_file_id")
        name = f.get("name") or "file.txt"
        text = f.get("content_text") or f.get("content") or ""
        if not fid:
            continue
        connector.seed_file(
            str(fid),
            name,
            str(text).encode("utf-8"),
            path=f.get("path") or name,
            mime_type=f.get("mime_type") or "text/plain",
        )
    register_fake_connector(connection.connection_id, connector)
    return {
        "service": SERVICE,
        "connection_id": connection.connection_id,
        "provider": connection.provider,
        "matter_id": body.matter_id,
        "seeded_files": len(body.files),
        "status": connection.status,
    }


@router.post("/connections/{connection_id}/sync")
def sync_connection(
    connection_id: str,
    body: SyncRequest | None = None,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    _require_enabled()
    body = body or SyncRequest()
    result = run_sync(
        connection_id,
        scope_key=body.scope_key,
        process_inline=body.process_inline,
    )
    if result.get("status") == "failed" and result.get("error") == "connection_not_found":
        raise HTTPException(status_code=404, detail="Connection not found")
    return {"service": SERVICE, **result}


@router.get("/connections/{connection_id}/files")
def list_files(
    connection_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    _require_enabled()
    if not store.get_connection(connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    return {
        "service": SERVICE,
        "connection_id": connection_id,
        "files": store.list_source_files(connection_id),
    }


@router.delete("/connections/{connection_id}")
def delete_connection(
    connection_id: str,
    member_id: str | None = Depends(resolve_member),
) -> dict:
    _require_enabled()
    if not store.get_connection(connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    store.disconnect_connection(connection_id)
    unregister_fake_connector(connection_id)
    return {"service": SERVICE, "connection_id": connection_id, "status": "disconnected"}
