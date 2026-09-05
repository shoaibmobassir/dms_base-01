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
        filters = filters or {}
        matter_ids = filters.get("matter_ids") or []
        matter_clause = ""
        if matter_ids:
            matter_clause = "AND d.matter_id = ANY(%(matter_ids)s)"
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
            {matter_clause}
            ORDER BY score DESC
            LIMIT %(limit)s
        """
        params = {
            "query": query,
            "member_id": member_id,
            "limit": limit,
            "matter_ids": matter_ids or ["__none__"],
        }
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
        filters = filters or {}
        matter_ids = filters.get("matter_ids") or []
        matter_clause = ""
        if matter_ids:
            matter_clause = "AND d.matter_id = ANY(%(matter_ids)s)"
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
            {matter_clause}
            ORDER BY c.embedding <=> %(qvec)s::vector
            LIMIT %(limit)s
        """
        params = {
            "qvec": vector,
            "member_id": member_id,
            "limit": limit,
            "matter_ids": matter_ids or ["__none__"],
        }
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
        exact_title_mode: bool = False,
    ) -> list[dict]:
        """Search documents by structured metadata fields."""
        mids = matter_ids or []
        codes = matter_codes or []

        # If we have specific matter IDs/codes, do scoped search
        if mids or codes:
            return await self._scoped_search(
                conn, member_id, limit, mids, codes, rank_query or query,
            )

        if exact_title_mode:
            return await self._exact_title_search(
                conn, member_id, limit, query or rank_query or "",
            )

        return await self._catalog_search(
            conn, member_id, limit, mids, codes, query,
            practice_area, dedupe_matters,
        )

    async def _exact_title_search(
        self, conn, member_id, limit, needle: str,
    ) -> list[dict]:
        """Exact / near-exact matter-title path for 'matter code for …' queries.

        Ranks by title match quality then document_id so duplicate-titled matters
        still surface the earliest gold documents (DOC-00001 before DOC-37302).
        """
        text = (needle or "").strip()
        if len(text) < 3:
            return []
        # Normalize fancy dashes to improve equality matching
        norm = (
            text.replace("\u2014", "-").replace("\u2013", "-").replace("—", "-").replace("–", "-")
        )
        like = self._like(text)
        like_norm = self._like(norm)
        sql = f"""
            SELECT d.document_id, d.matter_id, d.matter_code, d.title, d.document_type,
                   d.author_name, d.doc_date,
                   m.client_name, m.court, m.practice_area, m.title AS matter_title,
                   c.chunk_id, c.chunk_index, c.text,
                   (
                     CASE
                       WHEN lower(m.title) = lower(%(needle)s) THEN 100.0
                       WHEN lower(replace(replace(m.title, '—', '-'), '–', '-'))
                            = lower(%(norm)s) THEN 95.0
                       WHEN m.title ILIKE %(like)s ESCAPE '\\' THEN 80.0
                       WHEN cl.name ILIKE %(like)s ESCAPE '\\' THEN 50.0
                       ELSE 10.0
                     END
                     + CASE WHEN d.document_id ~ '^DOC-0+[0-9]+$' THEN
                         1.0 / (1.0 + abs(substring(d.document_id from '[0-9]+')::int))
                       ELSE 0.0 END
                   ) AS score
            FROM documents d
            JOIN chunks c ON c.document_id = d.document_id AND c.chunk_index = 0
            JOIN permissions p ON p.matter_id = d.matter_id
            JOIN matters m ON m.matter_id = d.matter_id
            JOIN clients cl ON cl.client_id = m.client_id
            WHERE {_ACL_WHERE}
            AND (
                m.title ILIKE %(like)s ESCAPE '\\'
                OR replace(replace(m.title, '—', '-'), '–', '-') ILIKE %(like_norm)s ESCAPE '\\'
                OR cl.name ILIKE %(like)s ESCAPE '\\'
                OR d.title ILIKE %(like)s ESCAPE '\\'
            )
            ORDER BY score DESC, d.document_id ASC
            LIMIT %(limit)s
        """
        params = {
            "member_id": member_id,
            "needle": text,
            "norm": norm,
            "like": like,
            "like_norm": like_norm,
            "limit": limit,
        }
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

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

    async def resolve_matters(
        self,
        conn,
        needle: str,
        member_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Resolve candidate matter IDs for hierarchical scope (no ranking of chunks).

        Returns matter rows with document_count for candidate-reduction metrics.
        """
        text = (needle or "").strip()
        if len(text) < 3:
            return []
        like = PgMetadataStore._like(text)
        sql = f"""
            SELECT m.matter_id, m.matter_code, m.title, m.practice_area,
                   cl.name AS client_name,
                   COUNT(DISTINCT d.document_id) AS document_count,
                   (
                     CASE
                       WHEN lower(cl.name) = lower(%(needle)s) THEN 100.0
                       WHEN cl.name ILIKE %(like)s ESCAPE '\\' THEN 80.0
                       WHEN lower(m.title) = lower(%(needle)s) THEN 90.0
                       WHEN m.title ILIKE %(like)s ESCAPE '\\' THEN 70.0
                       WHEN m.matter_code ILIKE %(like)s ESCAPE '\\' THEN 60.0
                       ELSE 10.0
                     END
                   ) AS score
            FROM matters m
            JOIN clients cl ON cl.client_id = m.client_id
            JOIN permissions p ON p.matter_id = m.matter_id
            LEFT JOIN documents d ON d.matter_id = m.matter_id
            WHERE {_ACL_WHERE}
              AND (
                cl.name ILIKE %(like)s ESCAPE '\\'
                OR m.title ILIKE %(like)s ESCAPE '\\'
                OR m.matter_code ILIKE %(like)s ESCAPE '\\'
                OR %(needle)s = ANY(cl.aliases)
              )
            GROUP BY m.matter_id, m.matter_code, m.title, m.practice_area, cl.name
            ORDER BY score DESC, document_count DESC, m.matter_id
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

    async def search_lexical_or(
        self,
        conn,
        tsquery: str,
        member_id: str | None = None,
        limit: int = 50,
        practice_area: str | None = None,
    ) -> list[dict]:
        """OR-style FTS over weighted matter metadata (P5.6-C1).

        Field weights (tsvector setweight):
          A title / matter_code
          B practice / theme / legal_issues
          C matter_type / opposing_party / jurisdiction / court
          D facts / client_name
        """
        if not (tsquery or "").strip():
            return []
        practice_clause = ""
        if practice_area:
            practice_clause = "OR m.practice_area ILIKE %(practice_like)s ESCAPE '\\'"
        sql = f"""
            SELECT m.matter_id, m.matter_code, m.title, m.practice_area,
                   m.theme_key, m.matter_type,
                   cl.name AS client_name,
                   ts_rank_cd(
                     setweight(to_tsvector('english', coalesce(m.title,'') || ' ' ||
                       coalesce(m.matter_code,'')), 'A') ||
                     setweight(to_tsvector('english', coalesce(m.practice_area,'') || ' ' ||
                       coalesce(m.theme_key,'') || ' ' ||
                       coalesce(array_to_string(m.legal_issues,' '), '')), 'B') ||
                     setweight(to_tsvector('english', coalesce(m.matter_type,'') || ' ' ||
                       coalesce(m.opposing_party,'') || ' ' ||
                       coalesce(m.jurisdiction,'') || ' ' || coalesce(m.court,'')), 'C') ||
                     setweight(to_tsvector('english', coalesce(array_to_string(m.facts,' '),'') || ' ' ||
                       coalesce(cl.name,'')), 'D'),
                     to_tsquery('english', %(tsquery)s)
                   ) AS score
            FROM matters m
            JOIN clients cl ON cl.client_id = m.client_id
            JOIN permissions p ON p.matter_id = m.matter_id
            WHERE {_ACL_WHERE}
              AND (
                (
                  setweight(to_tsvector('english', coalesce(m.title,'') || ' ' ||
                    coalesce(m.matter_code,'')), 'A') ||
                  setweight(to_tsvector('english', coalesce(m.practice_area,'') || ' ' ||
                    coalesce(m.theme_key,'') || ' ' ||
                    coalesce(array_to_string(m.legal_issues,' '), '')), 'B') ||
                  setweight(to_tsvector('english', coalesce(m.matter_type,'') || ' ' ||
                    coalesce(m.opposing_party,'') || ' ' ||
                    coalesce(m.jurisdiction,'') || ' ' || coalesce(m.court,'')), 'C') ||
                  setweight(to_tsvector('english', coalesce(array_to_string(m.facts,' '),'') || ' ' ||
                    coalesce(cl.name,'')), 'D')
                ) @@ to_tsquery('english', %(tsquery)s)
                {practice_clause}
              )
            ORDER BY score DESC NULLS LAST, m.matter_id
            LIMIT %(limit)s
        """
        params = {
            "tsquery": tsquery,
            "member_id": member_id,
            "limit": limit,
            "practice_like": f"%{practice_area}%" if practice_area else None,
        }
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

    async def fetch_evidence_profiles(
        self,
        conn,
        member_id: str | None = None,
        *,
        theme_keys: list[str] | None = None,
        practice_area: str | None = None,
        tsquery: str | None = None,
        evidence_tsquery: str | None = None,
        limit: int = 300,
    ) -> list[dict]:
        """Matter rows with document-type aggregates and optional doc-level evidence score.

        ``evidence_tsquery`` scores how well documents *inside* the matter match
        the query (holder-likelihood), separate from matter metadata FTS.
        """
        theme_keys = theme_keys or []
        filters = [f"({_ACL_WHERE})"]
        if theme_keys:
            filters.append("m.theme_key = ANY(%(theme_keys)s)")
        if practice_area and not theme_keys:
            filters.append("m.practice_area ILIKE %(practice_like)s ESCAPE '\\'")
        if tsquery:
            filters.append(
                """(
                  to_tsvector('english', coalesce(m.title,'') || ' ' ||
                    coalesce(m.theme_key,'') || ' ' || coalesce(m.practice_area,'') || ' ' ||
                    coalesce(array_to_string(m.legal_issues,' '),''))
                  @@ to_tsquery('english', %(tsquery)s)
                )"""
            )
        # If theme_keys set, that alone is enough; else require tsquery or practice
        if not theme_keys and not tsquery and not practice_area:
            return []

        evidence_select = "0.0::float AS doc_evidence_score"
        evidence_join = ""
        if evidence_tsquery:
            evidence_select = """
                coalesce((
                  SELECT MAX(ts_rank_cd(c.tsv, to_tsquery('english', %(evidence_tsquery)s)))
                  FROM documents d2
                  JOIN chunks c ON c.document_id = d2.document_id
                  WHERE d2.matter_id = m.matter_id
                    AND c.tsv @@ to_tsquery('english', %(evidence_tsquery)s)
                ), 0.0) AS doc_evidence_score
            """

        sql = f"""
            SELECT m.matter_id, m.matter_code, m.title, m.practice_area,
                   m.theme_key, m.matter_type, m.legal_issues, m.opposing_party,
                   cl.name AS client_name,
                   coalesce(array_agg(DISTINCT d.document_type)
                     FILTER (WHERE d.document_type IS NOT NULL), ARRAY[]::text[]) AS document_types,
                   COUNT(DISTINCT d.document_id) AS document_count,
                   CASE WHEN %(tsquery)s::text IS NOT NULL THEN
                     ts_rank_cd(
                       to_tsvector('english', coalesce(m.title,'') || ' ' ||
                         coalesce(m.theme_key,'') || ' ' || coalesce(m.practice_area,'') || ' ' ||
                         coalesce(array_to_string(m.legal_issues,' '), '')),
                       to_tsquery('english', %(tsquery)s)
                     )
                   ELSE 0.0 END AS lexical_score,
                   {evidence_select}
            FROM matters m
            JOIN clients cl ON cl.client_id = m.client_id
            JOIN permissions p ON p.matter_id = m.matter_id
            LEFT JOIN documents d ON d.matter_id = m.matter_id
            {evidence_join}
            WHERE {' AND '.join(filters)}
            GROUP BY m.matter_id, m.matter_code, m.title, m.practice_area,
                     m.theme_key, m.matter_type, m.legal_issues, m.opposing_party, cl.name
            ORDER BY m.matter_id
            LIMIT %(limit)s
        """
        params = {
            "member_id": member_id,
            "theme_keys": theme_keys or ["__none__"],
            "practice_like": f"%{practice_area}%" if practice_area else None,
            "tsquery": tsquery,
            "evidence_tsquery": evidence_tsquery,
            "limit": limit,
        }
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

    async def documents_in_matters(
        self,
        conn,
        matter_ids: list[str],
        member_id: str | None = None,
        limit: int = 120,
    ) -> list[dict]:
        """Return one document head per matter inside a resolved scope.

        Avoids flooding fusion with hundreds of score=1.0 heads (which buried
        gold under hard scope). BM25/vector still search the full scoped corpus.
        """
        if not matter_ids:
            return []
        sql = f"""
            SELECT DISTINCT ON (d.matter_id)
                   d.document_id, d.matter_id, d.matter_code, d.title, d.document_type,
                   d.author_name, d.doc_date,
                   m.client_name, m.court, m.practice_area,
                   c.chunk_id, c.chunk_index, c.text,
                   1.0 AS score
            FROM documents d
            JOIN matters m ON m.matter_id = d.matter_id
            JOIN permissions p ON p.matter_id = d.matter_id
            JOIN chunks c ON c.document_id = d.document_id AND c.chunk_index = 0
            WHERE {_ACL_WHERE}
              AND d.matter_id = ANY(%(matter_ids)s)
            ORDER BY d.matter_id, d.document_id
            LIMIT %(limit)s
        """
        params = {
            "member_id": member_id,
            "matter_ids": matter_ids,
            "limit": limit,
        }
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())


