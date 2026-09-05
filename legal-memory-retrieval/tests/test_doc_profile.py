"""Unit tests for C5.5-D document profile features."""
from __future__ import annotations

from app.retrieval.doc_profile import (
    discriminative_table,
    extract_doc_features,
    infer_document_role,
    infer_role_family,
    log_odds,
    oracle_role_families_from_gold,
)


def test_infer_roles():
    assert infer_document_role("Engagement Letter") == "ENGAGEMENT_DOCUMENT"
    assert infer_document_role("Research Memo") == "RESEARCH_MEMO"
    assert infer_document_role("Term Sheet") == "PRIMARY_AGREEMENT"


def test_role_families_and_oracle():
    assert infer_role_family("Engagement Letter") == "TRANSACTIONAL"
    assert infer_role_family("Term Sheet") == "TRANSACTIONAL"
    assert infer_role_family("Statement of Claim") == "PLEADING"
    assert infer_role_family("Hearing Notes") == "EVIDENCE_RECORD"
    assert infer_role_family("Research Memo") == "ANALYSIS"
    oracle = oracle_role_families_from_gold([
        {"document_type": "Engagement Letter"},
        {"document_type": "Term Sheet"},
        {"document_type": "Research Memo"},
        {"document_type": "Statement of Claim"},
        {"document_type": "Hearing Notes"},
    ])
    fams = {x["family"] for x in oracle}
    assert fams == {"TRANSACTIONAL", "ANALYSIS", "PLEADING", "EVIDENCE_RECORD"}


def test_extract_el_vs_memo():
    el = extract_doc_features(
        document_id="D1",
        matter_id="M1",
        document_type="Engagement Letter",
        title="Engagement Letter — Acme",
        body=(
            "ENGAGEMENT LETTER\n\nMatter: Acme\nClient: Acme Ltd\n"
            "We are pleased to act. Yours sincerely,\nSignature block\n"
        ),
    )
    memo = extract_doc_features(
        document_id="D2",
        matter_id="M1",
        document_type="Research Memo",
        title="Research Memo — Acme",
        body=(
            "RESEARCH MEMO\n\nIssue: insider trading under section 12\n"
            "Analysis: The parties must consider UPSI. See AIR 2020 SCC 1.\n" * 20
        ),
    )
    assert el.engagement_header and el.is_el_ica
    assert el.role_family == "TRANSACTIONAL"
    assert memo.memo_header and memo.is_hard_neg_type
    assert memo.role_family == "ANALYSIS"
    assert el.char_count < memo.char_count


def test_log_odds_and_table():
    assert log_odds(0.9, 0.1) > 0
    table = discriminative_table(
        [{"signature_present": 1.0, "word_count": 100.0}],
        [{"signature_present": 0.0, "word_count": 900.0}],
    )
    by = {r["feature"]: r for r in table}
    assert by["signature_present"]["log_odds"] > 0
