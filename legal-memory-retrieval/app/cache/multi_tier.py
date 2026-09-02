"""Multi-tier caching for retrieval pipeline.

Tier architecture:
  L1 (Embedding):   In-process TTLCache — hash(text) → vector. Zero network cost.
  L2 (Channel):     Redis — hash(query+channel+member) → channel results.
  L3 (Retrieval):   Redis — hash(query+member+channels) → fused+reranked hits.
  L4 (Answer):      Redis — hash(query+member) → LLM answer JSON.
  L5 (Graph):       Redis — community_id → summary text.

Invalidation:
  On document ingest/update, the ingest pipeline publishes
  `cache:invalidate:{matter_id}` to a Redis pub/sub channel.
  This module subscribes and pattern-evicts matching keys.

  L1 (embeddings) is never invalidated — deterministic function of text.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from enum import Enum
from typing import Any

from cachetools import TTLCache

from app.config import settings

logger = logging.getLogger(__name__)

# ── Redis client (lazy init) ────────────────────────────────────────────────

_redis = None


def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    if not settings.redis_url:
        return None
    try:
        import redis as redis_lib

        _redis = redis_lib.from_url(settings.redis_url, decode_responses=True)
        _redis.ping()
        return _redis
    except Exception as exc:
        logger.warning("Redis unavailable: %s", exc)
        _redis = None
        return None


async def _get_async_redis():
    """Get async Redis client for non-blocking cache operations."""
    if not settings.redis_url:
        return None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        return client
    except Exception as exc:
        logger.warning("Async Redis unavailable: %s", exc)
        return None


# ── Cache tiers ──────────────────────────────────────────────────────────────


class CacheTier(str, Enum):
    EMBEDDING = "emb"
    CHANNEL = "ch"
    RETRIEVAL = "ret"
    ANSWER = "ans"
    GRAPH_COMMUNITY = "gc"


_TTL_MAP = {
    CacheTier.EMBEDDING: 86400,      # 24 hours — deterministic
    CacheTier.CHANNEL: 300,          # 5 minutes
    CacheTier.RETRIEVAL: 300,        # 5 minutes
    CacheTier.ANSWER: 900,           # 15 minutes
    CacheTier.GRAPH_COMMUNITY: 3600, # 1 hour
}


# ── L1: In-process embedding cache ──────────────────────────────────────────

_embedding_cache: TTLCache = TTLCache(maxsize=10_000, ttl=86400)

# Track L1 stats
_l1_hits = 0
_l1_misses = 0


def embedding_cache_get(text: str) -> list[float] | None:
    """Get cached embedding vector for text (L1 in-process)."""
    global _l1_hits, _l1_misses
    key = hashlib.sha256(text.encode()).hexdigest()[:16]
    result = _embedding_cache.get(key)
    if result is not None:
        _l1_hits += 1
    else:
        _l1_misses += 1
    return result


def embedding_cache_set(text: str, vector: list[float]) -> None:
    """Store embedding vector in L1 cache."""
    key = hashlib.sha256(text.encode()).hexdigest()[:16]
    _embedding_cache[key] = vector


def embedding_cache_stats() -> dict:
    """Return L1 cache hit/miss statistics."""
    total = _l1_hits + _l1_misses
    return {
        "hits": _l1_hits,
        "misses": _l1_misses,
        "hit_ratio": round(_l1_hits / total, 3) if total > 0 else 0.0,
        "size": len(_embedding_cache),
        "maxsize": _embedding_cache.maxsize,
    }


# ── L2-L5: Redis-backed caches ──────────────────────────────────────────────


def _cache_key(tier: CacheTier, *parts: str) -> str:
    """Build a deterministic, collision-free cache key."""
    raw = json.dumps(
        {"t": tier.value, "p": list(parts), "v": settings.index_version},
        sort_keys=True,
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return f"{tier.value}:{digest}"


async def cache_get_async(tier: CacheTier, *key_parts: str) -> Any | None:
    """Async cache lookup. Returns deserialized value or None."""
    client = await _get_async_redis()
    if client is None:
        return None
    key = _cache_key(tier, *key_parts)
    try:
        raw = await client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.debug("Cache get error [%s]: %s", key, exc)
        return None
    finally:
        await client.aclose()


async def cache_set_async(
    tier: CacheTier, *key_parts: str, value: Any, ttl: int | None = None
) -> None:
    """Async cache store with tier-appropriate TTL."""
    client = await _get_async_redis()
    if client is None:
        return
    key = _cache_key(tier, *key_parts)
    effective_ttl = ttl or _TTL_MAP.get(tier, 300)
    try:
        await client.setex(key, effective_ttl, json.dumps(value, default=str))
    except Exception as exc:
        logger.debug("Cache set error [%s]: %s", key, exc)
    finally:
        await client.aclose()


def cache_get(tier: CacheTier, *key_parts: str) -> Any | None:
    """Synchronous cache lookup (for backward compat)."""
    client = _get_redis()
    if client is None:
        return None
    key = _cache_key(tier, *key_parts)
    try:
        raw = client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        return None


def cache_set(
    tier: CacheTier, *key_parts: str, value: Any, ttl: int | None = None
) -> None:
    """Synchronous cache store (for backward compat)."""
    client = _get_redis()
    if client is None:
        return
    key = _cache_key(tier, *key_parts)
    effective_ttl = ttl or _TTL_MAP.get(tier, 300)
    try:
        client.setex(key, effective_ttl, json.dumps(value, default=str))
    except Exception:
        pass


# ── Cache invalidation ──────────────────────────────────────────────────────


async def invalidate_for_matter(matter_id: str) -> int:
    """Invalidate all cached results related to a matter.

    Called by the ingest pipeline after document changes.
    Uses Redis SCAN to find and delete matching keys.
    Returns the number of keys deleted.
    """
    client = await _get_async_redis()
    if client is None:
        return 0
    deleted = 0
    try:
        # Invalidate L2 (channel), L3 (retrieval), L4 (answer) tiers
        # We can't know which queries touched this matter, so we flush
        # all retrieval-tier caches. This is aggressive but correct.
        for tier in (CacheTier.CHANNEL, CacheTier.RETRIEVAL, CacheTier.ANSWER):
            pattern = f"{tier.value}:*"
            async for key in client.scan_iter(match=pattern, count=100):
                await client.delete(key)
                deleted += 1
    except Exception as exc:
        logger.warning("Cache invalidation error for matter %s: %s", matter_id, exc)
    finally:
        await client.aclose()
    logger.info("Invalidated %d cache keys for matter %s", deleted, matter_id)
    return deleted


def cache_stats() -> dict[str, Any]:
    """Return cache statistics across all tiers."""
    client = _get_redis()
    redis_stats: dict[str, Any] = {"available": False}
    if client is not None:
        try:
            info = client.info("stats")
            redis_stats = {
                "available": True,
                "hits": info.get("keyspace_hits", 0),
                "misses": info.get("keyspace_misses", 0),
            }
        except Exception:
            pass
    return {
        "l1_embedding": embedding_cache_stats(),
        "redis": redis_stats,
    }
