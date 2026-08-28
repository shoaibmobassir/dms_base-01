from app.retrieval.reranker import rerank


def test_rerank_promotes_high_ce_hit() -> None:
    hits = [
        {"document_id": "a", "title": "A", "text": "aaa", "fused_score": 0.9},
        {"document_id": "b", "title": "B", "text": "bbb", "fused_score": 0.1},
    ]

    def predict(_pairs):
        return [0.0, 10.0]

    ranked = rerank("q", hits, predict=predict, ce_weight=0.9)
    assert ranked[0]["document_id"] == "b"
    assert "rerank_score" in ranked[0]
    assert "ce_score" in ranked[0]


def test_rerank_skips_singleton() -> None:
    hits = [{"document_id": "a", "fused_score": 1.0}]
    assert rerank("q", hits) is hits
