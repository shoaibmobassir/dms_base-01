"""Build matter profile rows (text + MiniLM embedding) for the resolver."""
from __future__ import annotations

from app.km.scope import _fetch


def profile_rows(conn, matter_ids: list[str] | None = None) -> list[dict]:
    where = "WHERE m.matter_id = ANY(%(ids)s)" if matter_ids else ""
    return _fetch(
        conn,
        f"""
        SELECT m.matter_id,
               concat_ws('. ',
                 m.title,
                 'Client: ' || cl.name,
                 nullif('Also known as: ' || array_to_string(cl.aliases, ', '), 'Also known as: '),
                 nullif('Counterparty: ' || coalesce(m.opposing_party, ''), 'Counterparty: '),
                 m.practice_area || ' ' || m.matter_type,
                 nullif(array_to_string(m.facts, ' '), ''),
                 nullif('Issues: ' || array_to_string(m.legal_issues, '; '), 'Issues: '),
                 (SELECT 'Documents: ' || string_agg(d.title, '; ' ORDER BY d.doc_date NULLS LAST)
                    FROM documents d WHERE d.matter_id = m.matter_id),
                 (SELECT 'Arguments: ' || string_agg(DISTINCT a.issue, '; ')
                    FROM arguments a WHERE a.matter_id = m.matter_id)
               ) AS profile_text
        FROM matters m JOIN clients cl ON cl.client_id = m.client_id
        {where}
        ORDER BY m.matter_id
        """,
        {"ids": matter_ids or []},
    )


def rebuild(conn, matter_ids: list[str] | None = None, batch: int = 64) -> int:
    from app.retrieval.engine_v2 import _get_embedder

    rows = profile_rows(conn, matter_ids)
    embedder = _get_embedder()
    for start in range(0, len(rows), batch):
        chunk = rows[start:start + batch]
        # MiniLM reads ~256 tokens; lead with identity fields, which come first in the text.
        vectors = embedder.encode([r["profile_text"][:2000] for r in chunk])
        with conn.cursor() as cur:
            for r, vec in zip(chunk, vectors):
                cur.execute(
                    """
                    INSERT INTO matter_profiles (matter_id, profile_text, embedding, built_at)
                    VALUES (%s, %s, %s::vector, now())
                    ON CONFLICT (matter_id) DO UPDATE
                      SET profile_text = EXCLUDED.profile_text, embedding = EXCLUDED.embedding, built_at = now()
                    """,
                    (r["matter_id"], r["profile_text"], "[" + ",".join(f"{x:.6f}" for x in vec) + "]"),
                )
    conn.commit()
    from app.km.resolver import invalidate

    invalidate()
    return len(rows)
