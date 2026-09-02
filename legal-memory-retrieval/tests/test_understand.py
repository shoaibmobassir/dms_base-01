from app.query.understand import understand
from app.sprint import CURRENT_SPRINT, FEATURES, health_payload


def test_empty_and_whitespace() -> None:
    assert understand("").intent == "empty"
    assert understand("   ").intent == "empty"
    assert understand(None).intent == "empty"  # type: ignore[arg-type]


def test_exact_matter_code_question_strips_prefix() -> None:
    parsed = understand("What is the matter code for Singh-Srinivas Holdings — Share Purchase Agreement?")
    assert parsed.intent == "exact_lookup"
    assert parsed.search_text == "Singh-Srinivas Holdings — Share Purchase Agreement"
    assert parsed.skip_vector is True
    assert parsed.skip_rerank is False


def test_matter_id_skips_rerank() -> None:
    parsed = understand("What happened in MTR-2023-00007?")
    assert parsed.matter_ids == ["MTR-2023-00007"]
    assert parsed.intent == "exact_lookup"
    assert parsed.skip_rerank is True
    assert parsed.skip_vector is True


def test_matter_code_in_long_prose_keeps_vector() -> None:
    parsed = understand(
        "What was our position regarding the flooding force majeure dispute in DIS/BLR/0004/2020?"
    )
    assert parsed.matter_codes == ["DIS/BLR/0004/2020"]
    assert parsed.intent == "cross_document"
    assert parsed.skip_vector is False
    assert parsed.skip_rerank is False


def test_graph_reasoning_intent() -> None:
    parsed = understand(
        "Find matters related to MTR-2019-00001 handled by the same lead lawyer but for different clients."
    )
    assert parsed.intent == "graph_reasoning"
    assert parsed.matter_ids == ["MTR-2019-00001"]


def test_document_id() -> None:
    parsed = understand("Open DOC-00122")
    assert parsed.document_ids == ["DOC-00122"]
    assert parsed.intent == "exact_lookup"


def test_client_research() -> None:
    parsed = understand("What have we previously done for Singh-Srinivas Holdings?")
    assert parsed.intent == "matter_research"
    assert parsed.search_text == "Singh-Srinivas Holdings"


def test_experience_maps_practice_area() -> None:
    parsed = understand("Which lawyers have experience in Arbitration?")
    assert parsed.intent == "experience_search"
    assert parsed.practice_area == "Arbitration"
    assert parsed.search_text == "Arbitration"
    assert parsed.dedupe_matters is True


def test_experience_ma_alias() -> None:
    parsed = understand("Which lawyers have experience in M&A?")
    assert parsed.practice_area == "M&A"


def test_similar_matter_keeps_semantics() -> None:
    parsed = understand(
        "Have we previously handled a construction arbitration involving flooding and force majeure?"
    )
    assert parsed.intent == "similar_matter"
    assert parsed.skip_vector is False
    assert "flooding" in parsed.search_text.lower()


def test_force_majeure_question_strips_prefix() -> None:
    parsed = understand("Have we previously advised on force majeure clauses?")
    assert parsed.intent == "semantic"
    assert parsed.search_text.lower() == "force majeure clauses"


def test_matters_involve_strips_to_client() -> None:
    parsed = understand("What matters involve Narang Limited?")
    assert parsed.intent == "matter_research"
    assert parsed.search_text == "Narang Limited"


def test_negative_style_question_is_not_exact() -> None:
    parsed = understand("Have we advised on nuclear submarine licensing?")
    assert parsed.intent == "semantic"
    assert parsed.skip_vector is False


def test_percent_and_underscore_not_stripped_from_search() -> None:
    parsed = understand("What is the matter code for 100% Acquisition_Holdings?")
    assert "100% Acquisition_Holdings" in parsed.search_text


def test_sprint_property() -> None:
    assert CURRENT_SPRINT == 8
    payload = health_payload()
    assert payload["sprint"] == 8
    assert payload["query_understanding"] is True
    assert payload["graph"] is True
    assert payload["llm"] is True
    assert FEATURES["rerank"] is True
