from __future__ import annotations

import json
from typing import Any

import httpx

from app.answers.citations import extract_document_ids, filter_citations

SYSTEM = (
    "You are Ask the Firm — the institutional memory assistant for Apex Chambers law firm. "
    "Your role is that of a senior research assistant who synthesises the firm's prior work.\n\n"
    "Rules:\n"
    "1. Answer ONLY from the provided excerpts — never invent facts.\n"
    "2. Write in clear prose, like a research memo. Use paragraphs, not bullet dumps.\n"
    "3. Cite every factual claim inline as (DOC-XXXXX). Multiple citations per sentence are fine.\n"
    "4. Include a ## Sources section at the end listing each cited doc ID and its title.\n"
    "5. If excerpts are insufficient, set abstain=true and leave answer empty.\n"
    "6. Never invent document IDs — only cite IDs that appear in the excerpts.\n\n"
    "Respond with JSON only, no markdown fences:\n"
    '{"abstain": bool, "answer": str, "citations": [str]}\n\n'
    "The answer field should be rich prose with inline citations. "
    "The citations array must list every DOC-ID you cited."
)


def _pack_context(hits: list[dict], max_docs: int = 12) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        doc_id = str(hit.get("document_id") or "").upper()
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        title = hit.get("title") or ""
        text = " ".join(str(hit.get("text") or "").split())[:600]
        lines.append(f"{doc_id} | {title}\n{text}")
        if len(lines) >= max_docs:
            break
    return "\n\n".join(lines)


def parse_model_json(raw: str, hits: list[dict]) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError:
        cited = filter_citations(extract_document_ids(text), hits)
        if not cited:
            return {
                "answer": "",
                "citations": [],
                "abstained": True,
                "reason": "unparseable_or_uncited",
            }
        return {
            "answer": text,
            "citations": cited,
            "abstained": False,
            "reason": None,
        }
    abstain = bool(payload.get("abstain"))
    answer = str(payload.get("answer") or "").strip()
    cited_raw = payload.get("citations") or extract_document_ids(answer)
    if isinstance(cited_raw, str):
        cited_raw = extract_document_ids(cited_raw)
    cited = filter_citations([str(c) for c in cited_raw], hits)
    cited.extend(cid for cid in extract_document_ids(answer) if cid not in cited)
    cited = filter_citations(cited, hits)
    if abstain or not answer:
        return {
            "answer": "",
            "citations": [],
            "abstained": True,
            "reason": "insufficient_evidence",
        }
    # If model answered but gave no citations, extract them from the answer text
    if not cited:
        cited = filter_citations(extract_document_ids(answer), hits)
    return {
        "answer": answer,
        "citations": cited,
        "abstained": False,
        "reason": None,
    }


def groq_complete(api_key: str, model: str, query: str, hits: list[dict]) -> str:
    context = _pack_context(hits)
    body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": f"Question: {query}\n\nExcerpts:\n{context}",
            },
        ],
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
        response.raise_for_status()
        data = response.json()
    return data["choices"][0]["message"]["content"]


def gemini_complete(api_key: str, model: str, query: str, hits: list[dict]) -> str:
    context = _pack_context(hits)
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [
            {
                "parts": [
                    {"text": f"Question: {query}\n\nExcerpts:\n{context}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(url, params={"key": api_key}, json=body)
        response.raise_for_status()
        data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]
