from app.retrieval.highlight import highlight_snippet


def hit_payload(hit: dict) -> dict:
    return {
        "document_id": hit["document_id"],
        "matter_id": hit["matter_id"],
        "matter_code": hit.get("matter_code", ""),
        "title": hit["title"],
        "document_type": hit["document_type"],
        "author_name": hit.get("author_name", ""),
        "doc_date": str(hit["doc_date"]) if hit.get("doc_date") else None,
        "chunk_id": hit.get("chunk_id"),
        "chunk_index": hit.get("chunk_index"),
        "score": hit.get("rerank_score", hit.get("fused_score")),
        "ce_score": hit.get("ce_score"),
        "channel": hit.get("channel"),
        "snippet": (hit.get("text") or "")[:400],
    }


def hit_payload_highlighted(hit: dict, query: str, max_chars: int = 350) -> dict:
    text = hit.get("text") or ""
    payload = hit_payload(hit)
    payload["highlighted_snippet"] = highlight_snippet(text, query, max_chars=max_chars)
    payload["score"] = round(float(payload.get("score") or 0.0), 4)
    return payload
