"""LLM pick among a party-span shortlist. Not a search of the firm.

Containment and ILIKE stay first. This runs only when those return nothing
and the question names two or more parties. The model may choose one id from
the shortlist or none. It cannot invent a matter id.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.70
MAX_SHORTLIST = 8
MIN_SPANS = 2

_STOP = frozenset({
    "papers", "paper", "case", "filed", "record", "records", "documents",
    "document", "which", "what", "where", "matter", "matters", "against",
    "brought", "supports", "support", "argument", "position", "series",
    "the", "find", "docs", "doc", "our", "we", "has", "have", "firm",
    "worked", "over", "about", "concerning", "concessions", "files",
})

_SPAN_RE = re.compile(r"\b[A-ZÀ-Ý][\w'’.-]*(?:\s+[A-ZÀ-Ý][\w'’.-]*)*")


def llm_resolve_enabled() -> bool:
    return os.environ.get("MATTER_LLM_RESOLVE", "off").strip().lower() == "on"


def party_spans(text: str, *, limit: int = 4) -> list[str]:
    """Capitalised party phrases. Lowercase prose and boilerplate are ignored."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _SPAN_RE.findall(text or ""):
        span = re.sub(r"\s+", " ", match).strip(" .,-")
        if len(span) < 4 or span.lower() in _STOP:
            continue
        key = span.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(span)
        if len(found) >= limit:
            break
    return found


def build_disambiguation_prompt(query: str, candidates: list[dict[str, Any]]) -> str:
    lines = []
    for row in candidates:
        facts = " ".join(str(row.get("facts_text") or "").split())[:180]
        lines.append(
            f"- {row.get('matter_id')}: {row.get('title') or ''} "
            f"(client: {row.get('client_name') or 'unknown'}; "
            f"opposing: {row.get('opposing_party') or 'unknown'}"
            + (f"; facts: {facts}" if facts else "")
            + ")"
        )
    listing = "\n".join(lines)
    return (
        "A lawyer asked a question that does not quote a matter title. "
        "Choose the one matter from the list that the question is about, "
        "or none if the list does not identify a single matter.\n"
        "Return JSON only: {\"matter_id\": \"MTR-...\" or null, \"confidence\": 0.0}\n"
        "matter_id must be copied from the list. Do not invent an id.\n\n"
        f"Question: {query}\n\nMatters:\n{listing}"
    )


def parse_llm_choice(
    raw: str,
    allowed_ids: set[str],
    *,
    min_confidence: float = MIN_CONFIDENCE,
) -> str | None:
    """Return one allowed matter id, or None. Unknown ids are rejected."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    matter_id = payload.get("matter_id")
    if not matter_id or not isinstance(matter_id, str):
        return None
    matter_id = matter_id.strip().upper()
    if matter_id not in {item.upper() for item in allowed_ids}:
        return None
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return None
    if confidence < min_confidence:
        return None
    return matter_id


async def disambiguate_matters(
    query: str,
    candidates: list[dict[str, Any]],
) -> tuple[str | None, str]:
    """Ask the configured chat model to pick one shortlisted matter.

    Returns (matter_id or None, status). Network errors abstain.
    """
    from app.config import settings

    allowed = {str(row.get("matter_id") or "") for row in candidates if row.get("matter_id")}
    if not settings.groq_api_key or not allowed:
        return None, "unavailable"
    prompt = build_disambiguation_prompt(query, candidates)
    model = settings.groq_model or os.environ.get("GROQ_MODEL") or "llama-3.3-70b-versatile"
    body = {
        "model": model,
        "temperature": 0,
        "max_tokens": 800,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                json=body,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
        detail = ""
        if isinstance(exc, httpx.HTTPStatusError):
            detail = exc.response.text[:300]
        logger.warning("matter disambiguation failed: %s %s", exc, detail)
        return None, "error"
    chosen = parse_llm_choice(content, allowed)
    if chosen is None:
        return None, "abstain"
    return chosen, "picked"
