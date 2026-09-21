from app.query.understand import query_class, understand
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


def test_related_matter_id_is_not_exact_lookup() -> None:
    parsed = understand("Find matters related to MTR-1923-00001 for the same client.")
    assert parsed.intent == "graph_reasoning"
    assert parsed.matter_ids == ["MTR-1923-00001"]
    assert parsed.relationship_types == ["same_client"]
    assert parsed.skip_vector is True  # named matter id still skips open-corpus vector
    assert parsed.skip_rerank is True  # a neighbour's text will not mention the question


def test_named_relations_map_to_stored_edge_types() -> None:
    assert understand("Which matter is precedent for MTR-1923-00001?").relationship_types == [
        "precedent_for"
    ]
    assert understand(
        "Find matters related to MTR-1923-00001 with similar facts."
    ).relationship_types == ["similar_facts"]
    assert understand(
        "What matter is a follow-up to MTR-1923-00001?"
    ).relationship_types == ["follow_up_to"]


def test_lead_overlap_question_stays_untyped() -> None:
    parsed = understand(
        "Find matters related to MTR-2019-00001 handled by the same lead lawyer but for different clients."
    )
    assert parsed.intent == "graph_reasoning"
    assert parsed.relationship_types == []


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


def test_argument_boilerplate_strips_to_title_without_new_intent() -> None:
    parsed = understand(
        "Which documents support our argument on Wimbledon — PCIJ Series A No. 1?"
    )
    assert parsed.intent == "matter_research"
    assert parsed.search_text == "Wimbledon — PCIJ Series A No. 1"
    assert query_class(parsed) == "argument_support"


def test_document_title_boilerplate_strips_without_new_intent() -> None:
    parsed = understand("Find the document titled Lotus Case Judgment")
    assert parsed.intent == "matter_research"
    assert parsed.search_text == "Lotus Case Judgment"
    assert query_class(parsed) == "document_title"


def test_wrapped_title_is_argument_support_without_new_intent() -> None:
    papers = understand("Papers we filed in Wimbledon — PCIJ Series A No. 1")
    assert papers.intent == "matter_research"
    assert query_class(papers) == "argument_support"
    record = understand(
        "Where is the record of Mavrommatis Jerusalem — PCIJ Series A No. 5?"
    )
    assert record.intent == "matter_research"
    assert query_class(record) == "argument_support"
    holdout = understand(
        "Docs that back our position on Wimbledon — PCIJ Series A No. 1"
    )
    assert holdout.intent == "matter_research"
    assert query_class(holdout) == "argument_support"
    supports = understand(
        "What supports the argument in Chorzow Factory — PCIJ Series A No. 9?"
    )
    assert supports.intent == "matter_research"
    assert query_class(supports) == "argument_support"


def test_bare_title_is_not_argument_support() -> None:
    parsed = understand("Wimbledon — PCIJ Series A No. 1")
    assert query_class(parsed) == "other"


def test_fact_paraphrase_without_document_language_is_not_argument_support() -> None:
    parsed = understand(
        "What was the matter where Acme challenged the bank's termination decision?"
    )
    assert parsed.intent == "matter_research"
    assert query_class(parsed) == "other"


def test_negative_style_question_is_not_exact() -> None:
    parsed = understand("Have we advised on nuclear submarine licensing?")
    assert parsed.intent == "semantic"
    assert parsed.skip_vector is False


def test_percent_and_underscore_not_stripped_from_search() -> None:
    parsed = understand("What is the matter code for 100% Acquisition_Holdings?")
    assert "100% Acquisition_Holdings" in parsed.search_text


def test_sprint_property() -> None:
    assert CURRENT_SPRINT == 9
    payload = health_payload()
    assert payload["sprint"] == 9
    assert payload["query_understanding"] is True
    assert payload["graph"] is True
    assert payload["llm"] is True
    assert payload["engine_v2"] is True
    assert payload["retrieval_engine"] == "v2"
    assert FEATURES["rerank"] is True
