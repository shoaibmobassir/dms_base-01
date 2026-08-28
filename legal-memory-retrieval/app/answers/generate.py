from __future__ import annotations

from typing import Literal, Never

import httpx

from app.answers.extractive import extractive_answer
from app.answers.llm import gemini_complete, groq_complete, parse_model_json
from app.config import settings
from app.query.understand import understand
from app.retrieval.engine import retrieve
from app.sprint import CURRENT_SPRINT, FEATURES

Provider = Literal["extractive", "groq", "gemini"]


def _provider() -> Provider:
    name = (settings.answer_provider or "auto").strip().lower()
    if name == "extractive":
        return "extractive"
    if name == "groq":
        return "groq"
    if name == "gemini":
        return "gemini"
    if settings.groq_api_key:
        return "groq"
    if settings.gemini_api_key:
        return "gemini"
    return "extractive"


def answer_question(
    conn,
    query: str,
    member_id: str | None = None,
    k: int | None = None,
    provider: Provider | None = None,
) -> dict:
    import time

    parsed = understand(query)
    hits: list[dict] = []
    retrieval_latency: dict = {}
    if parsed.intent != "empty" and parsed.raw:
        hits, retrieval_latency = retrieve(conn, query, member_id, k=k)

    blocked = _blocked_matter_or_doc(parsed, hits)
    if not hits or blocked:
        if blocked:
            hits = []
        result = {
            "answer": "",
            "citations": [],
            "abstained": True,
            "reason": "no_evidence" if not hits else "access_or_miss",
            "provider": "none",
            "latency_ms": retrieval_latency,
        }
    else:
        chosen: Provider = provider or _provider()
        t0 = time.perf_counter()
        result = _generate(chosen, query, hits)
        result["latency_ms"] = {
            **retrieval_latency,
            "llm": round((time.perf_counter() - t0) * 1000, 1),
        }

    return {
        "query": query,
        "sprint": CURRENT_SPRINT,
        "llm": FEATURES["llm"],
        "understanding": parsed.to_dict(),
        "member_id": member_id,
        "hits": hits,
        **result,
    }


def _blocked_matter_or_doc(parsed, hits: list[dict]) -> bool:
    if parsed.intent in {
        "graph_reasoning",
        "similar_matter",
        "experience_search",
        "cross_document",
    }:
        return False
    if parsed.matter_ids:
        seen = {str(h.get("matter_id") or "") for h in hits}
        if not any(mid in seen for mid in parsed.matter_ids):
            return True
    if parsed.document_ids:
        seen_docs = {str(h.get("document_id") or "").upper() for h in hits}
        wanted = {d.upper() for d in parsed.document_ids}
        if not (wanted & seen_docs):
            return True
    return False


def _generate(provider: Provider, query: str, hits: list[dict]) -> dict:
    if provider == "extractive":
        return extractive_answer(query, hits)
    if provider == "groq":
        if not settings.groq_api_key:
            return extractive_answer(query, hits)
        try:
            raw = groq_complete(
                settings.groq_api_key, settings.groq_model, query, hits
            )
        except httpx.HTTPError:
            fallback = extractive_answer(query, hits)
            fallback["provider"] = "extractive_after_groq_error"
            return fallback
        parsed = parse_model_json(raw, hits)
        parsed["provider"] = "groq"
        return parsed
    if provider == "gemini":
        if not settings.gemini_api_key:
            return extractive_answer(query, hits)
        try:
            raw = gemini_complete(
                settings.gemini_api_key, settings.gemini_model, query, hits
            )
        except httpx.HTTPError:
            fallback = extractive_answer(query, hits)
            fallback["provider"] = "extractive_after_gemini_error"
            return fallback
        parsed = parse_model_json(raw, hits)
        parsed["provider"] = "gemini"
        return parsed
    exhausted: Never = provider
    raise RuntimeError(f"unknown provider: {exhausted}")
