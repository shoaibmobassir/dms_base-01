from __future__ import annotations

import json
import re

from config import settings

SYSTEM_PROMPT = """You are a legal document assistant. Answer ONLY from the provided excerpts below.

Rules:
- Cite every claim as [filename, p.N] where N is the page number.
- If the excerpts do not contain enough information to answer, set "abstain" to true and leave "answer" empty.
- Never invent facts not found in the excerpts.
- Be precise and concise.

Respond with VALID JSON only — no markdown fences:
{
  "abstain": false,
  "answer": "your answer with inline citations like [Affidavit - CA 10046 of 2025.pdf, p.3]",
  "citations": [
    {"file": "exact filename from excerpt header", "page": 3, "snippet": "verbatim short excerpt (<=120 chars)"}
  ]
}"""


def _pack_context(hits: list[dict]) -> str:
    parts = []
    for i, h in enumerate(hits, start=1):
        parts.append(f"[{i}] {h['filename']} | page {h['page_number']}\n{h['text'][:600]}")
    return "\n\n---\n\n".join(parts)


def _parse_raw(raw: str) -> dict | None:
    """Strip markdown fences and parse JSON. Returns None on parse failure."""
    raw = re.sub(r"^```(?:json)?\s*", "", (raw or "").strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return {
            "abstain": bool(data.get("abstain", False)),
            "answer": str(data.get("answer") or ""),
            "citations": data.get("citations") or [],
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _extractive_answer(hits: list[dict]) -> dict:
    snippets = [
        f"[{h['filename']}, p.{h['page_number']}] {h['text'][:300]}"
        for h in hits[:3]
    ]
    return {
        "abstain": False,
        "answer": "Based on the documents:\n\n" + "\n\n".join(snippets),
        "citations": [
            {"file": h["filename"], "page": h["page_number"], "snippet": h["text"][:120]}
            for h in hits[:3]
        ],
    }


# ── provider implementations ─────────────────────────────────────────────────

def _groq(query: str, context: str) -> str:
    from groq import Groq
    client = Groq(api_key=settings.groq_api_key)
    r = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Question: {query}\n\nExcerpts:\n{context}"},
        ],
        max_tokens=4096,
        temperature=0.1,
        response_format={"type": "json_object"},
        timeout=30,
    )
    msg = r.choices[0].message
    return msg.content or getattr(msg, "reasoning_content", None) or ""


def _nvidia(query: str, context: str) -> str:
    from openai import OpenAI
    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=settings.nvidia_api_key,
    )
    r = client.chat.completions.create(
        model=settings.nvidia_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Question: {query}\n\nExcerpts:\n{context}"},
        ],
        max_tokens=8192,
        temperature=0.1,
        response_format={"type": "json_object"},
        stream=False,
        timeout=60,
    )
    msg = r.choices[0].message
    return msg.content or getattr(msg, "reasoning_content", None) or ""


def _gemini(query: str, context: str) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Question: {query}\n\nExcerpts:\n{context}"
    )
    r = client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=4096,
            temperature=0.1,
        ),
    )
    return r.text or ""


# ordered fallback chain: Groq → NVIDIA → Gemini → extractive
_PROVIDERS = [
    ("groq",   lambda k: bool(k), lambda q, c: _groq(q, c),   lambda: settings.groq_api_key),
    ("nvidia", lambda k: bool(k), lambda q, c: _nvidia(q, c), lambda: settings.nvidia_api_key),
    ("gemini", lambda k: bool(k), lambda q, c: _gemini(q, c), lambda: settings.gemini_api_key),
]


def complete(query: str, hits: list[dict]) -> dict:
    """Try Groq → NVIDIA → Gemini; fall back to extractive on all failures."""
    if not hits:
        return {**_extractive_answer([]), "provider": "extractive"}

    context = _pack_context(hits)
    errors: list[str] = []

    for name, _, call, get_key in _PROVIDERS:
        if not get_key():
            continue
        try:
            raw = call(query, context)
            result = _parse_raw(raw)
            if result is not None:
                result["provider"] = name
                return result
            errors.append(f"{name}: parse error on {raw[:80]!r}")
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}: {str(exc)[:120]}")

    result = _extractive_answer(hits)
    result["provider"] = "extractive"
    if errors:
        result["llm_errors"] = errors
    return result
