"""Sync DB access via a process-wide connection pool.

Scripts and tests that never call ``init_sync_pool`` still work: the first
``connect()`` opens a small pool lazily. The FastAPI lifespan opens the pool
eagerly so the first request is not charged for pool startup.
"""
from __future__ import annotations

import atexit
import logging
import threading
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
_lock = threading.Lock()


def init_sync_pool() -> None:
    """Open the sync pool. Idempotent; safe to call from app startup."""
    global _pool
    with _lock:
        if _pool is not None:
            return
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=settings.db_pool_min_size,
            max_size=settings.db_pool_max_size,
            max_idle=settings.db_pool_max_idle,
            kwargs={"row_factory": dict_row},
            open=False,
            name="firmos-sync",
        )
        _pool.open(wait=True)
        atexit.register(close_sync_pool)
        logger.info(
            "Sync DB pool initialized: min=%d max=%d",
            settings.db_pool_min_size,
            settings.db_pool_max_size,
        )


def close_sync_pool() -> None:
    global _pool
    with _lock:
        if _pool is None:
            return
        try:
            _pool.close()
        except Exception as exc:
            logger.debug("Sync pool close: %s", exc)
        _pool = None
        logger.info("Sync DB pool closed")


def _ensure_pool() -> ConnectionPool:
    if _pool is None:
        init_sync_pool()
    assert _pool is not None
    return _pool


@contextmanager
def connect():
    pool = _ensure_pool()
    with pool.connection() as conn:
        yield conn
