from __future__ import annotations

import re

from psycopg.rows import dict_row

from app.query.understand import ParsedQuery

MATTER_ID_RE = re.compile(r"\bMTR-\d{4}-\d+\b", re.I)
MATTER_CODE_RE = re.compile(r"\b[A-Z]{3}/[A-Z]{3}/\d{4}/\d{4}\b")

ACL = """
    (
        (%(member_id)s::text IS NULL)
        OR p.restricted = FALSE
        OR %(member_id)s::text = ANY (p.allowed_members)
    )
"""


def _like_pattern(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def metadata_search(
    conn,
    query: str,
    member_id: str | None,
    limit: int = 50,
    parsed: ParsedQuery | None = None,
) -> list[dict]:
    """Exact / near-exact lookups, or FTS ranked inside a resolved matter."""
    needle = (parsed.search_text if parsed and parsed.search_text else query).strip()
    rank_q = parsed.raw if parsed and parsed.raw else query
    matter_ids = list(parsed.matter_ids) if parsed else MATTER_ID_RE.findall(query)
    codes = list(parsed.matter_codes) if parsed else MATTER_CODE_RE.findall(query.upper())
    if not codes:
        codes = MATTER_CODE_RE.findall(needle.upper())
    practice = parsed.practice_area if parsed else None
    dedupe = bool(parsed and parsed.dedupe_matters)
    scoped = bool(matter_ids or codes) and (parsed is None or parsed.intent != "exact_lookup")
    if scoped:
        return _scoped_matter_search(
            conn,
            member_id=member_id,
            limit=limit,
            matter_ids=matter_ids,
            codes=codes,
            rank_q=rank_q,
        )
    return _catalog_search(
        conn,
        member_id=member_id,
        limit=limit,
        matter_ids=matter_ids,
        codes=codes,
        needle=needle,
        practice=practice,
        dedupe=dedupe,
    )


def _scoped_matter_search(
    conn,
    *,
    member_id: str | None,
    limit: int,
    matter_ids: list[str],
    codes: list[str],
    rank_q: str,
) -> list[dict]:
    sql = f"""
        SELECT d.document_id, d.matter_id, d.title, d.document_type,
               c.chunk_id, c.text,
               ts_rank_cd(c.tsv, plainto_tsquery('english', %(rank_q)s)) AS score,
               'metadata' AS channel
        FROM chunks c
        JOIN documents d ON d.document_id = c.document_id
        JOIN permissions p ON p.matter_id = c.matter_id
        JOIN matters m ON m.matter_id = d.matter_id
        WHERE {ACL}
        AND (
            m.matter_id = ANY(%(matter_ids)s)
            OR m.matter_code = ANY(%(codes)s)
        )
        ORDER BY score DESC
        LIMIT %(limit)s
    """
    params = {
        "member_id": member_id,
        "matter_ids": matter_ids or ["__none__"],
        "codes": codes or ["__none__"],
        "rank_q": rank_q or "the",
        "limit": limit,
    }
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def _catalog_search(
    conn,
    *,
    member_id: str | None,
    limit: int,
    matter_ids: list[str],
    codes: list[str],
    needle: str,
    practice: str | None,
    dedupe: bool,
) -> list[dict]:
    like = _like_pattern(needle) if len(needle) >= 3 else "__no_like__"
    distinct = "DISTINCT ON (d.matter_id)" if dedupe else ""
    order = "ORDER BY d.matter_id, c.chunk_index" if dedupe else ""
    sql = f"""
        SELECT {distinct} d.document_id, d.matter_id, d.title, d.document_type,
               c.chunk_id, c.text,
               1.0 AS score,
               'metadata' AS channel
        FROM documents d
        JOIN chunks c ON c.document_id = d.document_id AND c.chunk_index = 0
        JOIN permissions p ON p.matter_id = d.matter_id
        JOIN matters m ON m.matter_id = d.matter_id
        JOIN clients cl ON cl.client_id = m.client_id
        WHERE {ACL}
        AND (
            m.matter_id = ANY(%(matter_ids)s)
            OR m.matter_code ILIKE ANY(%(codes)s)
            OR m.title ILIKE %(like)s ESCAPE '\\'
            OR cl.name ILIKE %(like)s ESCAPE '\\'
            OR m.matter_code ILIKE %(like)s ESCAPE '\\'
            OR (
                %(practice)s::text IS NOT NULL
                AND m.practice_area ILIKE %(practice_like)s ESCAPE '\\'
            )
        )
        {order}
        LIMIT %(limit)s
    """
    params = {
        "member_id": member_id,
        "matter_ids": matter_ids or ["__none__"],
        "codes": codes or ["__none__"],
        "like": like,
        "practice": practice,
        "practice_like": _like_pattern(practice) if practice else "__no_like__",
        "limit": limit,
    }
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())
