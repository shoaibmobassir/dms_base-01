"""Async connection pools, one per event loop.

Reasoning:
  An ``AsyncConnectionPool`` belongs to the event loop that opened it: its
  connections' sockets, its grow/return workers and its waiters all live on
  that loop. The API has two kinds of async callers:

    - async endpoints (reviews, retrieval debugger) on uvicorn's loop;
    - sync endpoints (Ask the Firm, search, chat tools) that run the async
      retrieval engine on background loop workers (``app.db.loop``).

  A single global pool shared across those loops strands connections: a
  request that needs more than the idle connections waits the full pool
  timeout (30 s) on a loop that will never serve it, and the channel silently
  returns nothing. So pools are keyed by the running loop. Each loop gets its
  own bounded pool; pools of loops that have been closed are dropped.

  Sizing: uvicorn's loop gets the configured min/max; each background loop
  worker gets a small pool (it runs at most a few requests' channels at once).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import settings

logger = logging.getLogger(__name__)

# Seconds to wait for a connection before failing loudly (was the 30 s default).
ACQUIRE_TIMEOUT = 10.0
WORKER_POOL_MAX = 6

_pools: dict[int, tuple[asyncio.AbstractEventLoop, AsyncConnectionPool]] = {}


def _prune_closed() -> None:
    for key, (loop, _pool) in list(_pools.items()):
        if loop.is_closed():
            _pools.pop(key, None)


async def init_pool(*, worker: bool = False) -> None:
    """Open the pool for the running event loop. Idempotent per loop."""
    loop = asyncio.get_running_loop()
    _prune_closed()
    if id(loop) in _pools:
        return
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=1 if worker else settings.db_pool_min_size,
        max_size=WORKER_POOL_MAX if worker else settings.db_pool_max_size,
        max_idle=settings.db_pool_max_idle,
        timeout=ACQUIRE_TIMEOUT,
        kwargs={"row_factory": dict_row},
        open=False,
        name=f"firmos-async-{'worker' if worker else 'main'}-{len(_pools)}",
    )
    _pools[id(loop)] = (loop, pool)
    await pool.open()
    await pool.wait()
    logger.info("DB pool initialized for loop %s (worker=%s)", id(loop), worker)


async def close_pool() -> None:
    """Close the running loop's pool. Call during app / worker shutdown."""
    loop = asyncio.get_running_loop()
    entry = _pools.pop(id(loop), None)
    if entry is not None:
        await entry[1].close()
        logger.info("DB pool closed for loop %s", id(loop))


@asynccontextmanager
async def acquire():
    """Acquire an async connection from the running loop's pool.

    Usage:
        async with acquire() as conn:
            rows = await conn.execute("SELECT ...")
    """
    loop = asyncio.get_running_loop()
    entry = _pools.get(id(loop))
    if entry is None or entry[0] is not loop:
        await init_pool()
        entry = _pools[id(loop)]
    async with entry[1].connection() as conn:
        yield conn


def pool_stats() -> dict:
    """Aggregate statistics across every live pool (health checks, metrics)."""
    _prune_closed()
    if not _pools:
        return {"initialized": False}
    totals = {"pool_min": 0, "pool_max": 0, "pool_size": 0, "pool_available": 0,
              "requests_waiting": 0, "requests_num": 0, "requests_errors": 0}
    for _loop, pool in _pools.values():
        stats = pool.get_stats()
        for key in totals:
            totals[key] += int(stats.get(key, 0) or 0)
    return {"initialized": True, "pools": len(_pools), **totals}
