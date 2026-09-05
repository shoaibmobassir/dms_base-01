"""Unit tests for D6 document purpose helpers."""
from __future__ import annotations

from app.retrieval.doc_purpose import (
    infer_purpose,
    oracle_purposes_from_gold,
    purpose_card,
)


def test_infer_purpose_by_type():
    el = infer_purpose(
        "Engagement Letter",
        title="Engagement Letter — Acme",
        body="ENGAGEMENT LETTER\n\nWe are pleased to act as counsel.\n",
    )
    assert el.purpose == "ESTABLISH"
    assert el.role_family == "TRANSACTIONAL"
    assert el.phrase_hits

    ts = infer_purpose("Term Sheet", title="Term Sheet — Merger", body="TERM SHEET\n")
    assert ts.purpose == "PROPOSE"

    claim = infer_purpose(
        "Statement of Claim",
        title="Statement of Claim — Flood",
        body="STATEMENT OF CLAIM\nPlaintiff avers...\n",
    )
    assert claim.purpose == "PLEAD"


def test_oracle_multi_purpose():
    oracle = oracle_purposes_from_gold([
        {"document_type": "Engagement Letter", "title": "EL"},
        {"document_type": "Initial Case Assessment", "title": "ICA"},
        {"document_type": "Term Sheet", "title": "TS"},
        {"document_type": "Research Memo", "title": "RM"},
        {"document_type": "Statement of Claim", "title": "SOC"},
        {"document_type": "Hearing Notes", "title": "HN"},
    ])
    purposes = {x["purpose"] for x in oracle}
    assert "ESTABLISH" in purposes
    assert "ASSESS" in purposes
    assert "PROPOSE" in purposes
    assert "ANALYZE" in purposes
    assert "PLEAD" in purposes
    assert "RECORD" in purposes


def test_purpose_card_separates_topic_from_purpose():
    doc = {
        "document_id": "D1",
        "document_type": "Engagement Letter",
        "title": "Engagement Letter — Insider",
        "body": "ENGAGEMENT LETTER\ninvestment insider ownership UPSI\n",
    }
    sig = infer_purpose(doc["document_type"], title=doc["title"], body=doc["body"])
    card = purpose_card(doc, sig)
    assert card["purpose"] == "ESTABLISH"
    assert "insider" in card["topics"] or "investment" in card["topics"]
