"""Version-keyed multi-tier cache (content + pipeline versions, not TTL-only)."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VersionedCache:
    """
    Keys look like:
      review:{tenant}:{doc}:{version}:{feature}:{model_v}
      summary:{doc}:{content_hash}:{summary_v}
    """

    store: dict[str, Any] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def key(self, *parts: str) -> str:
        return ":".join(str(p) for p in parts)

    def get(self, *parts: str) -> Any | None:
        k = self.key(*parts)
        with self._lock:
            if k in self.store:
                self.hits += 1
                return self.store[k]
            self.misses += 1
            return None

    def set(self, value: Any, *parts: str) -> None:
        with self._lock:
            self.store[self.key(*parts)] = value

    @property
    def hit_rate(self) -> float:
        with self._lock:
            total = self.hits + self.misses
            return self.hits / total if total else 0.0

    def stats(self) -> dict[str, float | int]:
        with self._lock:
            total = self.hits + self.misses
            hit_rate = self.hits / total if total else 0.0
            return {
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(hit_rate, 4),
                "entries": len(self.store),
            }
