"""E2E tests for FirmOS document intelligence architecture simulator."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from architecture_sim.corpus import generate_corpus
from architecture_sim.hashing import make_anchor, resolve_anchor, sha256_text
from architecture_sim.intelligence import lexical_diff, semantic_diff_hints
from architecture_sim.pipeline import SimConfig, run_pipeline
from architecture_sim.structure import parse_structure


@pytest.fixture(scope="module")
def e2e_result():
    """One shared pipeline run for module-scoped e2e assertions (fast)."""
    cfg = SimConfig(
        n_documents=40,
        pages_per_doc=15,
        n_matters=8,
        versions_per_doc=2,
        max_workers=6,
        seed=7,
    )
    return run_pipeline(cfg)


class TestCorpusHierarchy:
    def test_folder_paths_preserved(self):
        files = generate_corpus(n_documents=12, pages_per_doc=5, n_matters=3, seed=1)
        assert any("/Transaction Documents/Agreements/" in f.relative_path for f in files)
        assert any("/Transaction Documents/Schedules/" in f.relative_path for f in files)
        assert all("/" in f.relative_path for f in files)

    def test_version_bodies_differ_when_liability_present(self):
        files = generate_corpus(
            n_documents=20, pages_per_doc=8, versions_per_doc=2, seed=2
        )
        spas = [f for f in files if f.document_type == "spa" and "liability" in f.features_present]
        assert spas
        # At least some liability docs should change caps across versions
        changed = [f for f in spas if f.version_bodies[0] != f.version_bodies[-1]]
        assert changed


class TestStructureAndAnchors:
    def test_parse_structure_sections(self):
        body = (
            "Preamble text.\n\n"
            "## Section 8. Indemnification\n\n"
            "Seller shall indemnify Buyer. Cap $50,000.\n\n"
            "## Section 9. Limitation of Liability\n\n"
            "Aggregate liability shall not exceed $75,000.\n"
        )
        blocks = parse_structure("VER-TEST", body, page_chars=100)
        secs = {b.section_id for b in blocks}
        assert "8" in secs and "9" in secs
        assert any(b.block_type.value == "heading" for b in blocks)

    def test_anchor_primary_and_fallback(self):
        body = "## Section 8. Indemnification\n\nThe aggregate liability of the Seller is $75,000.\n"
        blocks = parse_structure("VER-A", body)
        para = next(b for b in blocks if "aggregate liability" in b.text.lower())
        quote = "$75,000"
        anchor = make_anchor("DOC-1", "VER-A", para, quote)
        assert anchor.text_hash == sha256_text(quote)
        assert anchor.bbox is None  # coordinates not canonical

        ok, conf = resolve_anchor(anchor, blocks)
        assert ok is not None and conf >= 0.9

        broken = make_anchor("DOC-1", "VER-A", para, quote)
        broken.start_offset = 0
        broken.end_offset = 0
        broken.text_hash = "nope"
        ok2, conf2 = resolve_anchor(broken, blocks)
        assert ok2 is not None and conf2 >= 0.7


class TestPipelineE2E:
    def test_ingest_preserves_folders_and_versions(self, e2e_result):
        store = e2e_result.store
        assert len(store.documents) >= 40
        assert len(store.folders) >= 5
        assert len(store.matters) >= 1
        # Every document has a folder_path with hierarchy
        for d in store.documents.values():
            assert "/" in d.folder_path
            assert d.current_version_id
        # Immutable versions: prior versions still have chunks
        multi = [d for d in store.documents.values() if len(store.versions_for(d.document_id)) >= 2]
        assert multi
        d0 = multi[0]
        v_ids = store.document_versions[d0.document_id]
        assert len(store.chunks_for_version(v_ids[0])) > 0
        assert len(store.chunks_for_version(v_ids[-1])) > 0
        assert v_ids[0] != v_ids[-1]

    def test_object_store_uris(self, e2e_result):
        store = e2e_result.store
        assert store.objects.blobs
        uri = next(iter(store.objects.blobs))
        assert "/versions/v" in uri
        assert store.objects.exists(uri)

    def test_hierarchical_retrieval_returns_context(self, e2e_result):
        sample = e2e_result.retrieval_sample
        assert sample["n_results"] > 0
        assert sample["n_documents"] > 0
        preview = sample.get("context_envelope_preview") or ""
        assert "CLIENT:" in preview
        assert "MATTER:" in preview
        assert "FOLDER:" in preview
        assert "DOCUMENT:" in preview
        assert "SECTION:" in preview

    def test_review_map_reduce_verify(self, e2e_result):
        m = e2e_result.review_metrics
        assert m["documents_scanned"] >= 40
        assert m["map_tasks"] == m["documents_scanned"] * m["features"]
        assert m["findings_verified"] > 0
        assert m["annotations"] == m["findings_verified"]
        assert "change_of_control" in m["by_category"] or "liability" in m["by_category"]
        # Partial failure model: ingest errors should be empty for synthetic corpus
        assert e2e_result.ingest_metrics["errors"] == []

    def test_findings_have_content_anchors(self, e2e_result):
        store = e2e_result.store
        assert store.findings
        f = next(iter(store.findings.values()))
        assert f.evidence
        ev = f.evidence[0]
        assert ev.block_id
        assert ev.quote
        assert ev.text_hash == sha256_text(ev.quote)
        # Annotation bidirectional link
        anns = [a for a in store.annotations.values() if a.finding_id == f.finding_id]
        assert anns
        assert anns[0].anchor.block_id == ev.block_id

    def test_anchor_resolution_pipeline(self, e2e_result):
        ar = e2e_result.anchor_resolution
        assert ar["tested"] is True
        assert ar["primary_ok"] is True
        assert ar["fallback_ok"] is True

    def test_version_lexical_and_semantic_diff(self, e2e_result):
        vd = e2e_result.version_diff_sample
        assert vd.get("lexical", {}).get("content_changed") is True
        assert isinstance(vd.get("semantic"), list)

    def test_pages_represented_and_traces(self, e2e_result):
        # 40 SPAs * 15 pages + schedules
        assert e2e_result.pages_represented >= 40 * 15
        names = {t["name"] for t in e2e_result.traces}
        assert "ingestion" in names
        assert "retrieval" in names
        assert "review" in names
        assert "map" in names
        assert "verify" in names
        assert "reduce" in names

    def test_report_non_empty(self, e2e_result):
        assert "Review Report" in e2e_result.review_report
        assert e2e_result.wall_time_s > 0


class TestDiffHelpers:
    def test_semantic_money_change(self):
        old = "Liability shall not exceed $50,000."
        new = "Liability shall not exceed $75,000."
        hints = semantic_diff_hints(old, new)
        assert any(h["category"] == "liability" for h in hints)
        lex = lexical_diff(old, new)
        assert lex["content_changed"]
