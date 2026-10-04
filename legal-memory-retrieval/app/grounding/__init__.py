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
    """A JSON-mode, temperature-0 call to the configured verifier model.

    Uses Bedrock when the model id looks like a Mantle id (``vendor.model``) and
    Bedrock is configured; otherwise Azure / the chat gateway. Keep this on a
    different backend or deployment from the answer writer.
    """
    from app.config import settings
    from app.llm.azure_openai_client import azure_configured, chat_complete as azure_chat
    from app.llm.bedrock_client import bedrock_configured, chat_complete as bedrock_chat

    chosen = model or settings.grounding_verifier_model
    use_bedrock = (
        bedrock_configured()
        and "." in chosen
        and not chosen.lower().startswith("deepseek")
    )

    def call(messages: list[dict[str, Any]]) -> str:
        if use_bedrock:
            result = bedrock_chat(
                messages, model=chosen, temperature=0.0, max_tokens=6000,
                json_mode=True, timeout=timeout,
            )
        elif azure_configured():
            result = azure_chat(
                messages, model=chosen, temperature=0.0, max_tokens=6000,
                json_mode=True, timeout=timeout,
            )
        else:
            result = bedrock_chat(
                messages, model=chosen, temperature=0.0, max_tokens=6000,
                json_mode=True, timeout=timeout,
            )
        return str(result.get("content") or "")

    return call
