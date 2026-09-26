from __future__ import annotations

from psycopg.rows import dict_row

from app.retrieval.matter_resolver import chunk_or_tsquery


def keyword_search(conn, query: str, member_id: str | None, limit: int = 50) -> list[dict]:
    tsquery = chunk_or_tsquery(query)
    if not tsquery:
        return []
    # chunks.tsv_full = chunk text + document title/code at weight A, stored and
    # GIN-indexed (migration 20260926b); the per-row concatenation it replaces forced a seq scan.
    match_vec = "c.tsv_full"
    sql = f"""
        SELECT d.document_id, d.matter_id, d.matter_code, d.title, d.document_type,
               d.author_name, d.doc_date,
               m.client_name, m.court, m.practice_area,
               c.chunk_id, c.chunk_index, c.text,
               ts_rank_cd({match_vec}, to_tsquery('english', %(tsquery)s)) AS score,
               'keyword' AS channel
        FROM chunks c
        JOIN documents d ON d.document_id = c.document_id
        JOIN matters m ON m.matter_id = d.matter_id
        JOIN permissions p ON p.matter_id = c.matter_id
        WHERE (
            (%(member_id)s::text IS NULL)
            OR ((p.restricted = FALSE OR %(member_id)s::text = ANY (p.allowed_members))
                AND NOT (%(member_id)s::text = ANY (p.denied_members)))
        )
        AND ({match_vec}) @@ to_tsquery('english', %(tsquery)s)
        ORDER BY score DESC
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"tsquery": tsquery, "member_id": member_id, "limit": limit})
        return list(cur.fetchall())
