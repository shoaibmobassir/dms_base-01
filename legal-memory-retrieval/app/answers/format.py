"""Format retrieval hits into DMS portal-style structured response.

Reasoning:
  The DMS portal returns responses with:
  - Tags from schema (Client, Forum, Matter ID, Matter Code, Document Type)
  - Structured citations with document_id + matter_id + tags
  - sources[] — top hits with highlighted_snippet
  - matchedMatters[] — deduplicated by matter_id, ranked by max score
  - key_finding — LLM field or first-paragraph fallback

  This module transforms raw hits + LLM answer into the envelope format.
"""
from __future__ import annotations

from app.api.hits import hit_payload_highlighted


def _build_tags(hit: dict) -> list[dict]:
    """Build DMS-style tag list from a hit's metadata."""
    tags: list[dict] = []
    if hit.get("matter_id"):
        tags.append({"key": "Matter ID", "value": hit["matter_id"]})
    if hit.get("matter_code"):
        tags.append({"key": "Matter Code", "value": hit["matter_code"]})
    if hit.get("document_type"):
        tags.append({"key": "Document Type", "value": hit["document_type"]})
    if hit.get("client_name"):
        tags.append({"key": "Client", "value": hit["client_name"]})
    if hit.get("court"):
        tags.append({"key": "Forum", "value": hit["court"]})
    if hit.get("practice_area"):
        tags.append({"key": "Practice Area", "value": hit["practice_area"]})
    return tags


def _structured_citation(hit: dict) -> dict:
    """Build a structured citation from a retrieval hit."""
    return {
        "document_id": hit.get("document_id", ""),
        "matter_id": hit.get("matter_id", ""),
        "matter_code": hit.get("matter_code", ""),
        "title": hit.get("title", ""),
        "document_type": hit.get("document_type", ""),
        "tags": _build_tags(hit),
    }


def _build_sources(hits: list[dict], query: str, max_sources: int = 5) -> list[dict]:
    """Build sources[] — top hits with highlighted snippets."""
    sources: list[dict] = []
    seen_docs: set[str] = set()
    for hit in hits[:max_sources * 2]:  # look at more hits to find unique docs
        doc_id = hit.get("document_id", "")
        if doc_id in seen_docs:
            continue
        seen_docs.add(doc_id)
        payload = hit_payload_highlighted(hit, query, max_chars=380)
        payload["tags"] = _build_tags(hit)
        sources.append(payload)
        if len(sources) >= max_sources:
            break
    return sources


def _build_matched_matters(hits: list[dict]) -> list[dict]:
    """Deduplicate by matter_id, ranked by max score."""
    matter_map: dict[str, dict] = {}
    for hit in hits:
        mid = hit.get("matter_id", "")
        if not mid:
            continue
        score = float(hit.get("rerank_score", hit.get("fused_score", 0.0)) or 0.0)
        if mid not in matter_map or score > matter_map[mid]["max_score"]:
            matter_map[mid] = {
                "matter_id": mid,
                "matter_code": hit.get("matter_code", ""),
                "title": hit.get("matter_title") or hit.get("title", ""),
                "client_name": hit.get("client_name", ""),
                "court": hit.get("court", ""),
                "practice_area": hit.get("practice_area", ""),
                "max_score": score,
                "document_count": 0,
            }
        matter_map[mid]["document_count"] += 1

    return sorted(
        [
            {
                **{k: v for k, v in m.items() if k != "max_score"},
                "similarity": min(99, max(1, int(round(m["max_score"] * 100)))),
            }
            for m in matter_map.values()
        ],
        key=lambda m: m.get("similarity", 0),
        reverse=True,
    )


def format_dms_response(
    query: str,
    answer_result: dict,
    hits: list[dict],
    retrieval_latency: dict,
) -> dict:
    """Transform raw answer + hits into the full DMS-style response envelope."""
    # Enrich hits with matter metadata from DB if available
    enriched_hits = _enrich_hits_with_matter_data(hits)

    # Build structured parts
    sources = _build_sources(enriched_hits, query)
    matched_matters = _build_matched_matters(enriched_hits)
    structured_citations = [_structured_citation(h) for h in enriched_hits[:8]]

    # Key finding: LLM provides it, or first paragraph of answer
    key_finding = answer_result.get("key_finding", "")
    if not key_finding and answer_result.get("answer"):
        # Take first sentence/paragraph as key finding
        answer_text = answer_result["answer"]
        first_para = answer_text.split("\n\n")[0]
        key_finding = first_para[:300]

    return {
        "key_finding": key_finding,
        "structured_citations": structured_citations,
        "sources": sources,
        "matchedMatters": matched_matters,
        "tags": _build_tags(enriched_hits[0]) if enriched_hits else [],
    }


def _enrich_hits_with_matter_data(hits: list[dict]) -> list[dict]:
    """Add matter-level fields (client_name, court, practice_area) to hits.

    These come from a JOIN with matters table at query time. If already
    present on the hit, no-op. Otherwise fetch from DB.
    """
    if not hits:
        return hits

    # Check if hits already have matter data
    first = hits[0]
    if first.get("client_name") or first.get("court"):
        return hits  # already enriched

    # Fetch matter data for all unique matter_ids
    matter_ids = list({h.get("matter_id", "") for h in hits if h.get("matter_id")})
    if not matter_ids:
        return hits

    try:
        from app.db.connection import connect
        with connect() as conn:
            placeholders = ",".join(["%s"] * len(matter_ids))
            rows = conn.execute(
                f"""
                SELECT m.matter_id, m.matter_code, m.client_name, m.court,
                       m.practice_area, m.title as matter_title
                FROM matters m
                WHERE m.matter_id IN ({placeholders})
                """,
                matter_ids,
            ).fetchall()
            matter_map = {r["matter_id"]: r for r in rows}
    except Exception:
        return hits  # fail gracefully

    enriched = []
    for hit in hits:
        h = dict(hit)
        mid = h.get("matter_id", "")
        if mid in matter_map:
            m = matter_map[mid]
            h.setdefault("matter_code", m.get("matter_code"))
            h.setdefault("client_name", m.get("client_name"))
            h.setdefault("court", m.get("court"))
            h.setdefault("practice_area", m.get("practice_area"))
            h.setdefault("matter_title", m.get("matter_title"))
        enriched.append(h)
    return enriched
