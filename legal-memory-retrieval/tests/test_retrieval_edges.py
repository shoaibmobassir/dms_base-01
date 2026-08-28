from app.retrieval.fusion import fuse
from app.retrieval.graph import graph_search
from app.retrieval.metadata import _like_pattern
from app.retrieval.route import filter_vector_hits, is_exact_lookup
from evals.metrics import mrr, ndcg_at_k, recall_at_k


def test_graph_without_seed_returns_empty() -> None:
    assert graph_search(None, "Have we advised on force majeure?", None) == []
    assert graph_search(None, "", None) == []


def test_exact_lookup_edges() -> None:
    assert is_exact_lookup("What is the matter code for Acme?")
    assert is_exact_lookup("MTR-2020-00004 details")
    assert is_exact_lookup("matter REL/MUM/0005/2021")
    assert not is_exact_lookup("Have we advised on force majeure?")
    assert not is_exact_lookup("")


def test_filter_vector_abstains_when_lexical_empty() -> None:
    hits = [{"score": 0.45}, {"score": 0.51}]
    assert filter_vector_hits(hits, lexical_empty=True) == [{"score": 0.51}]
    assert len(filter_vector_hits(hits, lexical_empty=False)) == 2
    assert filter_vector_hits([], lexical_empty=True) == []


def test_fuse_empty_and_weights() -> None:
    assert fuse() == []
    assert fuse([], [], limit=5) == []
    a = [{"document_id": "d1", "chunk_id": "c1", "channel": "metadata"}]
    b = [{"document_id": "d1", "chunk_id": "c1", "channel": "keyword"}]
    out = fuse(a, b, weights={"metadata": 2.0, "keyword": 1.0})
    assert len(out) == 1
    assert out[0]["fused_score"] > 0


def test_metrics_empty_gold() -> None:
    assert recall_at_k(set(), [], 10) == 1.0
    assert recall_at_k(set(), ["x"], 10) == 0.0
    assert mrr(set(), []) == 1.0
    assert ndcg_at_k(set(), [], 10) == 1.0


def test_like_escape() -> None:
    assert _like_pattern("a%b_c") == r"%a\%b\_c%"
    assert _like_pattern("acme") == "%acme%"
