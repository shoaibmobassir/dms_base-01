"""Circuit breaker implementation for LLM providers and external services.

Implements the standard three-state circuit breaker pattern:
  CLOSED → (failures >= threshold) → OPEN → (timeout elapsed) → HALF_OPEN → (probe succeeds) → CLOSED
                                                                             (probe fails) → OPEN

Each provider (groq, gemini, etc.) gets its own CircuitBreaker instance.
When a circuit is OPEN, requests immediately fall through to the next provider
in the chain, avoiding wasted timeouts on known-broken services.

Metrics are exposed via the provider_circuit_state Prometheus gauge.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"       # Normal operation, requests flow through
    OPEN = "open"           # Service is down, requests fail fast
    HALF_OPEN = "half_open" # Probing — allow one request to test recovery


@dataclass
class CircuitBreaker:
    """Per-provider circuit breaker.

    Args:
        name: Provider name (e.g., "groq", "gemini")
        failure_threshold: Consecutive failures before opening circuit
        recovery_timeout: Seconds to wait before probing (OPEN → HALF_OPEN)
        success_threshold: Consecutive successes in HALF_OPEN before closing
    """

    name: str
    failure_threshold: int = 3
    recovery_timeout: float = 60.0
    success_threshold: int = 1
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _consecutive_failures: int = field(default=0, init=False)
    _consecutive_successes: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _last_state_change: float = field(default_factory=time.time, init=False)
    _total_failures: int = field(default=0, init=False)
    _total_successes: int = field(default=0, init=False)
    _total_rejected: int = field(default=0, init=False)

    @property
    def state(self) -> CircuitState:
        """Current state, with automatic OPEN → HALF_OPEN transition."""
        if self._state == CircuitState.OPEN:
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._transition(CircuitState.HALF_OPEN)
        return self._state

    @property
    def is_available(self) -> bool:
        """Whether the circuit allows requests."""
        return self.state != CircuitState.OPEN

    def record_success(self) -> None:
        """Record a successful call."""
        self._total_successes += 1
        self._consecutive_failures = 0
        self._consecutive_successes += 1

        if self._state == CircuitState.HALF_OPEN:
            if self._consecutive_successes >= self.success_threshold:
                self._transition(CircuitState.CLOSED)
                logger.info("Circuit breaker [%s] CLOSED — service recovered", self.name)
        elif self._state == CircuitState.CLOSED:
            pass  # Already closed, all good

    def record_failure(self, error: Exception | None = None) -> None:
        """Record a failed call."""
        self._total_failures += 1
        self._consecutive_failures += 1
        self._consecutive_successes = 0
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            # Probe failed — reopen
            self._transition(CircuitState.OPEN)
            logger.warning(
                "Circuit breaker [%s] re-OPENED — probe failed: %s",
                self.name,
                error,
            )
        elif self._state == CircuitState.CLOSED:
            if self._consecutive_failures >= self.failure_threshold:
                self._transition(CircuitState.OPEN)
                logger.warning(
                    "Circuit breaker [%s] OPENED — %d consecutive failures. "
                    "Recovery in %.0fs. Last error: %s",
                    self.name,
                    self._consecutive_failures,
                    self.recovery_timeout,
                    error,
                )

    def record_rejection(self) -> None:
        """Record a rejected request (circuit was OPEN)."""
        self._total_rejected += 1

    def _transition(self, new_state: CircuitState) -> None:
        self._state = new_state
        self._last_state_change = time.time()
        if new_state == CircuitState.CLOSED:
            self._consecutive_failures = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._consecutive_successes = 0

    def stats(self) -> dict[str, Any]:
        """Return stats for monitoring/health checks."""
        return {
            "name": self.name,
            "state": self.state.value,
            "consecutive_failures": self._consecutive_failures,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "total_rejected": self._total_rejected,
            "last_failure_ago_s": (
                round(time.time() - self._last_failure_time, 1)
                if self._last_failure_time > 0
                else None
            ),
            "recovery_timeout_s": self.recovery_timeout,
        }


# ── Global registry ─────────────────────────────────────────────────────────

_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(
    name: str,
    failure_threshold: int = 3,
    recovery_timeout: float = 60.0,
) -> CircuitBreaker:
    """Get or create a circuit breaker for a named service."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
    return _breakers[name]


def all_breaker_stats() -> list[dict]:
    """Return stats for all registered circuit breakers."""
    return [b.stats() for b in _breakers.values()]


async def call_with_breaker(
    breaker: CircuitBreaker,
    fn: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Execute a function with circuit breaker protection.

    If the circuit is open, raises CircuitOpenError immediately.
    On success, records success. On exception, records failure and re-raises.
    """
    if not breaker.is_available:
        breaker.record_rejection()
        raise CircuitOpenError(
            f"Circuit breaker [{breaker.name}] is OPEN — "
            f"last failure {time.time() - breaker._last_failure_time:.0f}s ago"
        )
    try:
        result = fn(*args, **kwargs)
        breaker.record_success()
        return result
    except Exception as exc:
        breaker.record_failure(exc)
        raise


class CircuitOpenError(Exception):
    """Raised when a circuit breaker is open and the call is rejected."""

    pass
