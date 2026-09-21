from app.retrieval.matter_llm import parse_llm_choice, party_spans


def test_party_spans_keep_countries_and_drop_boilerplate() -> None:
    spans = party_spans(
        "Papers we filed in the case Greece brought against the United Kingdom over Jerusalem concessions"
    )
    assert spans == ["Greece", "United Kingdom", "Jerusalem"]


def test_lowercase_fact_paraphrase_has_no_spans() -> None:
    assert party_spans("what was the case where acme challenged the bank") == []


def test_parse_accepts_only_a_confident_shortlist_id() -> None:
    allowed = {"MTR-1925-00005", "MTR-1924-00002"}
    raw = '{"matter_id": "MTR-1925-00005", "confidence": 0.91}'
    assert parse_llm_choice(raw, allowed) == "MTR-1925-00005"


def test_parse_rejects_invented_id_and_low_confidence() -> None:
    allowed = {"MTR-1925-00005"}
    assert parse_llm_choice('{"matter_id": "MTR-9999-00001", "confidence": 0.99}', allowed) is None
    assert parse_llm_choice('{"matter_id": "MTR-1925-00005", "confidence": 0.4}', allowed) is None
    assert parse_llm_choice('{"matter_id": null, "confidence": 0}', allowed) is None
    assert parse_llm_choice("not json", allowed) is None