class PgHierarchicalStore:
    """Three-stage retrieval: rank matters, then documents, then version-scoped chunks.

    Prefers hierarchical child chunks (``version_id IS NOT NULL AND is_parent = FALSE``)
    and falls back to legacy document chunks when version-scoped rows are absent.
    """

    async def rank_matters(
        self,
        conn,
        query: str,
        member_id: str | None = None,
        limit: int = 20,
        matter_ids: list[str] | None = None,
    ) -> list[dict]:
        text = (query or "").strip()
        if not text and not matter_ids:
            return []
        like = PgMetadataStore._like(text) if text else "%__none__%"
        sql = f"""
            SELECT m.matter_id, m.matter_code, m.title, m.practice_area,
                   m.court, cl.name AS client_name,
                   ts_rank(
                     to_tsvector('english', coalesce(m.title,'') || ' ' ||
                       coalesce(m.practice_area,'') || ' ' || coalesce(cl.name,'') || ' ' ||
                       coalesce(array_to_string(m.legal_issues, ' '), '')),
                     plainto_tsquery('english', %(q)s)
                   ) AS score
            FROM matters m
            JOIN clients cl ON cl.client_id = m.client_id
            JOIN permissions p ON p.matter_id = m.matter_id
            WHERE {_ACL_WHERE}
              AND (
                %(has_ids)s::boolean = FALSE
                OR m.matter_id = ANY(%(matter_ids)s)
              )
              AND (
                %(has_q)s::boolean = FALSE
                OR m.title ILIKE %(like)s ESCAPE '\\'
                OR m.matter_code ILIKE %(like)s ESCAPE '\\'
                OR cl.name ILIKE %(like)s ESCAPE '\\'
                OR m.practice_area ILIKE %(like)s ESCAPE '\\'
                OR to_tsvector('english', coalesce(m.title,'') || ' ' ||
                     coalesce(array_to_string(m.legal_issues,' '),''))
                   @@ plainto_tsquery('english', %(q)s)
              )
            ORDER BY score DESC NULLS LAST, m.opened_date DESC NULLS LAST
            LIMIT %(limit)s
        """
        params = {
            "member_id": member_id,
            "q": text or "legal",
            "like": like,
            "limit": limit,
            "has_ids": bool(matter_ids),
            "matter_ids": matter_ids or ["__none__"],
            "has_q": bool(text),
        }
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

    async def rank_documents(
        self,
        conn,
        query: str,
        matter_ids: list[str],
        member_id: str | None = None,
        limit: int = 40,
    ) -> list[dict]:
        if not matter_ids:
            return []
        text = (query or "").strip() or "legal"
        like = PgMetadataStore._like(text)
        sql = f"""
            SELECT d.document_id, d.matter_id, d.title, d.document_type,
                   d.author_name, d.doc_date, d.folder_path,
                   d.current_version_id AS version_id,
                   m.matter_code, m.practice_area, m.court,
                   cl.name AS client_name,
                   ts_rank(
                     to_tsvector('english', coalesce(d.title,'') || ' ' ||
                       coalesce(d.folder_path,'') || ' ' || coalesce(left(d.body, 4000),'')),
                     plainto_tsquery('english', %(q)s)
                   ) AS score
            FROM documents d
            JOIN matters m ON m.matter_id = d.matter_id
            JOIN clients cl ON cl.client_id = m.client_id
            JOIN permissions p ON p.matter_id = d.matter_id
            WHERE d.matter_id = ANY(%(matter_ids)s)
              AND {_ACL_WHERE}
              AND (
                d.title ILIKE %(like)s ESCAPE '\\'
                OR coalesce(d.folder_path,'') ILIKE %(like)s ESCAPE '\\'
                OR to_tsvector('english', coalesce(d.title,'') || ' ' ||
                     coalesce(left(d.body, 4000),''))
                   @@ plainto_tsquery('english', %(q)s)
                OR %(q)s = 'legal'
              )
            ORDER BY score DESC NULLS LAST, d.doc_date DESC NULLS LAST
            LIMIT %(limit)s
        """
        params = {
            "member_id": member_id,
            "matter_ids": matter_ids,
            "q": text,
            "like": like,
            "limit": limit,
        }
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())

    async def rank_chunks(
        self,
        conn,
        query: str,
        document_ids: list[str],
        member_id: str | None = None,
        limit: int = 80,
        children_only: bool = True,
    ) -> list[dict]:
        """Rank chunks within documents; prefer version-scoped hierarchical children."""
        if not document_ids:
            return []
        text = (query or "").strip() or "legal"
        # Stage A: version-scoped hierarchical children
        parent_clause = "AND COALESCE(c.is_parent, FALSE) = FALSE" if children_only else ""
        sql_versioned = f"""
            SELECT d.document_id, d.matter_id, d.title, d.document_type,
                   d.author_name, d.doc_date, d.folder_path AS doc_folder_path,
                   m.matter_code, m.practice_area, m.court,
                   cl.name AS client_name,
                   c.chunk_id, c.chunk_index, c.text,
                   c.version_id, c.folder_path, c.section_id, c.section_title,
                   c.page_number, c.parent_chunk_id, c.is_parent, c.block_ids,
                   ts_rank(c.tsv, plainto_tsquery('english', %(q)s)) AS score
            FROM chunks c
            JOIN documents d ON d.document_id = c.document_id
            JOIN matters m ON m.matter_id = d.matter_id
            JOIN clients cl ON cl.client_id = m.client_id
            JOIN permissions p ON p.matter_id = d.matter_id
            WHERE c.document_id = ANY(%(doc_ids)s)
              AND c.version_id IS NOT NULL
              {parent_clause}
              AND {_ACL_WHERE}
              AND (
                c.tsv @@ plainto_tsquery('english', %(q)s)
                OR c.text ILIKE %(like)s ESCAPE '\\'
                OR %(q)s = 'legal'
              )
            ORDER BY score DESC NULLS LAST, c.chunk_index
            LIMIT %(limit)s
        """
        like = PgMetadataStore._like(text)
        params = {
            "member_id": member_id,
            "doc_ids": document_ids,
            "q": text,
            "like": like,
            "limit": limit,
        }
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql_versioned, params)
            rows = list(await cur.fetchall())
            if rows:
                return rows
            # Fallback: legacy chunks (no version_id)
            sql_legacy = f"""
                SELECT d.document_id, d.matter_id, d.title, d.document_type,
                       d.author_name, d.doc_date, d.folder_path AS doc_folder_path,
                       m.matter_code, m.practice_area, m.court,
                       cl.name AS client_name,
                       c.chunk_id, c.chunk_index, c.text,
                       c.version_id, c.folder_path, c.section_id, c.section_title,
                       c.page_number, c.parent_chunk_id, c.is_parent, c.block_ids,
                       ts_rank(c.tsv, plainto_tsquery('english', %(q)s)) AS score
                FROM chunks c
                JOIN documents d ON d.document_id = c.document_id
                JOIN matters m ON m.matter_id = d.matter_id
                JOIN clients cl ON cl.client_id = m.client_id
                JOIN permissions p ON p.matter_id = d.matter_id
                WHERE c.document_id = ANY(%(doc_ids)s)
                  AND c.version_id IS NULL
                  AND {_ACL_WHERE}
                  AND (
                    c.tsv @@ plainto_tsquery('english', %(q)s)
                    OR c.text ILIKE %(like)s ESCAPE '\\'
                    OR %(q)s = 'legal'
                  )
                ORDER BY score DESC NULLS LAST, c.chunk_index
                LIMIT %(limit)s
            """
            await cur.execute(sql_legacy, params)
            return list(await cur.fetchall())

    async def retrieve(
        self,
        conn,
        query: str,
        member_id: str | None = None,
        *,
        top_matters: int = 15,
        top_docs: int = 40,
        top_chunks: int = 80,
        matter_ids: list[str] | None = None,
    ) -> list[dict]:
        """Full Matter → Document → Chunk cascade."""
        matters = await self.rank_matters(
            conn, query, member_id, limit=top_matters, matter_ids=matter_ids,
        )
        mids = [m["matter_id"] for m in matters]
        if matter_ids:
            # Always include explicitly requested matters
            for mid in matter_ids:
                if mid not in mids:
                    mids.append(mid)
        if not mids:
            return []
        docs = await self.rank_documents(conn, query, mids, member_id, limit=top_docs)
        dids = [d["document_id"] for d in docs]
        if not dids:
            return []
        chunks = await self.rank_chunks(conn, query, dids, member_id, limit=top_chunks)
        # Annotate cascade stage scores for provenance ONLY — do not blend into
        # chunk relevance (P5.5.1: hierarchy = where to search, not how relevant).
        matter_scores = {m["matter_id"]: float(m.get("score") or 0.0) for m in matters}
        doc_scores = {d["document_id"]: float(d.get("score") or 0.0) for d in docs}
        for c in chunks:
            c["matter_stage_score"] = matter_scores.get(c["matter_id"], 0.0)
            c["doc_stage_score"] = doc_scores.get(c["document_id"], 0.0)
            c["hierarchy"] = "matter>document>chunk"
            if not c.get("title") and c.get("doc_title"):
                c["title"] = c["doc_title"]
            # Keep chunk ts_rank / FTS score as the sole ranking signal for this channel.
            c["score"] = float(c.get("score") or 0.0)
        return chunks
