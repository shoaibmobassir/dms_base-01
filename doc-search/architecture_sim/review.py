"""Review Engine: Map → Reduce → Verify over structured Findings + Evidence."""
from __future__ import annotations

import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from architecture_sim.cache import VersionedCache
from architecture_sim.hashing import make_anchor, sha256_text
from architecture_sim.intelligence import CLAUSE_KEYWORDS, lexical_diff, semantic_diff_hints
from architecture_sim.models import (
    Annotation,
    AnnotationType,
    Evidence,
    Finding,
    FindingSeverity,
    FindingStatus,
    ReviewJob,
)
from architecture_sim.observability import Tracer
from architecture_sim.retrieval import RetrievalEngine
from architecture_sim.store import FirmStore

FEATURE_QUERIES: dict[str, str] = {
    "change_of_control": "change of control consent voting securities assignment",
    "termination": "termination outside date notice days",
    "indemnification": "indemnify indemnity tax claims losses",
    "liability": "aggregate liability cap consequential damages",
    "governing_law": "governed by laws jurisdiction courts",
    "assignment": "assignment affiliate consent",
    "non_compete": "non-compete compete territory years",
    "unusual_obligations": "minimum cash balance right of first refusal unusual",
}

MONEY_RE = re.compile(r"\$[\d,]+")


@dataclass
class ReviewResult:
    job: ReviewJob
    report: str
    metrics: dict[str, Any]


