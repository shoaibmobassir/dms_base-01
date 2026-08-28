from __future__ import annotations

from psycopg.rows import dict_row

from app.query.understand import ParsedQuery
from app.retrieval.route import MATTER_ID_RE

ACL = """
    (
        (%(member_id)s::text IS NULL)
        OR p.restricted = FALSE
        OR %(member_id)s::text = ANY (p.allowed_members)
    )
"""


def _seeds(query: str, parsed: ParsedQuery | None) -> list[str]:
    if parsed and parsed.matter_ids:
        return list(parsed.matter_ids)
    return [m.upper() for m in MATTER_ID_RE.findall(query or "")]


def graph_search(
    conn,
    query: str,
    member_id: str | None,
    limit: int = 50,
    parsed: ParsedQuery | None = None,
) -> list[dict]:
    """SQL matter graph: related matters + same-lead/different-client, then ACL docs."""
    seeds = _seeds(query, parsed)
    if not seeds:
        return []

    related_sql = """
        SELECT DISTINCT m.matter_id
        FROM (
            SELECT r.target_id AS matter_id
            FROM relationships r
            WHERE r.source_id = ANY(%(seeds)s)
            UNION
            SELECT r.source_id AS matter_id
            FROM relationships r
            WHERE r.target_id = ANY(%(seeds)s)
            UNION
            SELECT m2.matter_id
            FROM matters seed
            JOIN matter_members lead ON lead.matter_id = seed.matter_id
                AND lead.role_on_matter IN ('Lead', 'Partner')
            JOIN matter_members other ON other.member_id = lead.member_id
                AND other.role_on_matter IN ('Lead', 'Partner')
            JOIN matters m2 ON m2.matter_id = other.matter_id
            WHERE seed.matter_id = ANY(%(seeds)s)
              AND m2.client_id IS DISTINCT FROM seed.client_id
              AND m2.matter_id <> seed.matter_id
        ) m
    """
    docs_sql = f"""
        SELECT DISTINCT ON (d.matter_id)
               d.document_id, d.matter_id, d.title, d.document_type,
               c.chunk_id, c.text,
               1.0 AS score,
               'graph' AS channel
        FROM documents d
        JOIN chunks c ON c.document_id = d.document_id AND c.chunk_index = 0
        JOIN permissions p ON p.matter_id = d.matter_id
        WHERE {ACL}
          AND d.matter_id IN ({related_sql})
        ORDER BY d.matter_id, c.chunk_index
        LIMIT %(limit)s
    """
    params = {"member_id": member_id, "seeds": seeds, "limit": limit}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(docs_sql, params)
        return list(cur.fetchall())
