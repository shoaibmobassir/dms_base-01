"""Content-addressed blobs (plan 22, W0): the same bytes are stored once; collected when nothing uses them.

A blob is referenced by any version (its stored or raw file), a document's source, or an upload batch file.
Collection waits a grace period so an upload that has stored its bytes but not yet written its rows is never
collected underneath it.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from app.storage.object_store import get_object_store

log = logging.getLogger(__name__)

_REFERENCED = """
    EXISTS (SELECT 1 FROM document_versions v WHERE v.storage_uri = b.storage_uri OR v.source_storage_uri = b.storage_uri)
    OR EXISTS (SELECT 1 FROM documents d WHERE d.source_uri = b.storage_uri)
    OR EXISTS (SELECT 1 FROM upload_batch_files f WHERE f.storage_uri = b.storage_uri)
"""


def is_referenced(conn, storage_uri: str) -> bool:
    row = conn.execute(f"SELECT ({_REFERENCED}) AS used FROM (SELECT %s::text AS storage_uri) b", (storage_uri,)).fetchone()
    return bool(row["used"])


def collect(conn, *, grace: timedelta = timedelta(hours=24), only: list[str] | None = None, dry_run: bool = False) -> list[str]:
    """Delete blobs nothing references, older than ``grace`` (or only the given hashes). Returns hashes removed."""
    params: dict = {"grace": grace, "only": only}
    rows = conn.execute(
        f"""SELECT b.content_sha256, b.storage_uri FROM blobs b
            WHERE b.created_at < now() - %(grace)s
              AND (%(only)s::text[] IS NULL OR b.content_sha256 = ANY(%(only)s))
              AND NOT ({_REFERENCED})""", params).fetchall()
    if dry_run:
        return [r["content_sha256"] for r in rows]
    store = get_object_store()
    removed = []
    for r in rows:
        try:
            store.delete(r["storage_uri"])
        except FileNotFoundError:
            pass
        except Exception:  # noqa: BLE001 — keep the row so a later run retries
            log.exception("blob delete failed: %s", r["storage_uri"])
            continue
        conn.execute("DELETE FROM blobs WHERE content_sha256 = %s", (r["content_sha256"],))
        removed.append(r["content_sha256"])
    conn.commit()
    return removed
