"""Hierarchical hybrid retrieval: Matter → Document → Chunk + BM25/Vector/RRF."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from architecture_sim.hashing import bm25_score, cosine, embed_text, tokenize
from architecture_sim.models import Chunk
from architecture_sim.observability import Tracer
from architecture_sim.store import FirmStore


@dataclass
class Candidate:
    chunk_id: str
    document_id: str
    version_id: str
    matter_id: str
    score: float
    channel: str
    text: str
    section_id: str
    section_title: str
    page: int
    folder_path: str
    provenance: dict[str, Any] = field(default_factory=dict)


def rrf_fuse(
    ranked_lists: list[list[Candidate]],
    k: int = 60,
) -> list[Candidate]:
    scores: dict[str, float] = defaultdict(float)
    best: dict[str, Candidate] = {}
    for channel_list in ranked_lists:
        for rank, c in enumerate(channel_list, start=1):
            scores[c.chunk_id] += 1.0 / (k + rank)
            prev = best.get(c.chunk_id)
            if not prev or c.score > prev.score:
                best[c.chunk_id] = c
    fused = []
    for cid, s in sorted(scores.items(), key=lambda x: -x[1]):
        c = best[cid]
        fused.append(
            Candidate(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                version_id=c.version_id,
                matter_id=c.matter_id,
                score=s,
                channel="rrf",
                text=c.text,
                section_id=c.section_id,
                section_title=c.section_title,
                page=c.page,
                folder_path=c.folder_path,
                provenance={"channels": True, "rrf": s, "base_channel": c.channel},
            )
        )
    return fused


class RetrievalEngine:
    """
    Answers: Where is the evidence?

    Three-stage: matter summaries → document summaries → chunks,
    then BM25 + vector fusion + light rerank.
    """

    def __init__(self, store: FirmStore, tracer: Tracer | None = None):
        self.store = store
        self.tracer = tracer or Tracer()
        self._rebuild_stats()

    def _rebuild_stats(self) -> None:
        self._child_chunks: list[Chunk] = [
            c for c in self.store.chunks.values() if c.parent_chunk_id is not None
        ]
        # Prefer current versions only for default search
        current_vids = {
            d.current_version_id
            for d in self.store.documents.values()
            if d.current_version_id
        }
        self._child_chunks = [c for c in self._child_chunks if c.version_id in current_vids]
        self._doc_tokens = {c.chunk_id: tokenize(c.text) for c in self._child_chunks}
        self.n_docs = len(self._child_chunks) or 1
        self.avgdl = (
            sum(len(t) for t in self._doc_tokens.values()) / self.n_docs if self._doc_tokens else 1.0
        )
        self.df: dict[str, int] = defaultdict(int)
        for toks in self._doc_tokens.values():
            for t in set(toks):
                self.df[t] += 1

    def search_matters(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        q = embed_text(query)
        scored = []
        for m in self.store.matters.values():
            s = cosine(q, embed_text(m.summary or m.name))
            scored.append((m.matter_id, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    def search_documents(
        self,
        query: str,
        matter_ids: set[str] | None = None,
        top_k: int = 50,
    ) -> list[tuple[str, float]]:
        q = embed_text(query)
        q_toks = tokenize(query)
        scored = []
        for d in self.store.documents.values():
            if matter_ids and d.matter_id not in matter_ids:
                continue
            v = self.store.current_version(d.document_id)
            if not v:
                continue
            text = f"{d.name} {d.folder_path} {v.executive_summary} {' '.join(v.clauses)}"
            s = 0.6 * cosine(q, embed_text(text)) + 0.4 * (
                len(set(q_toks) & set(tokenize(text))) / max(len(set(q_toks)), 1)
            )
            scored.append((d.document_id, s))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    def _bm25(self, query: str, allowed_docs: set[str] | None, top_k: int) -> list[Candidate]:
        q_toks = tokenize(query)
        scored: list[Candidate] = []
        for c in self._child_chunks:
            if allowed_docs and c.document_id not in allowed_docs:
                continue
            s = bm25_score(q_toks, self._doc_tokens[c.chunk_id], self.avgdl, self.df, self.n_docs)
            if s <= 0:
                continue
            scored.append(self._to_candidate(c, s, "bm25"))
        scored.sort(key=lambda x: -x.score)
        return scored[:top_k]

    def _vector(self, query: str, allowed_docs: set[str] | None, top_k: int) -> list[Candidate]:
        q = embed_text(query)
        scored: list[Candidate] = []
        for c in self._child_chunks:
            if allowed_docs and c.document_id not in allowed_docs:
                continue
            if not c.embedding:
                continue
            s = cosine(q, c.embedding)
            scored.append(self._to_candidate(c, s, "vector"))
        scored.sort(key=lambda x: -x.score)
        return scored[:top_k]

    def _to_candidate(self, c: Chunk, score: float, channel: str) -> Candidate:
        return Candidate(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            version_id=c.version_id,
            matter_id=c.matter_id,
            score=score,
            channel=channel,
            text=c.text,
            section_id=c.section_id,
            section_title=c.section_title,
            page=c.page,
            folder_path=c.folder_path,
            provenance={"channel": channel},
        )

    def _rerank(self, query: str, candidates: list[Candidate], top_k: int) -> list[Candidate]:
        """Lightweight token-overlap rerank (simulates cross-encoder)."""
        q_toks = set(tokenize(query))
        reranked = []
        for c in candidates:
            overlap = len(q_toks & set(tokenize(c.text))) / max(len(q_toks), 1)
            score = 0.5 * c.score + 0.5 * overlap
            reranked.append(
                Candidate(
                    chunk_id=c.chunk_id,
                    document_id=c.document_id,
                    version_id=c.version_id,
                    matter_id=c.matter_id,
                    score=score,
                    channel="rerank",
                    text=c.text,
                    section_id=c.section_id,
                    section_title=c.section_title,
                    page=c.page,
                    folder_path=c.folder_path,
                    provenance={**c.provenance, "rerank": score},
                )
            )
        reranked.sort(key=lambda x: -x.score)
        return reranked[:top_k]

    def retrieve(
        self,
        query: str,
        top_matters: int = 10,
        top_docs: int = 40,
        top_chunks: int = 80,
        final_k: int = 30,
    ) -> dict[str, Any]:
        with self.tracer.span("retrieval", query=query[:80]):
            with self.tracer.span("matter_search"):
                matters = self.search_matters(query, top_matters)
                matter_ids = {m for m, _ in matters} if matters else None

            with self.tracer.span("document_search"):
                docs = self.search_documents(query, matter_ids, top_docs)
                doc_ids = {d for d, _ in docs}

            with self.tracer.span("chunk_search"):
                bm25 = self._bm25(query, doc_ids, top_chunks)
                vec = self._vector(query, doc_ids, top_chunks)

            with self.tracer.span("fusion_rerank"):
                fused = rrf_fuse([bm25, vec])
                final = self._rerank(query, fused, final_k)

            return {
                "matters": matters,
                "documents": docs,
                "bm25": bm25[:10],
                "vector": vec[:10],
                "results": final,
            }

    def context_envelope(self, candidate: Candidate) -> str:
        """Preserve hierarchy: client/matter/folder/doc/section/page."""
        doc = self.store.documents[candidate.document_id]
        matter = self.store.matters[doc.matter_id]
        ver = self.store.versions[candidate.version_id]
        return (
            f"CLIENT: {matter.client_name}\n"
            f"MATTER: {matter.name}\n"
            f"FOLDER: {doc.folder_path}\n"
            f"DOCUMENT: {doc.name}\n"
            f"VERSION: v{ver.version_number} ({ver.version_id})\n"
            f"SECTION: {candidate.section_title}\n"
            f"PAGE: {candidate.page}\n\n"
            f"{candidate.text}"
        )
