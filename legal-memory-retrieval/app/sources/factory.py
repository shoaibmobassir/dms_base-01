"""Resolve a DocumentConnector for a connection record."""
from __future__ import annotations

from app.sources.connectors.base import DocumentConnector
from app.sources.connectors.fake import FakeConnector
from app.sources.models import ConnectionRecord, Provider

# Process-local FakeConnector instances keyed by connection_id (tests / demos).
_FAKE_REGISTRY: dict[str, FakeConnector] = {}


def register_fake_connector(connection_id: str, connector: FakeConnector) -> None:
    _FAKE_REGISTRY[connection_id] = connector


def unregister_fake_connector(connection_id: str) -> None:
    _FAKE_REGISTRY.pop(connection_id, None)


def clear_fake_registry() -> None:
    _FAKE_REGISTRY.clear()


def get_connector(connection: ConnectionRecord) -> DocumentConnector:
    provider = connection.provider
    if provider == Provider.fake.value or provider == "fake":
        existing = _FAKE_REGISTRY.get(connection.connection_id)
        if existing is not None:
            return existing
        connector = FakeConnector(
            account_id=connection.provider_account_id or "fake-account",
            display_name=connection.display_name or "Fake Drive",
        )
        _FAKE_REGISTRY[connection.connection_id] = connector
        return connector

    if provider == Provider.google_drive.value:
        raise NotImplementedError("Google Drive connector ships in Phase A")
    if provider == Provider.microsoft_graph.value:
        raise NotImplementedError("Microsoft Graph connector ships in Phase B")
    raise ValueError(f"Unknown provider: {provider}")
