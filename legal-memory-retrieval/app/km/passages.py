"""Passage evidence for Ask the Firm.

Inside a resolved scope the candidate universe is small (one matter is at
most a few thousand chunks), so we can afford to rank it properly: BM25 and
an exact (non-ANN) vector scan restricted to the scoped matters, merged, with
heading-only chunks dropped and parent/child duplicates collapsed, then a
cross-encoder over the survivors. The top passages are kept with a per-document
cap so one long agreement cannot crowd out the board resolution.
"""
from __future__ import annotations

import re
from typing import Any

from app.km.scope import ACL_SQL, _fetch
from app.retrieval.matter_resolver import chunk_or_tsquery

MIN_PASSAGE_CHARS = 60

_SELECT = """
    c.chunk_id, c.chunk_index, c.document_id, c.matter_id, c.text, c.page_number,
    c.section_title, c.parent_chunk_id, c.is_parent,
    d.title, d.document_type, d.doc_date, d.author_name, d.matter_code,
    cl.name AS client_name, m.title AS matter_title, m.court, m.practice_area
"""
_FROM = """
    FROM chunks c
    JOIN documents d ON d.document_id = c.document_id
    JOIN matters m ON m.matter_id = c.matter_id
    JOIN clients cl ON cl.client_id = m.client_id
    JOIN permissions p ON p.matter_id = c.matter_id
"""


def _is_heading(row: dict) -> bool:
    text = " ".join(str(row.get("text") or "").split())
    if len(text) < MIN_PASSAGE_CHARS:
        return True
    stem = re.sub(r"\.(docx?|pdf|txt)$", "", str(row.get("title") or ""), flags=re.I).strip().lower()
    return bool(stem) and text.lower() == stem


def _collapse(rows: list[dict]) -> list[dict]:
    """Keep one row per passage (a parent and its child carry the same text)."""
    best: dict[str, dict] = {}
    for r in rows:
        key = r.get("parent_chunk_id") or r["chunk_id"]
        cur = best.get(key)
        if cur is None or float(r.get("_lex", 0)) + float(r.get("_vec", 0)) > float(cur.get("_lex", 0)) + float(cur.get("_vec", 0)):
            merged = dict(r)
            if cur is not None:
                merged["_lex"] = max(float(cur.get("_lex", 0)), float(r.get("_lex", 0)))
                merged["_vec"] = max(float(cur.get("_vec", 0)), float(r.get("_vec", 0)))
            best[key] = merged
        else:
            cur["_lex"] = max(float(cur.get("_lex", 0)), float(r.get("_lex", 0)))
            cur["_vec"] = max(float(cur.get("_vec", 0)), float(r.get("_vec", 0)))
    return list(best.values())


def _embed(question: str) -> str | None:
    try:
        from app.retrieval.engine_v2 import _get_embedder

        vec = _get_embedder().encode([question])[0]
        return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
    except Exception:
        return None


def _cross_encode(question: str, rows: list[dict]) -> list[float]:
    try:
        from app.retrieval.reranker import _predict

        pairs = [(question, f"{r.get('title') or ''}\n{(r.get('text') or '')[:1200]}") for r in rows]
        return _predict(pairs)
    except Exception:
        return [float(r.get("_lex", 0)) + float(r.get("_vec", 0)) for r in rows]


def scoped_passages(
    conn,
    question: str,
    matter_ids: list[str],
    member_id: str | None,
    *,
    limit: int = 14,
    per_doc: int = 4,
    overview: bool = False,
) -> list[dict]:
    if not matter_ids:
        return []
    base = {"member_id": member_id, "ids": list(matter_ids)}
    cands: list[dict] = []
    tsq = chunk_or_tsquery(question)
    if tsq:
        cands += [
            {**r, "_lex": float(r["lex"])}
            for r in _fetch(
                conn,
                f"""
                SELECT {_SELECT}, ts_rank_cd(c.tsv, to_tsquery('english', %(tsq)s)) AS lex
                {_FROM}
                WHERE {ACL_SQL} AND c.matter_id = ANY(%(ids)s)
                  AND c.tsv @@ to_tsquery('english', %(tsq)s)
                ORDER BY lex DESC LIMIT 60
                """,
                {**base, "tsq": tsq},
            )
        ]
    vec = _embed(question)
    if vec:
        # "+ 0" keeps the planner off the HNSW index so the scan is exact within scope.
        cands += [
            {**r, "_vec": float(r["sim"])}
            for r in _fetch(
                conn,
                f"""
                SELECT {_SELECT}, 1 - (c.embedding <=> %(v)s::vector) AS sim
                {_FROM}
                WHERE {ACL_SQL} AND c.matter_id = ANY(%(ids)s) AND c.embedding IS NOT NULL
                ORDER BY (c.embedding <=> %(v)s::vector) + 0 LIMIT 60
                """,
                {**base, "v": vec},
            )
        ]
    if overview:
        # Opening passages of every document: parties, recitals, operative purpose.
        cands += _fetch(
            conn,
            f"""
            SELECT * FROM (
              SELECT {_SELECT}, row_number() OVER (PARTITION BY c.document_id ORDER BY c.chunk_index) AS rn
              {_FROM}
              WHERE {ACL_SQL} AND c.matter_id = ANY(%(ids)s) AND length(c.text) >= {MIN_PASSAGE_CHARS}
            ) x WHERE rn <= 4
            """,
            base,
        )
    rows = [r for r in _collapse(cands) if not _is_heading(r)]
    return rank_passages(question, rows, limit=limit, per_doc=per_doc, overview=overview)


def rank_passages(
    question: str,
    rows: list[dict],
    *,
    limit: int = 14,
    per_doc: int = 4,
    overview: bool = False,
) -> list[dict]:
    rows = [r for r in rows if not _is_heading(r)]
    if not rows:
        return []
    ce = _cross_encode(question, rows)
    for r, s in zip(rows, ce):
        r["ce_score"] = float(s)
        r["score"] = float(s)
    rows.sort(key=lambda r: -r["score"])
    out: list[dict] = []
    per: dict[str, int] = {}
    if overview:
        # Guarantee every document is represented once before filling by score.
        for r in sorted(rows, key=lambda r: (r["document_id"], r.get("chunk_index") or 0)):
            if r["document_id"] not in per:
                per[r["document_id"]] = 1
                out.append(r)
    for r in rows:
        if len(out) >= limit:
            break
        if r in out or per.get(r["document_id"], 0) >= per_doc:
            continue
        per[r["document_id"]] = per.get(r["document_id"], 0) + 1
        out.append(r)
    out.sort(key=lambda r: -r["score"])
    return [_public(r) for r in out[:limit]]


def _public(r: dict) -> dict[str, Any]:
    keep = (
        "chunk_id", "chunk_index", "document_id", "matter_id", "text", "page_number", "section_title",
        "title", "document_type", "doc_date", "author_name", "matter_code", "client_name",
        "matter_title", "court", "practice_area", "score", "ce_score",
    )
    return {k: r.get(k) for k in keep}
