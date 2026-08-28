from __future__ import annotations

from app.answers.citations import filter_citations


def extractive_answer(query: str, hits: list[dict], max_docs: int = 3) -> dict:
    snippets: list[str] = []
    cited: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        doc_id = str(hit.get("document_id") or "").upper()
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        cited.append(doc_id)
        title = hit.get("title") or doc_id
        text = " ".join(str(hit.get("text") or "").split())[:400]
        snippets.append(f"[{doc_id}] {title}: {text}")
        if len(cited) >= max_docs:
            break
    cited = filter_citations(cited, hits)
    if not cited:
        return {
            "answer": "",
            "citations": [],
            "abstained": True,
            "reason": "no_evidence",
            "provider": "extractive",
        }
    body = (
        f"Retrieved firm records for: {query.strip()}\n\n" + "\n\n".join(snippets)
    )
    return {
        "answer": body,
        "citations": cited,
        "abstained": False,
        "reason": None,
        "provider": "extractive",
    }
