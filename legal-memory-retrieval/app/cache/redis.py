from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import redis as redis_lib

from app.config import settings

_client: redis_lib.Redis | None = None


def _get_client() -> redis_lib.Redis | None:
    global _client
    if _client is not None:
        return _client
    if not settings.redis_url:
        return None
    try:
        _client = redis_lib.from_url(settings.redis_url, decode_responses=True)
        _client.ping()
    except Exception:
        _client = None
    return _client


def _cache_key(query: str, member_id: str | None, channels: list[str]) -> str:
    raw = json.dumps(
        {
            "q": query.strip().lower(),
            "m": member_id,
            "c": sorted(channels),
            "v": settings.index_version,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return f"retrieve:{digest}"


def cache_get(query: str, member_id: str | None, channels: list[str]) -> list[dict] | None:
    client = _get_client()
    if client is None:
        return None
    key = _cache_key(query, member_id, channels)
    try:
        raw = client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        return None


def cache_set(
    query: str,
    member_id: str | None,
    channels: list[str],
    hits: list[dict],
) -> None:
    client = _get_client()
    if client is None:
        return
    key = _cache_key(query, member_id, channels)
    try:
        client.setex(key, settings.cache_ttl_seconds, json.dumps(hits))
    except Exception:
        pass


def cache_stats() -> dict[str, Any]:
    client = _get_client()
    if client is None:
        return {"available": False}
    try:
        info = client.info("stats")
        return {
            "available": True,
            "hits": info.get("keyspace_hits", 0),
            "misses": info.get("keyspace_misses", 0),
        }
    except Exception:
        return {"available": False}
