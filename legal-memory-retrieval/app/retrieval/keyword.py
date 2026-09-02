from __future__ import annotations

from psycopg.rows import dict_row


def keyword_search(conn, query: str, member_id: str | None, limit: int = 50) -> list[dict]:
    sql = """
        SELECT d.document_id, d.matter_id, d.matter_code, d.title, d.document_type,
               d.author_name, d.doc_date,
               m.client_name, m.court, m.practice_area,
               c.chunk_id, c.chunk_index, c.text,
               ts_rank_cd(c.tsv, plainto_tsquery('english', %(query)s)) AS score,
               'keyword' AS channel
        FROM chunks c
        JOIN documents d ON d.document_id = c.document_id
        JOIN matters m ON m.matter_id = d.matter_id
        JOIN permissions p ON p.matter_id = c.matter_id
        WHERE (
            (%(member_id)s::text IS NULL)
            OR p.restricted = FALSE
            OR %(member_id)s::text = ANY (p.allowed_members)
        )
        AND c.tsv @@ plainto_tsquery('english', %(query)s)
        ORDER BY score DESC
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"query": query, "member_id": member_id, "limit": limit})
        return list(cur.fetchall())
