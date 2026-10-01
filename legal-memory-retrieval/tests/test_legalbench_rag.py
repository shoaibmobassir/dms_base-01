"""LegalBench-RAG harness: span scoring, corpus conversion and the firm-database guard.

Uses a two-file synthetic fixture; the real benchmark data is not in the repository.
"""
from __future__ import annotations

import json

import pytest

from evals.legalbench_rag_eval import Locator, overlap, span_scores, union
from evals.legalbench_rag_prepare import assert_bench_env, bench_urls, build


def test_union_and_overlap_count_characters_once():
    assert union([(5, 10), (0, 6), (20, 25)]) == [(0, 10), (20, 25)]
    assert overlap([(0, 10), (20, 25)], [(8, 22)]) == 4


def test_span_scores_precision_and_recall():
    gold = [("a.txt", 100, 200)]
    assert span_scores([("a.txt", 100, 200)], gold) == (1.0, 1.0)
    p, r = span_scores([("a.txt", 150, 350)], gold)
    assert (p, r) == (0.25, 0.5)
    assert span_scores([("b.txt", 100, 200)], gold) == (0.0, 0.0)
    # overlapping retrieved chunks are not double-counted
    assert span_scores([("a.txt", 100, 200), ("a.txt", 150, 200)], gold) == (1.0, 1.0)


def test_locator_finds_chunk_offsets_in_the_source():
    loc = Locator({"cuad/x.txt": "Header\n\nThe Licensee shall pay royalties quarterly.\n"})
    assert loc.locate("cuad/x.txt", "The Licensee shall pay royalties quarterly.") == ("cuad/x.txt", 8, 51)
    assert loc.locate("cuad/missing.txt", "anything") is None
    assert loc.misses == 1


@pytest.fixture
def fixture_dir(tmp_path):
    corpus = tmp_path / "data" / "corpus"
    (corpus / "cuad").mkdir(parents=True)
    (corpus / "maud").mkdir(parents=True)
    (corpus / "cuad" / "lic.txt").write_text("The Licensee shall pay royalties quarterly.")
    (corpus / "maud" / "merger.txt").write_text("Closing occurs on the fifth business day.")
    bench = tmp_path / "data" / "benchmarks"
    bench.mkdir()
    (bench / "cuad.json").write_text(json.dumps({"tests": [
        {"query": "When are royalties paid?", "snippets": [{"file_path": "cuad/lic.txt", "span": [4, 43]}]},
    ]}))
    (bench / "maud.json").write_text(json.dumps({"tests": [
        {"query": "When is closing?", "snippets": [{"file_path": "maud/merger.txt", "span": [0, 41]}]},
    ]}))
    return tmp_path


def test_build_writes_our_corpus_format_and_queries(fixture_dir):
    out = fixture_dir / "prepared"
    stats = build(fixture_dir / "data", out, per_benchmark=0, seed=1, corpus_scope="full")
    assert stats["documents"] == 2 and stats["matters"] == 2 and stats["queries"] == 2
    docs = [json.loads(l) for l in (out / "documents.jsonl").read_text().splitlines()]
    doc_map = json.loads((out / "doc_map.json").read_text())
    assert {doc_map[d["document_id"]] for d in docs} == {"cuad/lic.txt", "maud/merger.txt"}
    # raw text is kept byte-for-byte so gold character spans line up
    assert docs[0]["text"] == "The Licensee shall pay royalties quarterly."
    assert json.loads((out / "permissions.json").read_text())[0]["restricted"] is False


def test_referenced_scope_keeps_only_documents_queries_point_at(fixture_dir):
    bench = fixture_dir / "data" / "benchmarks" / "maud.json"
    bench.unlink()
    stats = build(fixture_dir / "data", fixture_dir / "p2", per_benchmark=0, seed=1, corpus_scope="referenced")
    assert stats["documents"] == 1 and stats["queries"] == 1


def test_guard_refuses_the_firm_database():
    firm = "postgresql://legal:legal@localhost:55432/legal_memory"
    with pytest.raises(SystemExit):
        assert_bench_env(firm, firm)
    db, redis = bench_urls(firm, "redis://localhost:6380")
    assert db.endswith("/legalbench_rag") and redis.endswith("/9")
    assert_bench_env(db, firm)
