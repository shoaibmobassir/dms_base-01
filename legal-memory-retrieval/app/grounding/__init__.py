"""Claim-level grounding for Ask the Firm and the Assistant.

``verify``  — decides, per displayed sentence, whether its cited text supports it
``compose`` — rewrites the answer from those verdicts (verified spans, removals)

The verifier runs on a different model from the answer generator, so one model's blind
spot is not both written and approved.
"""
from __future__ import annotations

from typing import Any

from app.grounding.compose import Grounded, ground_answer
from app.grounding.verify import Claim, Source, Span, verify_claims

__all__ = ["Claim", "Grounded", "Source", "Span", "ground_answer", "verifier_llm", "verifier_llms", "verify_claims"]


def verifier_llms() -> list:
    """The configured verifiers: the first supplies spans, the rest can only veto."""
    from app.config import settings

    extra = [m.strip() for m in (settings.grounding_consensus_models or "").split(",") if m.strip()]
    return [verifier_llm()] + [verifier_llm(m) for m in extra if m != settings.grounding_verifier_model]


def verifier_llm(model: str | None = None, timeout: float = 90.0):
    """A JSON-mode, temperature-0 call to the configured verifier model."""
    from app.config import settings
    from app.llm.bedrock_client import chat_complete

    chosen = model or settings.grounding_verifier_model

    def call(messages: list[dict[str, Any]]) -> str:
        result = chat_complete(messages, model=chosen, temperature=0.0, max_tokens=6000,
                               json_mode=True, timeout=timeout)
        return str(result.get("content") or "")

    return call
