"""Sorting and the "mine" filter on the matters and documents lists."""
from __future__ import annotations

from app.api.sorting import order_by
from tests.conftest import as_member

ME = "MEM-00001"
COLS = {"a": "x.a", "b": "lower(x.b)"}


def test_order_by_is_whitelisted_and_stable():
    assert order_by("b", "asc", COLS, "a", "x.id") == "ORDER BY lower(x.b) ASC NULLS LAST, x.id ASC"
    assert order_by("b; DROP TABLE x", "desc", COLS, "a", "x.id") == "ORDER BY x.a DESC NULLS LAST, x.id DESC"
    assert order_by(None, None, COLS, "a", "x.id").endswith("x.id DESC")


def test_matters_sort_by_title_both_ways(client, seeded):
    asc = client.get("/api/matters?limit=200&sort=title&dir=asc", headers=as_member(ME)).json()
    desc = client.get("/api/matters?limit=200&sort=title&dir=desc", headers=as_member(ME)).json()
    assert asc["total"] == desc["total"]
    if asc["total"] <= 200:
        # The database's own collation decides the order; the two directions must mirror each other.
        assert [m["matter_id"] for m in asc["items"]] == [m["matter_id"] for m in desc["items"]][::-1]


def test_matters_sort_rejects_a_bad_direction(client, seeded):
    assert client.get("/api/matters?sort=title&dir=sideways", headers=as_member(ME)).status_code == 422


def test_unknown_matter_sort_falls_back_to_newest(client, seeded):
    a = client.get("/api/matters?limit=10&sort=nope", headers=as_member(ME)).json()["items"]
    b = client.get("/api/matters?limit=10", headers=as_member(ME)).json()["items"]
    assert [m["matter_id"] for m in a] == [m["matter_id"] for m in b]


def test_mine_only_returns_matters_the_caller_is_staffed_on(client, seeded):
    mine = client.get("/api/matters?limit=200&mine=true", headers=as_member(ME)).json()
    everyone = client.get("/api/matters?limit=200", headers=as_member(ME)).json()
    assert mine["total"] <= everyone["total"]
    for m in mine["items"]:
        team = client.get(f"/api/matters/{m['matter_id']}", headers=as_member(ME)).json()["team"]
        assert ME in {t["member_id"] for t in team}


def test_documents_sort_by_title_both_ways(client, seeded):
    asc = client.get("/api/documents?limit=200&sort=title&dir=asc", headers=as_member(ME)).json()
    desc = client.get("/api/documents?limit=200&sort=title&dir=desc", headers=as_member(ME)).json()
    assert asc["total"] == desc["total"]
    if asc["total"] <= 200:
        assert [d["document_id"] for d in asc["items"]] == [d["document_id"] for d in desc["items"]][::-1]
