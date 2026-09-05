"""P5.6-C7 — Evidence candidate generation + retrieval (theme + soft role).

Primary unit: chunk/passage scored against a Proposition.
Aggregation to documents is secondary (diagnostic).

Channels:
  lexical OR-BM25 (curated terms)
  phrase (AND within multi-word terms)
  proximity (adjacent / near terms)
  RRF fusion across lexical channels
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from psycopg.rows import dict_row

from app.retrieval.doc_profile import infer_role_family
from app.retrieval.matter_resolver import to_or_tsquery
from app.retrieval.proposition import EvidenceSpan, Proposition
from app.retrieval.theme_scoped import rrf_merge_doc_lists

_STOP = frozenset({
    "a", "an", "the", "and", "or", "of", "on", "in", "for", "to", "with",
    "we", "have", "had", "has", "is", "are", "was", "were", "by", "from",
})

# Soft demotion only — never hard-exclude ANALYSIS (memos).
_ANALYSIS_FAMILIES = frozenset({"ANALYSIS"})


def evidence_id_for(chunk_id: str, proposition_id: str) -> str:
    raw = f"{chunk_id}:{proposition_id}"
    return "EV-" + hashlib.sha1(raw.encode()).hexdigest()[:16]


def soft_role_boost(
    role_family: str | None,
    preferred: set[str],
    *,
    preferred_mult: float = 2.5,
    analysis_mult: float = 0.7,
) -> float:
    """Return multiplicative score factor (soft prior; never excludes)."""
    if not role_family:
        return 1.0
    if preferred and role_family in preferred:
        return preferred_mult
    if preferred and role_family in _ANALYSIS_FAMILIES:
        return analysis_mult
    return 1.0


def phrase_tsquery(terms: list[str], *, max_phrases: int = 8) -> str | None:
    """AND within multi-word terms; OR across phrases."""
    parts: list[str] = []
    for term in terms[:max_phrases]:
        words = [
            w for w in re.findall(r"[A-Za-z0-9]+", (term or "").lower())
            if w not in _STOP and len(w) > 1
        ]
        if len(words) >= 2:
            parts.append("(" + " & ".join(words[:5]) + ")")
        elif len(words) == 1 and len(words[0]) > 3:
            parts.append(words[0])
    if not parts:
        return None
    return " | ".join(dict.fromkeys(parts))


def proximity_tsquery(terms: list[str], *, distance: int = 3, max_pairs: int = 8) -> str | None:
    """Near-term pairs within multi-word phrases (not across unrelated terms)."""
    parts: list[str] = []
    for term in terms:
        words = [
            w for w in re.findall(r"[A-Za-z0-9]+", (term or "").lower())
            if w not in _STOP and len(w) > 2
        ]
        if len(words) < 2:
            continue
        for i in range(len(words) - 1):
            parts.append(f"({words[i]} <{distance}> {words[i + 1]})")
            if len(parts) >= max_pairs:
                break
        if len(parts) >= max_pairs:
            break
    return " | ".join(dict.fromkeys(parts)) if parts else None


def _prop_terms(prop: Proposition) -> list[str]:
    terms = list(dict.fromkeys(prop.lexical_terms or []))
    if not terms:
        terms = [w for w in prop.claim.split() if len(w) > 3][:8]
    return terms


def _rows_to_spans(
    rows: list[dict[str, Any]],
    prop: Proposition,
    *,
    channel: str,
) -> list[EvidenceSpan]:
    out: list[EvidenceSpan] = []
    for r in rows:
        fam = infer_role_family(r.get("document_type"), title=r.get("title"))
        out.append(EvidenceSpan(
            evidence_id=evidence_id_for(r["chunk_id"], prop.id),
            document_id=r["document_id"],
            chunk_id=r["chunk_id"],
            matter_id=r.get("matter_id"),
            proposition_id=prop.id,
            relationship="SUPPORTS",
            quoted_text=(r.get("text") or "")[:1500],
            score=float(r.get("score") or 0),
            channel=channel,
            document_type=r.get("document_type"),
            title=r.get("title"),
            role_family=fam,
        ))
    return out


async def _fts_evidence(
    conn,
    prop: Proposition,
    matter_ids: list[str],
    tsquery: str,
    *,
    member_id: str | None,
    limit: int,
    channel: str,
) -> list[EvidenceSpan]:
    if not tsquery or not matter_ids:
        return []
    sql = """
        SELECT c.chunk_id, c.document_id, c.matter_id, c.chunk_index, c.text,
               d.title, d.document_type,
               ts_rank_cd(c.tsv, to_tsquery('english', %(tsquery)s)) AS score
        FROM chunks c
        JOIN documents d ON d.document_id = c.document_id
        JOIN permissions p ON p.matter_id = c.matter_id
        WHERE c.matter_id = ANY(%(matter_ids)s)
          AND c.tsv @@ to_tsquery('english', %(tsquery)s)
          AND (
            (%(member_id)s::text IS NULL)
            OR p.restricted = FALSE
            OR %(member_id)s::text = ANY (p.allowed_members)
          )
        ORDER BY score DESC
        LIMIT %(limit)s
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql,
            {
                "tsquery": tsquery,
                "matter_ids": matter_ids,
                "member_id": member_id,
                "limit": limit,
            },
        )
        rows = list(await cur.fetchall())
    return _rows_to_spans(rows, prop, channel=channel)


