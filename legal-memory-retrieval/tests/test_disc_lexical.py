"""Unit tests for P5.6-C5.4 discriminative lexical helpers."""
from __future__ import annotations

from app.retrieval.disc_lexical import (
    EL_ICA_TYPES,
    DocLexicalScore,
    FieldWeights,
    classify_tokens,
    score_to_rank_map,
)
from app.retrieval.matter_resolver import MatterQueryRep
from app.retrieval import theme_scoped as ts


def test_classify_tokens_buckets():
    rep = MatterQueryRep(
        original="upsi insider trading",
        search_text="upsi insider trading",
        terms=["upsi", "insider", "trading", "information"],
        concepts=["UPSI", "SEBI"],
        phrases=["insider trading"],
    )
    dfs = {"upsi": 5, "insider": 40, "trading": 80, "information": 900, "sebi": 30}
    buckets = classify_tokens(rep, dfs, n_docs=1000)
    assert "information" in [t.lower() for t in buckets.common]
    disc = [t.lower() for t in buckets.discriminative_terms()]
    assert "upsi" in disc or "sebi" in disc
    assert "information" not in disc


def test_el_ica_types_and_ranks():
    assert "Engagement Letter" in EL_ICA_TYPES
    assert FieldWeights().title > FieldWeights().body
    scored = [
        DocLexicalScore("D1", "M1", "t", "Engagement Letter", 9.0),
        DocLexicalScore("D2", "M1", "t", "Research Memo", 3.0),
    ]
    assert score_to_rank_map(scored)["D1"] == 1


def test_theme_retrieval_alias(monkeypatch):
    monkeypatch.delenv("THEME_SCOPED_DOCUMENT_RESOLVE", raising=False)
    monkeypatch.delenv("THEME_SCOPED_DOCUMENT_RETRIEVAL", raising=False)
    assert ts.theme_scoped_resolve_enabled() is False
    monkeypatch.setenv("THEME_SCOPED_DOCUMENT_RETRIEVAL", "on")
    assert ts.theme_scoped_resolve_enabled() is True
    monkeypatch.setenv("THEME_SCOPED_DOCUMENT_RETRIEVAL", "off")
    monkeypatch.setenv("THEME_SCOPED_DOCUMENT_RESOLVE", "on")
    assert ts.theme_scoped_resolve_enabled() is True
