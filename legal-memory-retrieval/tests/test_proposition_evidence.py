"""Unit tests for C7 proposition + evidence helpers."""
from __future__ import annotations

from app.retrieval.evidence import (
    aggregate_evidence_to_documents,
    apply_soft_role_prior,
    best_evidence_span_offsets,
    evidence_id_for,
    phrase_tsquery,
    proximity_tsquery,
    rrf_evidence,
    soft_role_boost,
    term_density,
)
from app.retrieval.proposition import (
    EvidenceSpan,
    Proposition,
    format_proposition_context,
    proposition_from_dict,
    query_propositions_from_dict,
)


def test_proposition_retrieval_text():
    p = Proposition(
        id="P1",
        claim="Insider ownership is restricted.",
        subject="insider",
        predicate="ownership is restricted",
        object="ownership",
        lexical_terms=["insider", "ownership"],
    )
    text = p.retrieval_text()
    assert "Insider ownership is restricted" in text
    assert "insider" in text.lower()


def test_proposition_from_dict_roundtrip():
    d = {
        "query_id": "Q-0271",
        "query": "Find agreements restricting insider ownership",
        "theme_hints": ["t1"],
        "role_families": ["transactional"],
        "propositions": [
            {
                "id": "P1",
                "claim": "Insider ownership is restricted.",
                "subject": "insider",
                "predicate": "restricted",
                "object": "ownership",
                "lexical_terms": ["insider"],
            }
        ],
    }
    qp = query_propositions_from_dict(d)
    assert qp.query_id == "Q-0271"
    assert len(qp.propositions) == 1
    assert qp.propositions[0].id == "P1"
    assert qp.to_dict()["propositions"][0]["claim"].startswith("Insider")


def test_format_proposition_context():
    p = proposition_from_dict({
        "id": "P1",
        "claim": "Restriction applies.",
    })
    ctx = format_proposition_context(
        p,
        theme="M&A",
        role_family="transactional",
        section_title="Ownership",
        chunk_text="No insider may hold more than 5%.",
    )
    assert "[LEGAL PROPOSITION]" in ctx
    assert "Restriction applies" in ctx
    assert "No insider may hold" in ctx


def test_evidence_id_stable():
    a = evidence_id_for("CHK-1", "P1")
    b = evidence_id_for("CHK-1", "P1")
    c = evidence_id_for("CHK-1", "P2")
    assert a == b
    assert a != c
    assert a.startswith("EV-")


def test_soft_role_boost_multiplicative():
    assert soft_role_boost("TRANSACTIONAL", {"TRANSACTIONAL"}) == 2.5
    assert soft_role_boost("ANALYSIS", {"TRANSACTIONAL"}) == 0.7
    assert soft_role_boost("PLEADING", {"TRANSACTIONAL"}) == 1.0
    assert soft_role_boost(None, {"TRANSACTIONAL"}) == 1.0


def test_phrase_and_proximity_tsquery():
    terms = ["insider trading", "UPSI", "show-cause"]
    ph = phrase_tsquery(terms)
    assert ph is not None
    assert "insider" in ph and "trading" in ph
    px = proximity_tsquery(terms, distance=3)
    assert px is not None
    assert "<3>" in px


def test_apply_soft_role_prior_orders():
    spans = [
        EvidenceSpan(
            evidence_id="e1", document_id="d1", chunk_id="c1",
            score=1.0, role_family="ANALYSIS",
        ),
        EvidenceSpan(
            evidence_id="e2", document_id="d2", chunk_id="c2",
            score=0.5, role_family="TRANSACTIONAL",
        ),
    ]
    out = apply_soft_role_prior(spans, {"TRANSACTIONAL"}, preferred_mult=2.5, analysis_mult=0.7)
    assert out[0].chunk_id == "c2"  # 0.5 * 2.5 = 1.25 > 1.0 * 0.7
    assert out[0].score == 1.25


def test_rrf_evidence_merges():
    a = [
        EvidenceSpan(evidence_id="e1", document_id="d1", chunk_id="c1", score=1.0),
        EvidenceSpan(evidence_id="e2", document_id="d2", chunk_id="c2", score=0.5),
    ]
    b = [
        EvidenceSpan(evidence_id="e2b", document_id="d2", chunk_id="c2", score=0.9),
        EvidenceSpan(evidence_id="e3", document_id="d3", chunk_id="c3", score=0.8),
    ]
    merged = rrf_evidence([a, b], k=10)
    ids = [s.chunk_id for s in merged]
    assert "c2" in ids
    assert ids[0] == "c2"


def test_aggregate_max():
    spans = [
        EvidenceSpan(evidence_id="e1", document_id="d1", chunk_id="c1", score=0.5),
        EvidenceSpan(evidence_id="e2", document_id="d1", chunk_id="c2", score=0.9),
        EvidenceSpan(evidence_id="e3", document_id="d2", chunk_id="c3", score=0.7),
    ]
    docs = aggregate_evidence_to_documents(spans, method="max")
    assert docs[0]["document_id"] == "d1"
    assert docs[0]["score"] == 0.9
    assert docs[0]["n_evidence"] == 2


def test_term_density_and_span():
    text = "Header\n\nFacts: SEBI issued a show-cause notice alleging UPSI trading.\nMore."
    terms = ["UPSI", "show-cause", "insider"]
    assert term_density(text, terms) > 0.5
    start, end, quoted = best_evidence_span_offsets(text, terms, window=80)
    assert "UPSI" in quoted or "show-cause" in quoted
    assert end > start


def test_rerank_evidence_orders_by_ce():
    from app.retrieval.evidence_rerank import rerank_evidence

    prop = Proposition(id="P1", claim="Insider ownership is restricted.")
    spans = [
        EvidenceSpan(
            evidence_id="e1", document_id="d1", chunk_id="c1",
            score=0.9, quoted_text="unrelated memo about markets",
            role_family="ANALYSIS", document_type="Research Memo",
        ),
        EvidenceSpan(
            evidence_id="e2", document_id="d2", chunk_id="c2",
            score=0.2, quoted_text="Insider ownership is restricted to 5%.",
            role_family="TRANSACTIONAL", document_type="Engagement Letter",
        ),
    ]

    def fake_predict(pairs):
        return [0.1, 0.9]

    out = rerank_evidence(prop, spans, predict=fake_predict, ce_weight=1.0)
    assert out[0].chunk_id == "c2"