async def lexical_evidence_search(
    conn,
    prop: Proposition,
    matter_ids: list[str],
    *,
    member_id: str | None = None,
    limit: int = 100,
) -> list[EvidenceSpan]:
    """BM25/OR over chunks in theme matters for one proposition."""
    terms = _prop_terms(prop)
    tsq = to_or_tsquery(terms, max_terms=16)
    return await _fts_evidence(
        conn, prop, matter_ids, tsq or "",
        member_id=member_id, limit=limit, channel="lexical",
    )


async def phrase_evidence_search(
    conn,
    prop: Proposition,
    matter_ids: list[str],
    *,
    member_id: str | None = None,
    limit: int = 100,
) -> list[EvidenceSpan]:
    """Phrase/AND-within-term evidence channel."""
    tsq = phrase_tsquery(_prop_terms(prop))
    return await _fts_evidence(
        conn, prop, matter_ids, tsq or "",
        member_id=member_id, limit=limit, channel="phrase",
    )


async def proximity_evidence_search(
    conn,
    prop: Proposition,
    matter_ids: list[str],
    *,
    member_id: str | None = None,
    limit: int = 100,
    distance: int = 3,
) -> list[EvidenceSpan]:
    """Proximity evidence channel (term1 <N> term2)."""
    tsq = proximity_tsquery(_prop_terms(prop), distance=distance)
    return await _fts_evidence(
        conn, prop, matter_ids, tsq or "",
        member_id=member_id, limit=limit, channel="proximity",
    )


async def hybrid_lexical_evidence(
    conn,
    prop: Proposition,
    matter_ids: list[str],
    *,
    member_id: str | None = None,
    limit: int = 100,
) -> list[EvidenceSpan]:
    """RRF of OR + phrase + proximity lexical channels."""
    lex = await lexical_evidence_search(
        conn, prop, matter_ids, member_id=member_id, limit=limit,
    )
    phrase = await phrase_evidence_search(
        conn, prop, matter_ids, member_id=member_id, limit=limit,
    )
    prox = await proximity_evidence_search(
        conn, prop, matter_ids, member_id=member_id, limit=limit,
    )
    return rrf_evidence([lex, phrase, prox], k=limit)


