"""Retrieval contracts — the interfaces every channel, store, and pipeline component implements.

This module defines the Protocol classes and data contracts that decouple the
retrieval engine from specific infrastructure (Postgres, pgvector, Neo4j, etc.).

Design rationale:
  The retrieval engine shouldn't know or care whether candidates come from
  pgvector, Qdrant, Elasticsearch, or a graph database.  Every channel returns
  the same Candidate shape, every store implements the same Protocol, and the
  engine orchestrates them through these contracts alone.

  This means:
    - Channels are independently testable (mock the store)
    - Stores are independently swappable (pgvector → Qdrant = one file)
    - The engine never imports a specific DB driver
    - Evaluation can compare channel configurations without code changes

Usage:
    class BM25Retriever:
        async def retrieve(self, query, context) -> list[Candidate]:
            ...

    class PgVectorStore:
        async def search(self, vector, limit, filters) -> list[dict]:
            ...
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ═══════════════════════════════════════════════════════════════════════════════
# Candidate — the universal retrieval result
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Provenance:
    """Full lineage of how and why a candidate was retrieved.

    Populated incrementally as the candidate moves through the pipeline:
      channel function  → sets channel, raw_score
      ACL filter        → sets acl_passed
      fusion            → sets fusion_score, fusion_rank
      graph expansion   → sets graph_path
      reranker          → sets rerank_score, ce_score
    """

    channel: str = ""
    raw_score: float = 0.0

    # Populated by fusion
    channels_found_in: list[str] = field(default_factory=list)
    bm25_score: float | None = None
    vector_score: float | None = None
    metadata_score: float | None = None
    matter_score: float | None = None
    graph_score: float | None = None
    similar_matter_score: float | None = None

    # Populated by graph expansion
    graph_path: list[str] = field(default_factory=list)
    expansion_depth: int = 0

    # Populated by reranker
    ce_score: float | None = None

    # Populated by ACL
    acl_passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "channel": self.channel,
            "raw_score": self.raw_score,
            "channels_found_in": self.channels_found_in,
        }
        for attr in (
            "bm25_score", "vector_score", "metadata_score",
            "matter_score", "graph_score", "similar_matter_score",
            "ce_score",
        ):
            val = getattr(self, attr)
            if val is not None:
                d[attr] = val
        if self.graph_path:
            d["graph_path"] = self.graph_path
            d["expansion_depth"] = self.expansion_depth
        return d


@dataclass
class Candidate:
    """Universal retrieval result returned by every channel.

    Every retrieval channel — BM25, vector, metadata, matter, graph, similar matter —
    returns a list of Candidates.  Fusion, ACL filtering, deduplication, reranking,
    and context building all operate on Candidates exclusively.

    This contract means the engine never needs to know which store or channel
    produced the result.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    chunk_id: str
    document_id: str
    matter_id: str
    tenant_id: str | None = None

    # ── Content ───────────────────────────────────────────────────────────────
    text: str = ""
    title: str = ""
    document_type: str = ""
    matter_code: str = ""
    client_name: str = ""
    court: str = ""
    practice_area: str = ""
    author_name: str = ""
    doc_date: str | None = None
    chunk_index: int = 0

    # ── Scores (populated by different pipeline stages) ───────────────────────
    raw_score: float = 0.0
    fusion_score: float | None = None
    rerank_score: float | None = None

    # ── Channel + provenance ──────────────────────────────────────────────────
    channel: str = ""
    provenance: Provenance = field(default_factory=Provenance)

    # ── Extensible metadata ───────────────────────────────────────────────────
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def dedup_key(self) -> str:
        """Key used for deduplication across channels."""
        return self.chunk_id or self.document_id

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API response / caching."""
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "matter_id": self.matter_id,
            "text": self.text,
            "title": self.title,
            "document_type": self.document_type,
            "matter_code": self.matter_code,
            "client_name": self.client_name,
            "court": self.court,
            "practice_area": self.practice_area,
            "author_name": self.author_name,
            "doc_date": self.doc_date,
            "chunk_index": self.chunk_index,
            "channel": self.channel,
            "raw_score": self.raw_score,
            "fusion_score": self.fusion_score,
            "rerank_score": self.rerank_score,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_db_row(cls, row: dict, channel: str) -> Candidate:
        """Construct a Candidate from a database row (dict_row).

        This is the single point where DB schema meets retrieval contracts.
        All channel implementations should use this instead of manually
        constructing Candidates.
        """
        score = float(row.get("score") or 0.0)
        return cls(
            chunk_id=str(row.get("chunk_id") or ""),
            document_id=str(row.get("document_id") or ""),
            matter_id=str(row.get("matter_id") or ""),
            text=str(row.get("text") or ""),
            title=str(row.get("title") or ""),
            document_type=str(row.get("document_type") or ""),
            matter_code=str(row.get("matter_code") or ""),
            client_name=str(row.get("client_name") or ""),
            court=str(row.get("court") or ""),
            practice_area=str(row.get("practice_area") or ""),
            author_name=str(row.get("author_name") or ""),
            doc_date=str(row["doc_date"]) if row.get("doc_date") else None,
            chunk_index=int(row.get("chunk_index") or 0),
            channel=channel,
            raw_score=score,
            provenance=Provenance(channel=channel, raw_score=score),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Retrieval context — everything a channel needs to execute
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class RetrievalContext:
    """Shared context passed to every retrieval channel.

    Contains the parsed query, auth context, and configuration.
    Channels extract what they need; the engine doesn't need to know
    which fields each channel uses.
    """

    query_raw: str
    query_search_text: str
    intent: str

    # Auth
    member_id: str | None = None
    tenant_id: str | None = None

    # Extracted entities (from query understanding)
    matter_ids: list[str] = field(default_factory=list)
    matter_codes: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    member_ids: list[str] = field(default_factory=list)
    practice_area: str | None = None
    client_name: str | None = None
    entities: list[str] = field(default_factory=list)

    # Retrieval config
    limit: int = 50
    k: int = 20


# ═══════════════════════════════════════════════════════════════════════════════
# Retrieval plan — what the planner decides
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class RetrievalPlan:
    """Execution plan produced by the Retrieval Planner.

    Determines which channels to run, whether to do graph expansion,
    and whether to rerank.  This gives query-adaptive compute — an
    exact lookup shouldn't waste time on vector search and a cross-encoder.
    """

    channels: list[str] = field(default_factory=lambda: [
        "bm25", "vector", "metadata", "matter", "graph_seed",
    ])
    graph_expansion: bool = False
    graph_expansion_depth: int = 2
    rerank: bool = True
    rerank_candidates: int = 100
    final_k: int = 20

    # Channel-specific weights for fusion
    weights: dict[str, float] = field(default_factory=lambda: {
        "bm25": 1.2,
        "vector": 0.75,
        "metadata": 1.5,
        "matter": 1.3,
        "graph_seed": 0.9,
        "similar_matter": 0.8,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# Protocols — the interfaces that decouple retrieval from infrastructure
# ═══════════════════════════════════════════════════════════════════════════════


@runtime_checkable
class Retriever(Protocol):
    """Interface every retrieval channel must implement.

    The engine calls `retrieve()` on each channel in parallel via
    asyncio.gather.  Each channel is responsible for acquiring its
    own DB connection (from the pool) and returning Candidates.
    """

    channel_name: str

    async def retrieve(
        self,
        query: RetrievalContext,
        limit: int = 50,
    ) -> list[Candidate]:
        ...


@runtime_checkable
class VectorStore(Protocol):
    """Abstraction over vector similarity search.

    Today: pgvector.  Tomorrow: Qdrant, Pinecone, Weaviate.
    The retriever never imports a specific vector DB driver.
    """

    async def search(
        self,
        vector: list[float],
        limit: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> list[dict]:
        ...

    async def upsert(
        self,
        id: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ...

    async def delete(self, id: str) -> None:
        ...


@runtime_checkable
class GraphStore(Protocol):
    """Abstraction over graph storage and traversal.

    Today: Postgres relationships table.
    Tomorrow: Apache AGE, Neo4j, or dedicated graph DB.

    Two modes:
      seed()   — runs in parallel with other channels
      expand() — runs after initial candidate pool is built
    """

    async def seed(
        self,
        entities: list[str],
        member_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Find graph nodes matching the given entities (parallel retrieval)."""
        ...

    async def expand(
        self,
        seed_ids: list[str],
        depth: int = 2,
        member_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Multi-hop traversal from seed nodes (post-fusion expansion)."""
        ...

    async def related_matters(
        self,
        matter_ids: list[str],
        member_id: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Find matters related to the given matter IDs."""
        ...


@runtime_checkable
class SearchStore(Protocol):
    """Abstraction over full-text search.

    Today: Postgres tsvector/GIN.
    Tomorrow: Elasticsearch, Typesense, Meilisearch.
    """

    async def search(
        self,
        query: str,
        limit: int = 50,
        filters: dict[str, Any] | None = None,
    ) -> list[dict]:
        ...


@runtime_checkable
class Ranker(Protocol):
    """Abstraction over reranking.

    Today: cross-encoder/ms-marco-MiniLM.
    Tomorrow: learned ranker, ColBERT, etc.
    """

    async def rerank(
        self,
        query: str,
        candidates: list[Candidate],
        top_k: int = 20,
    ) -> list[Candidate]:
        ...


@runtime_checkable
class Embedder(Protocol):
    """Abstraction over embedding models.

    Today: MiniLM-L6-v2 (384d).
    Tomorrow: BGE, Nomic, legal-domain model.
    The retriever doesn't know or care which model is used.
    """

    @property
    def dim(self) -> int:
        ...

    async def encode(self, texts: list[str]) -> list[list[float]]:
        ...
