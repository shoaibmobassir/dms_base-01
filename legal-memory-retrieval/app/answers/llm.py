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
    "6. Never invent document IDs — only cite IDs that appear in the excerpts.\n"
    "7. Produce a key_finding — a 1-2 sentence executive summary of the main answer.\n"
    "8. Include matter_id, document_type from excerpt headers in your citations where available.\n\n"
    "Respond with JSON only, no markdown fences:\n"
    '{"abstain": bool, "key_finding": str, "answer": str, "citations": [str]}\n\n'
    "The key_finding is the executive summary. "
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
        # Include matter metadata in excerpt header for structured citations
        header = f"{doc_id} | {title}"
        meta_parts = []
        if hit.get("matter_id"):
            meta_parts.append(f"Matter: {hit['matter_id']}")
        if hit.get("document_type"):
            meta_parts.append(f"Type: {hit['document_type']}")
        if hit.get("matter_code"):
            meta_parts.append(f"Code: {hit['matter_code']}")
        if hit.get("client_name"):
            meta_parts.append(f"Client: {hit['client_name']}")
        if hit.get("court"):
            meta_parts.append(f"Forum: {hit['court']}")
        if meta_parts:
            header += f" | {' | '.join(meta_parts)}"
        # Increased from 600 to 1200 chars to preserve complete legal arguments
        text = " ".join(str(hit.get("text") or "").split())[:1200]
        lines.append(f"{header}\n{text}")
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
            "key_finding": "",
        }
    if not cited:
        cited = filter_citations(extract_document_ids(answer), hits)
    if not cited:
        return {
            "answer": "",
            "citations": [],
            "abstained": True,
            "reason": "uncited_or_invalid_citations",
            "key_finding": "",
        }
    key_finding = str(payload.get("key_finding") or "").strip()
    if not key_finding:
        key_finding = answer.split("\n\n")[0][:300]
    return {
        "answer": answer,
        "citations": cited,
        "abstained": False,
        "reason": None,
        "key_finding": key_finding,
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
