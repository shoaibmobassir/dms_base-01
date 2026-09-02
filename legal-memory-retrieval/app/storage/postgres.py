"""Postgres implementations of VectorStore, GraphStore, and SearchStore.

All three protocols are implemented against the same Postgres database using:
  VectorStore  → pgvector HNSW index on chunks.embedding
  GraphStore   → relationships table + SQL graph traversal
  SearchStore  → tsvector/GIN index on chunks.tsv

Each method accepts a connection from the async pool — the stores don't
manage their own connections.  This keeps them composable and testable.

Migration path:
  When benchmarks show a bottleneck:
    PgVectorStore → QdrantVectorStore (new file, same Protocol)
    PgGraphStore  → Neo4jGraphStore   (new file, same Protocol)
    PgSearchStore → ElasticSearchStore (new file, same Protocol)
  Zero changes to the retrieval engine.
"""
from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row


# ── ACL fragment (shared across all stores) ──────────────────────────────────

_ACL_WHERE = """
    (
        (%(member_id)s::text IS NULL)
        OR p.restricted = FALSE
        OR %(member_id)s::text = ANY (p.allowed_members)
    )
"""


# ═══════════════════════════════════════════════════════════════════════════════
# PgSearchStore — Postgres full-text search
# ═══════════════════════════════════════════════════════════════════════════════


class PgSearchStore:
    """Full-text search using Postgres tsvector/GIN.

    Implements the SearchStore Protocol.
    """

    async def search(
        self,
        conn,
        query: str,
        member_id: str | None = None,
        limit: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> list[dict]:
        sql = f"""
            SELECT d.document_id, d.matter_id, d.matter_code, d.title, d.document_type,
                   d.author_name, d.doc_date,
                   m.client_name, m.court, m.practice_area,
                   c.chunk_id, c.chunk_index, c.text,
                   ts_rank_cd(c.tsv, plainto_tsquery('english', %(query)s)) AS score
            FROM chunks c
            JOIN documents d ON d.document_id = c.document_id
            JOIN matters m ON m.matter_id = d.matter_id
            JOIN permissions p ON p.matter_id = c.matter_id
            WHERE {_ACL_WHERE}
            AND c.tsv @@ plainto_tsquery('english', %(query)s)
            ORDER BY score DESC
            LIMIT %(limit)s
        """
        params = {"query": query, "member_id": member_id, "limit": limit}
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())


# ═══════════════════════════════════════════════════════════════════════════════
# PgVectorStore — pgvector ANN search
# ═══════════════════════════════════════════════════════════════════════════════