class ReviewEngine:
    """
    Answers: What does the evidence mean?

    Hard boundary from RetrievalEngine.
    """

    def __init__(
        self,
        store: FirmStore,
        retrieval: RetrievalEngine,
        cache: VersionedCache | None = None,
        tracer: Tracer | None = None,
        max_workers: int = 8,
    ):
        self.store = store
        self.retrieval = retrieval
        self.cache = cache or VersionedCache()
        self.tracer = tracer or Tracer()
        self.max_workers = max_workers

    def plan(self, features: list[str]) -> list[str]:
        return [f for f in features if f in FEATURE_QUERIES]

    def _map_document_feature(
        self,
        document_id: str,
        feature: str,
    ) -> list[Finding]:
        doc = self.store.documents.get(document_id)
        if not doc or not doc.current_version_id:
            return []
        version = self.store.versions[doc.current_version_id]
        cache_hit = self.cache.get(
            "review",
            "firm",
            document_id,
            version.version_id,
            feature,
            "review-model-v1",
        )
        if cache_hit is not None:
            return cache_hit

        query = FEATURE_QUERIES[feature]
        # Restrict retrieval to this document via document summary gate + chunk filter
        retrieved = self.retrieval.retrieve(
            f"{query} {doc.name}",
            top_matters=5,
            top_docs=20,
            top_chunks=40,
            final_k=15,
        )
        evidence_chunks = [
            c for c in retrieved["results"] if c.document_id == document_id
        ]
        # Also scan version clauses / section summaries directly
        text_blob = version.raw_text
        kws = CLAUSE_KEYWORDS.get(feature, [])
        low = text_blob.lower()
        has_feature = any(k in low for k in kws) or feature in version.clauses

        findings: list[Finding] = []
        if not has_feature and not evidence_chunks:
            self.cache.set(
                findings,
                "review",
                "firm",
                document_id,
                version.version_id,
                feature,
                "review-model-v1",
            )
            return findings

        # Prefer evidence from matching sections
        blocks = self.store.blocks_for_version(version.version_id)
        quote = None
        block = None
        for b in blocks:
            if any(k in b.text.lower() for k in kws):
                quote = b.text[:200]
                block = b
                break
        if block is None and evidence_chunks:
            # map chunk → first block
            ch = self.store.chunks.get(evidence_chunks[0].chunk_id)
            if ch and ch.block_ids:
                block = self.store.blocks.get(ch.block_ids[0])
                quote = (evidence_chunks[0].text or "")[:200]

        if block is None:
            # fallback: any paragraph
            paras = [b for b in blocks if b.text]
            block = paras[0] if paras else None
            quote = (block.text[:200] if block else "")

        if not block or not quote:
            self.cache.set(
                findings,
                "review",
                "firm",
                document_id,
                version.version_id,
                feature,
                "review-model-v1",
            )
            return findings

        money = MONEY_RE.findall(block.text)
        severity = FindingSeverity.MEDIUM
        if feature in ("change_of_control", "liability", "indemnification", "unusual_obligations"):
            severity = FindingSeverity.HIGH if has_feature else FindingSeverity.LOW
        if feature == "unusual_obligations" and has_feature:
            severity = FindingSeverity.HIGH

        title_map = {
            "change_of_control": "Change of control provision present",
            "termination": "Termination rights identified",
            "indemnification": "Indemnification terms identified",
            "liability": f"Liability cap {' / '.join(money[:2]) or 'present'}",
            "governing_law": "Governing law clause present",
            "assignment": "Assignment restrictions present",
            "non_compete": "Non-compete obligation present",
            "unusual_obligations": "Unusual obligation detected",
        }

        ev = Evidence(
            version_id=version.version_id,
            block_id=block.block_id,
            page=block.page_number,
            section=block.section_id,
            quote=quote,
            offsets=(0, len(quote)),
            text_hash=sha256_text(quote),
            chunk_id=evidence_chunks[0].chunk_id if evidence_chunks else None,
        )
        finding = Finding(
            finding_id=f"FND-{uuid.uuid4().hex[:10].upper()}",
            document_id=document_id,
            version_id=version.version_id,
            category=feature,
            severity=severity,
            title=title_map.get(feature, feature),
            explanation=(
                f"{doc.name} ({doc.folder_path}): {feature.replace('_', ' ')} "
                f"evidence in section {block.section_id}, page {block.page_number}."
            ),
            confidence=0.92 if has_feature else 0.55,
            evidence=[ev],
            status=FindingStatus.OPEN,
            created_by="AI",
        )

        # Version comparison if prior version exists
        versions = self.store.versions_for(document_id)
        if len(versions) >= 2:
            prev, curr = versions[-2], versions[-1]
            hints = semantic_diff_hints(prev.raw_text, curr.raw_text)
            related = [h for h in hints if h["category"] == feature or feature == "liability"]
            if related:
                h = related[0]
                finding.comparison = {
                    "previous_version": prev.version_id,
                    "current_version": curr.version_id,
                    "old_text": str(h.get("old")),
                    "new_text": str(h.get("new")),
                }
                finding.title = h.get("title", finding.title)
                lex = lexical_diff(prev.raw_text, curr.raw_text)
                finding.explanation += (
                    f" Lexical diff: +{lex['added_lines']}/-{lex['removed_lines']} lines."
                )

        findings = [finding]
        self.cache.set(
            findings,
            "review",
            "firm",
            document_id,
            version.version_id,
            feature,
            "review-model-v1",
        )
        return findings

    def verify(self, finding: Finding) -> Finding:
        """Claim must be supported by quote present in the version text/blocks."""
        version = self.store.versions.get(finding.version_id)
        if not version:
            finding.verified = False
            finding.confidence *= 0.3
            return finding
        ok = False
        for ev in finding.evidence:
            if ev.quote and ev.quote[:40] in version.raw_text:
                ok = True
                break
            block = self.store.blocks.get(ev.block_id)
            if block and ev.quote and ev.quote[:40] in block.text:
                ok = True
                break
        finding.verified = ok
        if not ok:
            finding.confidence *= 0.2
            finding.status = FindingStatus.DISMISSED
        return finding

    def run(
        self,
        document_ids: list[str],
        features: list[str],
    ) -> ReviewResult:
        features = self.plan(features)
        job = ReviewJob(
            job_id=f"REV-{uuid.uuid4().hex[:8].upper()}",
            document_ids=document_ids,
            features=features,
            status="running",
        )
        all_findings: list[Finding] = []
        llm_calls = 0  # simulated map calls

        with self.tracer.span(
            "review",
            documents=len(document_ids),
            features=len(features),
        ):
            with self.tracer.span("map"):
                tasks = [
                    (did, feat) for did in document_ids for feat in features
                ]

                def _work(pair: tuple[str, str]) -> list[Finding]:
                    return self._map_document_feature(pair[0], pair[1])

                with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                    futs = [pool.submit(_work, t) for t in tasks]
                    for fut in as_completed(futs):
                        found = fut.result()
                        llm_calls += 1
                        all_findings.extend(found)

            with self.tracer.span("verify"):
                verified = [self.verify(f) for f in all_findings]
                verified = [f for f in verified if f.verified]

            with self.tracer.span("reduce"):
                by_cat: dict[str, list[Finding]] = {}
                for f in verified:
                    by_cat.setdefault(f.category, []).append(f)
                    self.store.findings[f.finding_id] = f
                    # Create bidirectional annotation
                    if f.evidence:
                        ev = f.evidence[0]
                        block = self.store.blocks[ev.block_id]
                        anchor = make_anchor(f.document_id, f.version_id, block, ev.quote)
                        ann = Annotation(
                            annotation_id=f"ANN-{uuid.uuid4().hex[:8].upper()}",
                            version_id=f.version_id,
                            anchor=anchor,
                            annotation_type=AnnotationType.AI_HIGHLIGHT,
                            author="AI",
                            finding_id=f.finding_id,
                            body=f.title,
                        )
                        self.store.annotations[ann.annotation_id] = ann

            report_lines = [
                f"# Review Report ({job.job_id})",
                f"Documents reviewed: {len(document_ids)}",
                f"Features: {', '.join(features)}",
                f"Findings (verified): {len(verified)}",
                "",
            ]
            for cat, items in sorted(by_cat.items()):
                high = sum(1 for x in items if x.severity == FindingSeverity.HIGH)
                report_lines.append(
                    f"## {cat.replace('_', ' ').title()} — {len(items)} findings ({high} high)"
                )
                for item in items[:8]:
                    report_lines.append(
                        f"- [{item.severity.value}] {item.title} "
                        f"(doc={item.document_id}, conf={item.confidence:.2f})"
                    )
                    if item.evidence:
                        e = item.evidence[0]
                        report_lines.append(
                            f"  evidence: §{e.section} p.{e.page} «{e.quote[:80]}…»"
                        )
                report_lines.append("")

        job.findings = verified
        job.status = "completed"
        metrics = {
            "documents_scanned": len(document_ids),
            "features": len(features),
            "map_tasks": llm_calls,
            "findings_raw": len(all_findings),
            "findings_verified": len(verified),
            "annotations": len(self.store.annotations),
            "cache": self.cache.stats(),
            "by_category": {k: len(v) for k, v in by_cat.items()},
        }
        job.metrics = metrics
        return ReviewResult(job=job, report="\n".join(report_lines), metrics=metrics)
