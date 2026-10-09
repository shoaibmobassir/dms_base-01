"""GET /api/search: finds words inside documents, keeps every kind visible, respects the ethical wall."""
from __future__ import annotations

import re

import pytest

from app.api.routers.search import KINDS, _combine, _quotas
from app.db.connection import connect
from tests.conftest import as_member


def _search(client, q: str, member: str = "MEM-00001", **params):
    resp = client.get("/api/search", params={"q": q, **params}, headers=as_member(member))
    assert resp.status_code == 200, resp.text
    return resp.json()["results"]


# --- quota logic (no database) ------------------------------------------------

def _rows(kind: str, n: int) -> list[dict]:
    return [{"kind": kind, "id": f"{kind}-{i}"} for i in range(n)]


def test_every_kind_with_hits_keeps_a_share():
    out = _combine({"matter": _rows("matter", 40), "document": _rows("document", 40), "client": _rows("client", 5)}, 20)
    kinds = [r["kind"] for r in out]
    assert len(out) == 20
    assert kinds.count("document") >= 8 and kinds.count("matter") >= 5 and kinds.count("client") >= 3


def test_unused_slots_go_to_the_other_kinds():
    out = _combine({"matter": _rows("matter", 3), "document": _rows("document", 40)}, 20)
    assert [r["kind"] for r in out].count("matter") == 3
    assert [r["kind"] for r in out].count("document") == 17


def test_single_kind_gets_the_whole_limit_and_nothing_gives_nothing():
    assert len(_combine({"document": _rows("document", 40)}, 20)) == 20
    assert _combine({}, 20) == []
    assert _quotas(20, ["document"]) == {"document": 20}
    assert set(KINDS) == {"matter", "document", "client", "member"}


# --- against the seeded database ----------------------------------------------

@pytest.fixture(scope="module")
def conn(seeded):
    with connect() as c:
        yield c


def test_word_inside_a_document_is_found(client, conn):
    """The palette used to match titles only, so a phrase inside a filing found nothing."""
    row = conn.execute(
        "SELECT document_id FROM documents WHERE body ILIKE '%knowledge and belief%' "
        "AND title NOT ILIKE '%knowledge and belief%' LIMIT 1").fetchone()
    if not row:
        pytest.skip("no document contains 'knowledge and belief'")
    hits = _search(client, "knowledge and belief", kind="document")
    assert hits, "body-only phrase returned nothing"
    assert all(h["match_kind"] in ("title", "content") for h in hits)
    content = [h for h in hits if h["match_kind"] == "content"]
    assert content and all("<<" in h["snippet"] and ">>" in h["snippet"] for h in content)


def test_title_hits_rank_before_content_hits(client):
    hits = _search(client, "Rejoinder", kind="document")
    kinds = [h["match_kind"] for h in hits]
    assert "title" in kinds
    assert kinds == sorted(kinds, key=lambda k: 0 if k == "title" else 1)


def test_many_matter_hits_do_not_push_documents_out(client):
    """'Security Council' matches 80+ matter titles and thousands of documents; both must show up."""
    hits = _search(client, "Security Council", limit=20)
    kinds = [h["kind"] for h in hits]
    assert len(hits) == 20
    assert kinds.count("document") >= 8 and kinds.count("matter") >= 1


def test_odd_input_never_errors(client):
    for q in ['"unbalanced (', "!!!", "and", "a", "'; DROP TABLE documents; --", "\\", "  spaced   out  "]:
        resp = client.get("/api/search", params={"q": q}, headers=as_member("MEM-00001"))
        assert resp.status_code == 200, (q, resp.text)


def test_blank_query_returns_nothing(client):
    assert _search(client, "   ") == []


def test_outsider_cannot_find_a_restricted_document_by_title_or_content(client, conn, walls):
    w = walls[0]
    doc = conn.execute("SELECT title FROM documents WHERE document_id = %s", (w.document_id,)).fetchone()
    chunk = conn.execute("SELECT text FROM chunks WHERE document_id = %s AND NOT COALESCE(is_parent, false) "
                         "ORDER BY chunk_index LIMIT 1", (w.document_id,)).fetchone()
    queries = [doc["title"][:60]]
    if chunk:
        words = sorted(set(re.findall(r"[A-Za-z]{9,}", chunk["text"])), key=len, reverse=True)
        queries += words[:2]
    for q in queries:
        inside = {h["id"] for h in _search(client, q, member=w.insider, kind="document", limit=50)}
        outside = {h["id"] for h in _search(client, q, member=w.outsider, kind="document", limit=50)}
        assert w.document_id not in outside, f"{q!r} leaked a restricted document"
        if q == queries[0]:
            assert w.document_id in inside
