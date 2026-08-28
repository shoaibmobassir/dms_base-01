from app.answers.citations import extract_document_ids, filter_citations
from app.answers.extractive import extractive_answer
from app.answers.generate import answer_question
from app.answers.llm import parse_model_json


def test_filter_citations_drops_hallucinated_ids() -> None:
    hits = [{"document_id": "DOC-00122"}]
    kept = filter_citations(["DOC-00122", "DOC-99999"], hits)
    assert kept == ["DOC-00122"]


def test_extract_document_ids_order() -> None:
    assert extract_document_ids("see DOC-00002 and doc-00001 and DOC-00002") == [
        "DOC-00002",
        "DOC-00001",
    ]


def test_parse_model_json_abstains_without_allowed_citation() -> None:
    hits = [{"document_id": "DOC-00122", "text": "flood"}]
    parsed = parse_model_json(
        '{"abstain": false, "answer": "We deny", "citations": ["DOC-99999"]}',
        hits,
    )
    assert parsed["abstained"] is True
    assert parsed["citations"] == []


def test_parse_model_json_keeps_allowed_citation() -> None:
    hits = [{"document_id": "DOC-00122", "text": "flood"}]
    parsed = parse_model_json(
        '{"abstain": false, "answer": "Position is X [DOC-00122]", '
        '"citations": ["DOC-00122"]}',
        hits,
    )
    assert parsed["abstained"] is False
    assert parsed["citations"] == ["DOC-00122"]


def test_extractive_cites_retrieved_only() -> None:
    hits = [
        {
            "document_id": "DOC-00122",
            "title": "Note",
            "text": "The firm denied liability for flooding.",
        }
    ]
    out = extractive_answer("what was our position", hits)
    assert out["abstained"] is False
    assert out["citations"] == ["DOC-00122"]
    assert "DOC-00122" in out["answer"]


def test_extractive_abstains_on_empty_hits() -> None:
    out = extractive_answer("anything", [])
    assert out["abstained"] is True
    assert out["reason"] == "no_evidence"


class _EmptyConn:
    pass


def test_answer_question_empty_query_abstains(monkeypatch) -> None:
    def _no_retrieve(*_args, **_kwargs):
        raise AssertionError("retrieve must not run on empty query")

    monkeypatch.setattr("app.answers.generate.retrieve", _no_retrieve)
    out = answer_question(_EmptyConn(), "   ", member_id="MEM-00001")
    assert out["abstained"] is True
    assert out["hits"] == []


def test_answer_question_abstains_when_named_matter_missing(monkeypatch) -> None:
    def _other_matter(*_args, **_kwargs):
        return (
            [
                {
                    "document_id": "DOC-00999",
                    "matter_id": "MTR-2019-00001",
                    "title": "Unrelated",
                    "text": "noise",
                }
            ],
            {},
        )

    monkeypatch.setattr("app.answers.generate.retrieve", _other_matter)
    out = answer_question(
        _EmptyConn(),
        "What is in MTR-2020-00004?",
        member_id="MEM-00099",
        provider="extractive",
    )
    assert out["abstained"] is True
    assert out["hits"] == []
    assert out["citations"] == []
