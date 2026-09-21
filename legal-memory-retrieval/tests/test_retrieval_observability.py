from app.observability.metrics import record_latency_breakdown
from app.retrieval.engine_v2 import argument_scope_enabled, title_match_enabled
from app.retrieval.fusion_policy import _REPAIR_WEIGHTS
from evals.harbour_retrieval_eval import summarize_matter_scope, summarize_stage_latency


def test_stage_latency_skips_empty_channels() -> None:
    summary = summarize_stage_latency({"rerank": [100.0, 300.0], "bm25": []})
    assert summary["rerank"]["n"] == 2
    assert "bm25" not in summary


def test_matter_scope_resolved_rate() -> None:
    summary = summarize_matter_scope(
        [
            {"matter_count": 1, "document_universe": 4},
            {"matter_count": 0, "document_universe": 0, "fallback": "unscoped"},
        ]
    )
    assert summary["resolved_rate"] == 0.5
    assert summary["median_document_universe"] == 2.0


def test_argument_scope_is_not_a_global_fusion_weight() -> None:
    assert "argument_scope" not in _REPAIR_WEIGHTS
    assert argument_scope_enabled("argument_support", ["MTR-1"]) is True
    assert argument_scope_enabled("other", ["MTR-1"]) is False
    assert argument_scope_enabled("argument_support", []) is False
    assert title_match_enabled("document_title") is True
    assert title_match_enabled("other") is False


def test_record_latency_breakdown_bounded_labels() -> None:
    record_latency_breakdown(
        {
            "intent": "matter_research",
            "scoped": "unscoped",
            "query_class": "argument_support",
            "rerank": 400.0,
            "matter_scope": {"matter_count": 0, "document_universe": 0, "fallback": "unscoped"},
            "bm25": 20.0,
        },
        "retrieve",
        elapsed_ms=1800.0,
    )
    record_latency_breakdown({"cache": "hit", "intent": "exact_lookup"}, "retrieve", elapsed_ms=2.0)