async def vector_evidence_search(
    conn,
    qvec: list[float],
    prop: Proposition,
    matter_ids: list[str],
    *,
    member_id: str | None = None,
    column: str = "embedding_ctx",
    limit: int = 100,
) -> list[EvidenceSpan]:
    """Vector search over chunks in theme; score against proposition embedding."""
    if column not in {"embedding", "embedding_ctx"} or not matter_ids:
        return []
    sql = f"""
        SELECT c.chunk_id, c.document_id, c.matter_id, c.chunk_index, c.text,
               d.title, d.document_type,
               1.0 - (c.{column} <=> %(qvec)s::vector) AS score
        FROM chunks c
        JOIN documents d ON d.document_id = c.document_id
        JOIN permissions p ON p.matter_id = c.matter_id
        WHERE c.matter_id = ANY(%(matter_ids)s)
          AND c.{column} IS NOT NULL
          AND (
            (%(member_id)s::text IS NULL)
            OR p.restricted = FALSE
            OR %(member_id)s::text = ANY (p.allowed_members)
          )
        ORDER BY c.{column} <=> %(qvec)s::vector
        LIMIT %(limit)s
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            sql,
            {"qvec": qvec, "matter_ids": matter_ids, "member_id": member_id, "limit": limit},
        )
        rows = list(await cur.fetchall())
    return _rows_to_spans(rows, prop, channel=f"vector_{column}")


def apply_soft_role_prior(
    spans: list[EvidenceSpan],
    preferred_families: set[str],
    *,
    preferred_mult: float = 2.5,
    analysis_mult: float = 0.7,
) -> list[EvidenceSpan]:
    """Re-rank with multiplicative soft role prior; does not drop candidates."""
    rescored: list[EvidenceSpan] = []
    for s in spans:
        factor = soft_role_boost(
            s.role_family,
            preferred_families,
            preferred_mult=preferred_mult,
            analysis_mult=analysis_mult,
        )
        rescored.append(EvidenceSpan(**{**s.to_dict(), "score": s.score * factor}))
    rescored.sort(key=lambda x: x.score, reverse=True)
    return rescored


def rrf_evidence(
    lists: list[list[EvidenceSpan]],
    *,
    k: int = 100,
    rrf_k: int = 60,
) -> list[EvidenceSpan]:
    """RRF over evidence spans keyed by chunk_id (+ proposition)."""
    adapted = []
    for ranked in lists:
        if not ranked:
            continue
        adapted.append([
            {
                "document_id": s.chunk_id,  # reuse doc RRF helper keying
                "matter_id": s.matter_id,
                "score": s.score,
                "_span": s,
            }
            for s in ranked
        ])
    if not adapted:
        return []
    merged = rrf_merge_doc_lists(adapted, k=k, rrf_k=rrf_k)
    out: list[EvidenceSpan] = []
    for row in merged:
        span: EvidenceSpan = row["_span"]
        out.append(EvidenceSpan(**{**span.to_dict(), "score": float(row.get("score") or 0), "channel": "rrf"}))
    return out


def aggregate_evidence_to_documents(
    spans: list[EvidenceSpan],
    *,
    method: str = "max",
) -> list[dict[str, Any]]:
    """Secondary diagnostic: document score from evidence (max / top3 mean)."""
    by_doc: dict[str, list[EvidenceSpan]] = {}
    for s in spans:
        by_doc.setdefault(s.document_id, []).append(s)
    out = []
    for doc_id, items in by_doc.items():
        items = sorted(items, key=lambda x: x.score, reverse=True)
        if method == "top3_mean":
            top = items[:3]
            score = sum(x.score for x in top) / len(top)
        else:
            score = items[0].score
        best = items[0]
        out.append({
            "document_id": doc_id,
            "score": score,
            "best_chunk_id": best.chunk_id,
            "best_evidence_id": best.evidence_id,
            "n_evidence": len(items),
            "document_type": best.document_type,
            "title": best.title,
            "role_family": best.role_family,
        })
    out.sort(key=lambda r: r["score"], reverse=True)
    return out


def best_evidence_span_offsets(
    text: str,
    terms: list[str],
    *,
    window: int = 280,
) -> tuple[int, int, str]:
    """Pick a window around densest term hits (refined gold span)."""
    low = (text or "").lower()
    if not low:
        return 0, 0, ""
    hits: list[int] = []
    for t in terms:
        tlow = (t or "").lower().strip()
        if len(tlow) < 3:
            continue
        start = 0
        while True:
            idx = low.find(tlow, start)
            if idx < 0:
                break
            hits.append(idx)
            start = idx + len(tlow)
    if not hits:
        end = min(len(text), window)
        return 0, end, text[:end]
    # densest window: center on median hit
    hits.sort()
    mid = hits[len(hits) // 2]
    start = max(0, mid - window // 2)
    end = min(len(text), start + window)
    return start, end, text[start:end]


def term_density(text: str, terms: list[str]) -> float:
    low = (text or "").lower()
    if not low or not terms:
        return 0.0
    hits = sum(1 for t in terms if t and len(t) > 2 and t.lower() in low)
    return hits / max(len(terms), 1)
