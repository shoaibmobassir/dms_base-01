"""Lightweight trace spans for review/ingest observability."""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from architecture_sim.models import TraceSpan


@dataclass
class Tracer:
    spans: list[TraceSpan] = field(default_factory=list)
    _stack: list[tuple[str, float, dict[str, Any]]] = field(default_factory=list)

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[dict[str, Any]]:
        started = time.perf_counter() * 1000
        bag: dict[str, Any] = dict(attrs)
        self._stack.append((name, started, bag))
        try:
            yield bag
        finally:
            ended = time.perf_counter() * 1000
            self.spans.append(
                TraceSpan(name=name, started_ms=started, ended_ms=ended, attrs=dict(bag))
            )
            self._stack.pop()

    def summary(self) -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "duration_ms": round(s.duration_ms, 2),
                **s.attrs,
            }
            for s in self.spans
        ]
