"""Model warm-up state, reported by /api/system/ready.

A replica that has not loaded the embedder and cross-encoder answers its first
questions 10–17 s late, so it must not receive traffic until warm.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_state = "not_started"  # not_started | warming | ok | failed | skipped
_lock = threading.Lock()


def state() -> str:
    return _state


def _set(value: str) -> None:
    global _state
    with _lock:
        _state = value


def skip() -> None:
    _set("skipped")


def warm() -> None:
    """Load retrieval models off the request path (runs in a daemon thread)."""
    _set("warming")
    try:
        from app.retrieval.engine_v2 import _get_embedder
        from app.retrieval.reranker import _predict

        _get_embedder().encode(["warm up"])
        _predict([("warm up", "warm up")])
        _set("ok")
        logger.info("Retrieval models warmed")
    except Exception as exc:
        _set("failed")
        logger.warning("Model warm-up failed: %s", exc)


def start_background() -> None:
    threading.Thread(target=warm, name="warm-models", daemon=True).start()
