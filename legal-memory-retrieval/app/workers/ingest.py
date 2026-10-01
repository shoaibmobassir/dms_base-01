"""Ingest worker: parses, indexes and embeds queued upload batches off the API process.

    python -m app.workers.ingest            # run until SIGTERM/SIGINT
    python -m app.workers.ingest --once     # process at most one batch and exit

Batches are claimed with ``FOR UPDATE SKIP LOCKED`` so any number of workers can run.
A batch whose worker stopped heartbeating for INGEST_STALE_MINUTES is reclaimed.
Per-file failures are isolated inside ``process_upload_batch``.
"""
from __future__ import annotations

import argparse
import logging
import signal
import threading

from app.config import settings
from app.db.connection import connect
from app.ingest.upload_batch import process_upload_batch

log = logging.getLogger("ingest-worker")
_stop = threading.Event()

CLAIM_SQL = """
UPDATE upload_batches SET status = 'running', updated_at = now()
WHERE batch_id = (
    SELECT batch_id FROM upload_batches
    WHERE status = 'queued'
       OR (status = 'running' AND updated_at < now() - make_interval(mins => %(stale)s))
    ORDER BY created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING batch_id, created_by
"""


def enqueue(batch_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE upload_batches SET status = 'queued', updated_at = now() WHERE batch_id = %s AND status <> 'running'",
            (batch_id,),
        )
        conn.commit()


def run_once() -> str | None:
    """Claim and process one batch. Returns its id, or None if the queue is empty."""
    with connect() as conn:
        row = conn.execute(CLAIM_SQL, {"stale": settings.ingest_stale_minutes}).fetchone()
        conn.commit()
    if row is None:
        return None
    batch_id = row["batch_id"]
    log.info("processing batch %s", batch_id)
    try:
        result = process_upload_batch(batch_id, created_by=row["created_by"])
        log.info("batch %s: %s (indexed %s, failed %s)", batch_id, result["status"], result["indexed"], result["failed"])
    except Exception:  # noqa: BLE001 — never kill the worker; mark and move on
        log.exception("batch %s crashed", batch_id)
        with connect() as conn:
            conn.execute("UPDATE upload_batches SET status = 'failed', updated_at = now() WHERE batch_id = %s", (batch_id,))
            conn.commit()
    return batch_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    from app.observability import redaction

    redaction.install()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: _stop.set())

    if args.once:
        run_once()
        return 0
    log.info("ingest worker started (stale after %s min)", settings.ingest_stale_minutes)
    while not _stop.is_set():
        if run_once() is None:
            _stop.wait(args.poll_seconds)
    log.info("ingest worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
