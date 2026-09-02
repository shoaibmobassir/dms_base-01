"""LLM answer generation with DMS-style structured output.

Reasoning:
  The DMS portal returns structured responses with:
  - Key finding (summary paragraph)
  - Primary document (strongest match with matter_id, tags, document_type)
  - Supporting documents (additional matches)
  - Inline citations

  Original prompt produced a flat answer with [filename, p.N] citations.
  New prompt instructs the LLM to produce a structured JSON response that
  maps 1:1 to the DMS portal format shown in the screenshots.

  Context packing is increased from 600→1200 chars per hit and now includes
  metadata (document_type, matter_id, tags) so the LLM can reference them.
"""
from __future__ import annotations

import json
import re

from config import settings

SYSTEM_PROMPT = """You are a legal DMS (Document Management System) assistant for a law firm. Answer ONLY from the provided document excerpts below.

Rules:
- Cite every claim inline as [filename, p.N] where N is the page number.
- If the excerpts do not contain enough information, set "abstain" to true and leave "answer" empty.
- Never invent facts not found in the excerpts.
- Write in clear, professional prose like a research memo.
- Identify the single most relevant document as the primary_document.
- List additional relevant documents as supporting_documents.
- Produce a "key_finding" — a 1-2 sentence executive summary of the main takeaway.
- Include matter_id, document_type, and tags from the excerpt headers when available.

Respond with VALID JSON only — no markdown fences:
{
  "abstain": false,
  "key_finding": "One-line summary of the key finding across all documents.",
  "answer": "Detailed answer with inline citations like [Affidavit - CA 10046 of 2025.pdf, p.3]",
  "primary_document": {
    "filename": "exact filename from excerpt header",
    "page": 3,
    "matter_id": "if available from excerpt header, else null",
    "document_type": "if available from excerpt header, else null",
    "tags": ["tag1", "tag2"],
    "snippet": "verbatim short excerpt (<=120 chars)"
  },
  "supporting_documents": [
    {
      "filename": "another_file.pdf",
      "page": 1,
      "matter_id": "if available",
      "document_type": "if available",
      "tags": ["tag1"],
      "snippet": "verbatim short excerpt (<=120 chars)"
    }
  ],
  "citations": [
    {"file": "exact filename", "page": 3, "snippet": "verbatim short excerpt (<=120 chars)"}
  ]
}"""


def _pack_context(hits: list[dict]) -> str:
    """Pack retrieval hits into a numbered context string for the LLM.

    Now includes metadata (document_type, matter_id, tags) in each header
    so the LLM can reference them in its structured response.
    """
    parts = []
    for i, h in enumerate(hits, start=1):
        header = f"[{i}] {h['filename']} | page {h['page_number']}"
        # Add metadata if available
        meta_parts = []
        if h.get("document_type"):
            meta_parts.append(f"Type: {h['document_type']}")
        if h.get("matter_id"):
            meta_parts.append(f"Matter: {h['matter_id']}")
        if h.get("tags"):
            tags = h["tags"] if isinstance(h["tags"], list) else []
            if tags:
                meta_parts.append(f"Tags: {', '.join(tags)}")
        if meta_parts:
            header += f" | {' | '.join(meta_parts)}"
        # Increased from 600 to 1200 chars to preserve complete legal arguments
        parts.append(f"{header}\n{h['text'][:1200]}")
    return "\n\n---\n\n".join(parts)


def _parse_raw(raw: str) -> dict | None:
    """Strip markdown fences and parse JSON. Returns None on parse failure."""
    raw = re.sub(r"^```(?:json)?\s*", "", (raw or "").strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
        return {
            "abstain": bool(data.get("abstain", False)),
            "key_finding": str(data.get("key_finding") or ""),
            "answer": str(data.get("answer") or ""),
            "primary_document": data.get("primary_document"),
            "supporting_documents": data.get("supporting_documents") or [],
            "citations": data.get("citations") or [],
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _extractive_answer(hits: list[dict]) -> dict:
    """Fallback answer when all LLM providers fail."""
    snippets = [
        f"[{h['filename']}, p.{h['page_number']}] {h['text'][:400]}"
        for h in hits[:3]
    ]

    # Build primary and supporting documents from hits
    primary = None
    supporting = []
    for i, h in enumerate(hits[:5]):
        doc_entry = {
            "filename": h["filename"],
            "page": h["page_number"],
            "matter_id": h.get("matter_id"),
            "document_type": h.get("document_type"),
            "tags": h.get("tags") if isinstance(h.get("tags"), list) else [],
            "snippet": h["text"][:120],
        }
        if i == 0:
            primary = doc_entry
        else:
            supporting.append(doc_entry)

    return {
        "abstain": False,
        "key_finding": f"Found {len(hits)} relevant excerpts from firm documents.",
        "answer": "Based on the documents:\n\n" + "\n\n".join(snippets),
        "primary_document": primary,
        "supporting_documents": supporting,
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
