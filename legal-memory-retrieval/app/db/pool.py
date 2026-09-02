"""Async connection pool for production-grade DB access.

Reasoning:
  The original connection.py opens a fresh psycopg connection per request/thread.
  At scale (millions of docs, concurrent users), this causes:
    - Connection churn overhead (~5-10ms per connect)
    - Risk of exhausting PostgreSQL max_connections
    - No connection reuse across channels in the same request

  psycopg_pool.AsyncConnectionPool maintains a warmed pool of connections
  that are checked out/returned, amortizing connection setup cost to near-zero
  and bounding total connections to the configured max_size.

  Pool sizing rationale:
    min_size=4  — enough for baseline health checks + single request
    max_size=20 — supports ~5 concurrent requests × 4 channels each
    max_idle=300 — reclaim idle connections after 5 minutes
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None


async def init_pool() -> None:
    """Initialize the global async connection pool. Call once during app startup."""
    global _pool
    if _pool is not None:
        return

    _pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        max_idle=settings.db_pool_max_idle,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    await _pool.open()
    await _pool.wait()
    logger.info(
        "DB pool initialized: min=%d max=%d",
        settings.db_pool_min_size,
        settings.db_pool_max_size,
    )


async def close_pool() -> None:
    """Close the global pool. Call during app shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("DB pool closed")


@asynccontextmanager
async def acquire():
    """Acquire an async connection from the pool.

    Usage:
        async with acquire() as conn:
            rows = await conn.execute("SELECT ...")
    """
    if _pool is None:
        raise RuntimeError("DB pool not initialized. Call init_pool() first.")
    async with _pool.connection() as conn:
        yield conn


def pool_stats() -> dict:
    """Return current pool statistics for health checks and metrics."""
    if _pool is None:
        return {"initialized": False}
    stats = _pool.get_stats()
    return {
        "initialized": True,
        "pool_min": stats.get("pool_min", 0),
        "pool_max": stats.get("pool_max", 0),
        "pool_size": stats.get("pool_size", 0),
        "pool_available": stats.get("pool_available", 0),
        "requests_waiting": stats.get("requests_waiting", 0),
        "requests_num": stats.get("requests_num", 0),
    }
