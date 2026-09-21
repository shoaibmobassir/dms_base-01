"""Redis list queues with in-process fallback for source sync jobs."""
from __future__ import annotations

import json
import logging
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Callable

from app.cache.redis import _get_client
from app.config import settings

log = logging.getLogger(__name__)

QUEUE_SYNC = "sources:sync"
QUEUE_DOWNLOAD = "sources:download"
QUEUE_PROCESS = "sources:process"
QUEUE_PERMISSIONS = "sources:permissions"

_INLINE: dict[str, deque[dict[str, Any]]] = {
    QUEUE_SYNC: deque(),
    QUEUE_DOWNLOAD: deque(),
    QUEUE_PROCESS: deque(),
    QUEUE_PERMISSIONS: deque(),
}


@dataclass
class SourceJob:
    job_type: str
    connection_id: str
    payload: dict[str, Any]
    attempt: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceJob:
        return cls(
            job_type=data["job_type"],
            connection_id=data["connection_id"],
            payload=data.get("payload") or {},
            attempt=int(data.get("attempt") or 0),
        )


def enqueue(job: SourceJob) -> None:
    raw = json.dumps(job.to_dict())
    client = None if settings.sources_queue_inline else _get_client()
    if client is not None:
        try:
            client.lpush(job.job_type, raw)
            return
        except Exception as exc:
            log.warning("Redis enqueue failed, falling back to inline: %s", exc)
    _INLINE.setdefault(job.job_type, deque()).append(job.to_dict())


def dequeue(queue_name: str) -> SourceJob | None:
    client = None if settings.sources_queue_inline else _get_client()
    if client is not None:
        try:
            raw = client.rpop(queue_name)
            if raw:
                return SourceJob.from_dict(json.loads(raw))
        except Exception as exc:
            log.warning("Redis dequeue failed: %s", exc)
    q = _INLINE.get(queue_name)
    if q:
        return SourceJob.from_dict(q.popleft())
    return None


def clear_inline_queues() -> None:
    for q in _INLINE.values():
        q.clear()


def drain_inline(
    handlers: dict[str, Callable[[SourceJob], None]],
    *,
    max_jobs: int = 500,
) -> int:
    """Process queued inline jobs until empty or max_jobs. Returns count processed."""
    processed = 0
    while processed < max_jobs:
        progressed = False
        for queue_name, handler in handlers.items():
            job = dequeue(queue_name)
            if job is None:
                continue
            handler(job)
            processed += 1
            progressed = True
            if processed >= max_jobs:
                break
        if not progressed:
            break
    return processed


def backoff_seconds(attempt: int) -> float:
    base = settings.sources_sync_backoff_base_seconds
    return min(60.0, base * (2 ** max(0, attempt)))
