"""Simple per-identity sliding-window rate limiter (no external dependency).

Used on expensive LLM endpoints so a single key cannot saturate the provider.
In-process only — sufficient for a single uvicorn worker; multi-worker
deployments should put a shared limiter (Redis) in front.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, status

_lock = threading.Lock()
_windows: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(key: str, *, limit: int, window_seconds: float) -> None:
    """Raise 429 if ``key`` has exceeded ``limit`` events in the sliding window."""
    if limit <= 0:
        return
    now = time.monotonic()
    cutoff = now - window_seconds
    with _lock:
        q = _windows[key]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded ({limit} per {int(window_seconds)}s)",
                headers={"Retry-After": str(max(1, int(window_seconds - (now - q[0]))))},
            )
        q.append(now)


def reset_for_tests() -> None:
    with _lock:
        _windows.clear()
