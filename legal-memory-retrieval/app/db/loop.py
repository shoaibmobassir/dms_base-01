"""Long-lived background event loops for running async code from sync code.

Sync callers (FastAPI sync endpoints in the threadpool, chat tools, scripts)
used to call ``asyncio.run(...)`` per request, creating and destroying an
event loop each time. Async resources opened on one of those loops — the
connection pool above all — are unusable once it closes.

Here a few daemon threads each run one event loop forever. ``run_sync``
submits a coroutine to them round-robin and blocks for the result. Several
workers keep CPU-bound steps inside retrieval (embedding, cross-encoder)
from serialising concurrent requests behind a single loop.
"""
from __future__ import annotations

import asyncio
import atexit
import itertools
import os
import threading
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

_workers: list[asyncio.AbstractEventLoop] = []
_lock = threading.Lock()
_rr = itertools.count()


def _worker_count() -> int:
    try:
        return max(1, min(16, int(os.environ.get("ASYNC_LOOP_WORKERS", "4"))))
    except ValueError:
        return 4


def _start_worker(index: int) -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.call_soon(ready.set)
        loop.run_forever()

    threading.Thread(target=_run, name=f"async-loop-{index}", daemon=True).start()
    ready.wait()
    return loop


def _loops() -> list[asyncio.AbstractEventLoop]:
    if _workers:
        return _workers
    with _lock:
        if not _workers:
            _workers.extend(_start_worker(i) for i in range(_worker_count()))
            atexit.register(shutdown)
    return _workers


def is_worker_loop() -> bool:
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        return False
    return running in _workers


def run_sync(coro: Coroutine[Any, Any, T], timeout: float | None = None) -> T:
    """Run ``coro`` on a background loop worker and wait for its result.

    Must not be called from a worker loop itself (it would deadlock).
    """
    if is_worker_loop():
        coro.close()
        raise RuntimeError("run_sync() called from a background loop worker")
    loops = _loops()
    loop = loops[next(_rr) % len(loops)]
    return asyncio.run_coroutine_threadsafe(_on_worker(coro), loop).result(timeout)


async def _on_worker(coro: Coroutine[Any, Any, T]) -> T:
    from app.db.pool import init_pool

    await init_pool(worker=True)
    return await coro


def shutdown() -> None:
    """Close each worker's pool and stop its loop (app shutdown)."""
    from app.db.pool import close_pool

    with _lock:
        loops = list(_workers)
        _workers.clear()
    for loop in loops:
        try:
            asyncio.run_coroutine_threadsafe(close_pool(), loop).result(5)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