class PgVectorStore:
    """Vector similarity search using pgvector HNSW.

    Implements the VectorStore Protocol.
    """

    async def search(
        self,
        conn,
        vector: list[float],
        member_id: str | None = None,
        limit: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> list[dict]:
        sql = f"""
            SELECT d.document_id, d.matter_id, d.matter_code, d.title, d.document_type,
                   d.author_name, d.doc_date,
                   m.client_name, m.court, m.practice_area,
                   c.chunk_id, c.chunk_index, c.text,
                   1.0 - (c.embedding <=> %(qvec)s::vector) AS score
            FROM chunks c
            JOIN documents d ON d.document_id = c.document_id
            JOIN matters m ON m.matter_id = d.matter_id
            JOIN permissions p ON p.matter_id = c.matter_id
            WHERE c.embedding IS NOT NULL
            AND {_ACL_WHERE}
            ORDER BY c.embedding <=> %(qvec)s::vector
            LIMIT %(limit)s
        """
        params = {"qvec": vector, "member_id": member_id, "limit": limit}
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

    async def upsert(
        self,
        conn,
        id: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await conn.execute(
            "UPDATE chunks SET embedding = %s WHERE chunk_id = %s",
            (vector, id),
        )

    async def delete(self, conn, id: str) -> None:
        await conn.execute(
            "UPDATE chunks SET embedding = NULL WHERE chunk_id = %s",
            (id,),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PgGraphStore — SQL-based graph traversal
# ═══════════════════════════════════════════════════════════════════════════════


class PgGraphStore:
    """Graph traversal using Postgres relationships table.

    Implements the GraphStore Protocol.

    Two modes:
      seed()   — find graph nodes matching entities (parallel with other channels)
      expand() — multi-hop traversal from seeds (post-fusion, conditional)

    Migration: When graph complexity justifies it, create Neo4jGraphStore
    with the same method signatures.
    """

    async def seed(
        self,
        conn,
        entities: list[str],
        member_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Find documents connected to seed entities via graph relationships.

        This is Graph Operation A — runs in parallel with BM25/vector.
        """
        if not entities:
            return []

        # Find related matter IDs through the relationships table
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
                   d.document_id, d.matter_id, d.matter_code, d.title, d.document_type,
                   d.author_name, d.doc_date,
                   m.client_name, m.court, m.practice_area,
                   c.chunk_id, c.chunk_index, c.text,
                   1.0 AS score
            FROM documents d
            JOIN chunks c ON c.document_id = d.document_id AND c.chunk_index = 0
            JOIN matters m ON m.matter_id = d.matter_id
            JOIN permissions p ON p.matter_id = d.matter_id
            WHERE {_ACL_WHERE}
              AND d.matter_id IN ({related_sql})
            ORDER BY d.matter_id, c.chunk_index
            LIMIT %(limit)s
        """
        params = {"member_id": member_id, "seeds": entities, "limit": limit}
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(docs_sql, params)
            return list(await cur.fetchall())

    async def expand(
        self,
        conn,
        seed_ids: list[str],
        depth: int = 2,
        member_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Multi-hop traversal from seed matter/document IDs.

        This is Graph Operation B — runs AFTER initial candidate pool.
        Discovers related matters/documents the initial retrieval missed.
        """
        if not seed_ids:
            return []

        # Iterative expansion: find neighbors of neighbors up to `depth` hops
        visited: set[str] = set(seed_ids)
        frontier = list(seed_ids)

        for _ in range(depth):
            if not frontier:
                break
            sql = """
                SELECT DISTINCT CASE
                    WHEN r.source_id = ANY(%(frontier)s) THEN r.target_id
                    ELSE r.source_id
                END AS neighbor_id
                FROM relationships r
                WHERE r.source_id = ANY(%(frontier)s)
                   OR r.target_id = ANY(%(frontier)s)
            """
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(sql, {"frontier": frontier})
                rows = await cur.fetchall()
            new_frontier = []
            for row in rows:
                nid = row["neighbor_id"]
                if nid not in visited:
                    visited.add(nid)
                    new_frontier.append(nid)
            frontier = new_frontier

        # Fetch documents from expanded matter set (excluding original seeds)
        expanded_ids = list(visited - set(seed_ids))
        if not expanded_ids:
            return []

        docs_sql = f"""
            SELECT DISTINCT ON (d.matter_id)
                   d.document_id, d.matter_id, d.matter_code, d.title, d.document_type,
                   d.author_name, d.doc_date,
                   m.client_name, m.court, m.practice_area,
                   c.chunk_id, c.chunk_index, c.text,
                   0.5 AS score
            FROM documents d
            JOIN chunks c ON c.document_id = d.document_id AND c.chunk_index = 0
            JOIN matters m ON m.matter_id = d.matter_id
            JOIN permissions p ON p.matter_id = d.matter_id
            WHERE {_ACL_WHERE}
              AND d.matter_id = ANY(%(expanded_ids)s)
            ORDER BY d.matter_id, c.chunk_index
            LIMIT %(limit)s
        """
        params = {
            "member_id": member_id,
            "expanded_ids": expanded_ids,
            "limit": limit,
        }
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(docs_sql, params)
            return list(await cur.fetchall())

    async def related_matters(
        self,
        conn,
        matter_ids: list[str],
        member_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Find matters directly related to the given matter IDs."""
        if not matter_ids:
            return []
        sql = f"""
            SELECT DISTINCT m.matter_id, m.matter_code, m.title,
                   m.practice_area, m.court, m.status,
                   cl.name AS client_name,
                   r.rel_type
            FROM relationships r
            JOIN matters m ON m.matter_id = CASE
                WHEN r.source_id = ANY(%(matter_ids)s) THEN r.target_id
                ELSE r.source_id
            END
            JOIN clients cl ON cl.client_id = m.client_id
            JOIN permissions p ON p.matter_id = m.matter_id
            WHERE (r.source_id = ANY(%(matter_ids)s) OR r.target_id = ANY(%(matter_ids)s))
              AND m.matter_id <> ALL(%(matter_ids)s)
              AND {_ACL_WHERE}
            LIMIT %(limit)s
        """
        params = {"matter_ids": matter_ids, "member_id": member_id, "limit": limit}
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())


# ═══════════════════════════════════════════════════════════════════════════════
# Metadata store — exact entity lookups
# ═══════════════════════════════════════════════════════════════════════════════


class PgMetadataStore:
    """Exact / near-exact metadata lookups via Postgres.

    Covers matter IDs, matter codes, client names, practice areas.
    This is distinct from SearchStore (BM25) — it targets structured
    fields, not free-text content.
    """

    async def search(
        self,
        conn,
        query: str,
        member_id: str | None = None,
        limit: int = 50,
        matter_ids: list[str] | None = None,
        matter_codes: list[str] | None = None,
        practice_area: str | None = None,
        rank_query: str | None = None,
        dedupe_matters: bool = False,
    ) -> list[dict]:
        """Search documents by structured metadata fields."""
        mids = matter_ids or []
        codes = matter_codes or []

        # If we have specific matter IDs/codes, do scoped search
        if mids or codes:
            return await self._scoped_search(
                conn, member_id, limit, mids, codes, rank_query or query,
            )

        return await self._catalog_search(
            conn, member_id, limit, mids, codes, query,
            practice_area, dedupe_matters,
        )

    async def _scoped_search(
        self, conn, member_id, limit, matter_ids, codes, rank_q,
    ) -> list[dict]:
        sql = f"""
            SELECT d.document_id, d.matter_id, d.matter_code, d.title, d.document_type,
                   d.author_name, d.doc_date,
                   m.client_name, m.court, m.practice_area,
                   c.chunk_id, c.chunk_index, c.text,
                   ts_rank_cd(c.tsv, plainto_tsquery('english', %(rank_q)s)) AS score
            FROM chunks c
            JOIN documents d ON d.document_id = c.document_id
            JOIN permissions p ON p.matter_id = c.matter_id
            JOIN matters m ON m.matter_id = d.matter_id
            WHERE {_ACL_WHERE}
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
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

    async def _catalog_search(
        self, conn, member_id, limit, matter_ids, codes, needle,
        practice_area, dedupe,
    ) -> list[dict]:
        like = self._like(needle) if len(needle) >= 3 else "__no_like__"
        distinct = "DISTINCT ON (d.matter_id)" if dedupe else ""
        order = "ORDER BY d.matter_id, c.chunk_index" if dedupe else ""
        sql = f"""
            SELECT {distinct} d.document_id, d.matter_id, d.matter_code, d.title, d.document_type,
                   d.author_name, d.doc_date,
                   m.client_name, m.court, m.practice_area,
                   c.chunk_id, c.chunk_index, c.text,
                   1.0 AS score
            FROM documents d
            JOIN chunks c ON c.document_id = d.document_id AND c.chunk_index = 0
            JOIN permissions p ON p.matter_id = d.matter_id
            JOIN matters m ON m.matter_id = d.matter_id
            JOIN clients cl ON cl.client_id = m.client_id
            WHERE {_ACL_WHERE}
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
            "practice": practice_area,
            "practice_like": self._like(practice_area) if practice_area else "__no_like__",
            "limit": limit,
        }
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

    @staticmethod
    def _like(text: str) -> str:
        escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"


# ═══════════════════════════════════════════════════════════════════════════════
# Matter store — matter-level retrieval
# ═══════════════════════════════════════════════════════════════════════════════


class PgMatterStore:
    """Matter-level retrieval — find relevant matters before diving into documents.

    This enables hierarchical retrieval: Matter → Document → Chunk.
    """

    async def search_by_practice(
        self,
        conn,
        practice_area: str,
        member_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        sql = f"""
            SELECT m.matter_id, m.matter_code, m.title, m.practice_area,
                   m.court, m.status, m.legal_issues,
                   cl.name AS client_name,
                   d.document_id, d.title AS doc_title, d.document_type,
                   d.author_name, d.doc_date,
                   c.chunk_id, c.chunk_index, c.text,
                   1.0 AS score
            FROM matters m
            JOIN clients cl ON cl.client_id = m.client_id
            JOIN permissions p ON p.matter_id = m.matter_id
            JOIN documents d ON d.matter_id = m.matter_id
            JOIN chunks c ON c.document_id = d.document_id AND c.chunk_index = 0
            WHERE m.practice_area ILIKE %(practice_like)s ESCAPE '\\'
              AND {_ACL_WHERE}
            ORDER BY m.opened_date DESC NULLS LAST
            LIMIT %(limit)s
        """
        params = {
            "practice_like": f"%{practice_area}%",
            "member_id": member_id,
            "limit": limit,
        }
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

    async def search_by_client(
        self,
        conn,
        client_name: str,
        member_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        sql = f"""
            SELECT m.matter_id, m.matter_code, m.title, m.practice_area,
                   m.court, m.status, m.legal_issues,
                   cl.name AS client_name,
                   d.document_id, d.title AS doc_title, d.document_type,
                   d.author_name, d.doc_date,
                   c.chunk_id, c.chunk_index, c.text,
                   1.0 AS score
            FROM matters m
            JOIN clients cl ON cl.client_id = m.client_id
            JOIN permissions p ON p.matter_id = m.matter_id
            JOIN documents d ON d.matter_id = m.matter_id
            JOIN chunks c ON c.document_id = d.document_id AND c.chunk_index = 0
            WHERE (cl.name ILIKE %(client_like)s ESCAPE '\\' OR %(client_name)s = ANY(cl.aliases))
              AND {_ACL_WHERE}
            ORDER BY m.opened_date DESC NULLS LAST
            LIMIT %(limit)s
        """
        params = {
            "client_like": f"%{client_name}%",
            "client_name": client_name,
            "member_id": member_id,
            "limit": limit,
        }
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

    async def search_by_legal_issues(
        self,
        conn,
        issues: list[str],
        member_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        sql = f"""
            SELECT m.matter_id, m.matter_code, m.title, m.practice_area,
                   m.court, m.status, m.legal_issues,
                   cl.name AS client_name,
                   d.document_id, d.title AS doc_title, d.document_type,
                   d.author_name, d.doc_date,
                   c.chunk_id, c.chunk_index, c.text,
                   1.0 AS score
            FROM matters m
            JOIN clients cl ON cl.client_id = m.client_id
            JOIN permissions p ON p.matter_id = m.matter_id
            JOIN documents d ON d.matter_id = m.matter_id
            JOIN chunks c ON c.document_id = d.document_id AND c.chunk_index = 0
            WHERE m.legal_issues && %(issues)s
              AND {_ACL_WHERE}
            ORDER BY m.opened_date DESC NULLS LAST
            LIMIT %(limit)s
        """
        params = {
            "issues": issues,
            "member_id": member_id,
            "limit": limit,
        }
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

    async def search_by_text(
        self,
        conn,
        needle: str,
        member_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Matter-level lookup by free-text match on client, title, or code."""
        text = (needle or "").strip()
        if len(text) < 3:
            return []
        like = PgMetadataStore._like(text)
        sql = f"""
            SELECT DISTINCT ON (m.matter_id)
                   m.matter_id, m.matter_code, m.title, m.practice_area,
                   m.court, m.status, m.legal_issues,
                   cl.name AS client_name,
                   d.document_id, d.title AS doc_title, d.document_type,
                   d.author_name, d.doc_date,
                   c.chunk_id, c.chunk_index, c.text,
                   1.0 AS score
            FROM matters m
            JOIN clients cl ON cl.client_id = m.client_id
            JOIN permissions p ON p.matter_id = m.matter_id
            JOIN documents d ON d.matter_id = m.matter_id
            JOIN chunks c ON c.document_id = d.document_id AND c.chunk_index = 0
            WHERE {_ACL_WHERE}
              AND (
                cl.name ILIKE %(like)s ESCAPE '\\'
                OR m.title ILIKE %(like)s ESCAPE '\\'
                OR m.matter_code ILIKE %(like)s ESCAPE '\\'
                OR %(needle)s = ANY(cl.aliases)
              )
            ORDER BY m.matter_id, c.chunk_index
            LIMIT %(limit)s
        """
        params = {
            "like": like,
            "needle": text,
            "member_id": member_id,
            "limit": limit,
        }
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())
