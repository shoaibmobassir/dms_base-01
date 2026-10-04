"""Find-in-document over a version's blocks."""
from __future__ import annotations

from app.documents.block_search import search_blocks
from tests.conftest import as_member

BLOCKS = [
    {"block_id": "b1", "text": "Services Agreement between the parties", "page_number": 1},
    {"block_id": "b2", "text": "The Supplier shall deliver within 30 days of the order.", "page_number": 1},
    {"block_id": "b3", "text": "Payment is due DELIVERY plus fifteen days.", "page_number": 2, "section_title": "Payment"},
]


def test_matches_are_case_insensitive_and_in_reading_order():
    out = search_blocks(BLOCKS, "deliver")
    assert [m["block_id"] for m in out["matches"]] == ["b2", "b3"]
    assert out["matches"][1]["index"] == 2
    assert out["matches"][1]["page_number"] == 2
    assert "DELIVERY" in out["matches"][1]["snippet"]


def test_a_one_letter_query_finds_nothing():
    assert search_blocks(BLOCKS, "a")["matches"] == []


def test_results_are_capped_but_the_total_is_reported():
    many = [{"block_id": f"b{i}", "text": "the clause"} for i in range(80)]
    out = search_blocks(many, "clause", limit=50)
    assert len(out["matches"]) == 50
    assert out["total"] == 80


def test_long_blocks_give_a_short_snippet():
    out = search_blocks([{"block_id": "x", "text": "word " * 200 + "needle" + " word" * 200}], "needle")
    assert len(out["matches"][0]["snippet"]) < 200


def test_search_is_refused_for_an_unknown_document(client, seeded):
    res = client.get("/api/documents/NOPE/versions/NOPE/search?q=agreement", headers=as_member("MEM-00001"))
    assert res.status_code == 404


def test_line_breaks_and_double_spaces_do_not_hide_a_phrase():
    blocks = [{"block_id": "b", "text": "Payment is due\nwithin   30 days"}]
    out = search_blocks(blocks, "due within 30")
    assert [m["block_id"] for m in out["matches"]] == ["b"]


def test_a_version_of_another_document_cannot_be_searched(client, seeded):
    headers = as_member("MEM-00001")
    docs = client.get("/api/documents?limit=60", headers=headers).json()["items"]
    versions = {}
    for d in docs:
        detail = client.get(f"/api/documents/{d['document_id']}", headers=headers).json()
        if detail.get("current_version_id"):
            versions[d["document_id"]] = detail["current_version_id"]
        if len(versions) == 2:
            break
    assert len(versions) == 2, "needs two documents with versions"
    (doc_a, ver_a), (doc_b, ver_b) = versions.items()
    assert client.get(f"/api/documents/{doc_a}/versions/{ver_a}/search?q=the", headers=headers).status_code == 200
    # Document A is readable, but version B is not one of its versions.
    assert client.get(f"/api/documents/{doc_a}/versions/{ver_b}/search?q=the", headers=headers).status_code == 404
    assert client.get(f"/api/documents/{doc_a}/versions/{ver_b}/blocks", headers=headers).status_code == 404
