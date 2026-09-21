"""Universal document sync — connector framework + incremental sync engine.

Phase 0: FakeConnector, schema-backed store, Redis/inline queues, ingest wire-up.
"""

from app.sources.factory import get_connector
from app.sources.sync_engine import run_sync

__all__ = ["get_connector", "run_sync"]
