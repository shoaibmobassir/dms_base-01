"""End-to-end FirmOS document intelligence architecture simulator."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from architecture_sim.cache import VersionedCache
from architecture_sim.corpus import generate_corpus
from architecture_sim.hashing import resolve_anchor
from architecture_sim.ingest import IngestionManager
from architecture_sim.intelligence import lexical_diff, semantic_diff_hints
from architecture_sim.observability import Tracer
from architecture_sim.retrieval import RetrievalEngine
from architecture_sim.review import ReviewEngine
from architecture_sim.store import FirmStore


@dataclass
class SimConfig:
    n_documents: int = 100
    pages_per_doc: int = 20  # use 100 for full sim; 20 keeps e2e fast
    n_matters: int = 10
    versions_per_doc: int = 2
    seed: int = 42
    max_workers: int = 8
    review_features: tuple[str, ...] = (
        "change_of_control",
        "termination",
        "indemnification",
        "liability",
        "governing_law",
        "unusual_obligations",
    )


@dataclass
class PipelineResult:
    store: FirmStore
    ingest_metrics: dict[str, Any]
    retrieval_sample: dict[str, Any]
    review_metrics: dict[str, Any]
    review_report: str
    version_diff_sample: dict[str, Any]
    anchor_resolution: dict[str, Any]
    traces: list[dict[str, Any]]
    wall_time_s: float
    pages_represented: int
    config: SimConfig

    def summary(self) -> dict[str, Any]:
        return {
            "wall_time_s": round(self.wall_time_s, 3),
            "documents": len(self.store.documents),
            "versions": len(self.store.versions),
            "folders": len(self.store.folders),
            "matters": len(self.store.matters),
            "blocks": len(self.store.blocks),
            "chunks": len(self.store.chunks),
            "pages_represented": self.pages_represented,
            "ingest": self.ingest_metrics,
            "review": self.review_metrics,
            "anchor_resolution": self.anchor_resolution,
            "version_diff_sample": {
                k: self.version_diff_sample[k]
                for k in ("document_id", "lexical", "semantic")
                if k in self.version_diff_sample
            },
        }


def run_pipeline(config: SimConfig | None = None) -> PipelineResult:
    cfg = config or SimConfig()
    store = FirmStore()
    cache = VersionedCache()
    tracer = Tracer()
    t0 = time.perf_counter()

    files = generate_corpus(
        n_documents=cfg.n_documents,
        pages_per_doc=cfg.pages_per_doc,
        n_matters=cfg.n_matters,
        seed=cfg.seed,
        versions_per_doc=cfg.versions_per_doc,
    )

    ingest = IngestionManager(store, cache=cache, tracer=tracer, max_workers=cfg.max_workers)
    doc_ids = ingest.ingest_batch(files)

    retrieval = RetrievalEngine(store, tracer=tracer)
    sample_q = "unusual change of control and indemnification liability caps"
    retrieval_sample = retrieval.retrieve(sample_q)

    # Context envelope check on top hit
    if retrieval_sample["results"]:
        top = retrieval_sample["results"][0]
        retrieval_sample["context_envelope_preview"] = retrieval.context_envelope(top)[:500]

    review = ReviewEngine(store, retrieval, cache=cache, tracer=tracer, max_workers=cfg.max_workers)
    # Review SPA docs only (not schedules) for cleaner metrics
    spa_ids = [
        d.document_id
        for d in store.documents.values()
        if d.document_type == "spa"
    ]
    review_result = review.run(spa_ids, list(cfg.review_features))

    # Version diff sample
    version_diff_sample: dict[str, Any] = {}
    for did in spa_ids:
        vers = store.versions_for(did)
        if len(vers) >= 2:
            lex = lexical_diff(vers[-2].raw_text, vers[-1].raw_text)
            sem = semantic_diff_hints(vers[-2].raw_text, vers[-1].raw_text)
            version_diff_sample = {
                "document_id": did,
                "from": vers[-2].version_id,
                "to": vers[-1].version_id,
                "lexical": lex,
                "semantic": sem,
            }
            break

    # Anchor resolution e2e on first annotation
    anchor_resolution: dict[str, Any] = {"tested": False}
    if store.annotations:
        ann = next(iter(store.annotations.values()))
        blocks = store.blocks_for_version(ann.version_id)
        resolved, conf = resolve_anchor(ann.anchor, blocks)
        # Corrupt offsets and re-resolve via quote
        broken = ann.anchor
        broken_copy = type(broken)(
            document_id=broken.document_id,
            version_id=broken.version_id,
            block_id=broken.block_id,
            start_offset=0,
            end_offset=0,
            quoted_text=broken.quoted_text,
            text_hash="deadbeef",
            page=broken.page,
            section_id=broken.section_id,
        )
        resolved2, conf2 = resolve_anchor(broken_copy, blocks)
        anchor_resolution = {
            "tested": True,
            "primary_ok": resolved is not None and conf >= 0.9,
            "fallback_ok": resolved2 is not None and conf2 >= 0.7,
            "primary_confidence": conf,
            "fallback_confidence": conf2,
        }

    wall = time.perf_counter() - t0
    pages = sum(v.page_count for v in store.versions.values() if v.is_current)

    return PipelineResult(
        store=store,
        ingest_metrics=ingest.progress.as_dict(),
        retrieval_sample={
            "query": sample_q,
            "n_matters": len(retrieval_sample["matters"]),
            "n_documents": len(retrieval_sample["documents"]),
            "n_results": len(retrieval_sample["results"]),
            "top_section": (
                retrieval_sample["results"][0].section_title
                if retrieval_sample["results"]
                else None
            ),
            "context_envelope_preview": retrieval_sample.get("context_envelope_preview"),
        },
        review_metrics=review_result.metrics,
        review_report=review_result.report,
        version_diff_sample=version_diff_sample,
        anchor_resolution=anchor_resolution,
        traces=tracer.summary(),
        wall_time_s=wall,
        pages_represented=pages,
        config=cfg,
    )
