"""Batch review: engine mechanics with a scripted model, and the benchmark's gold matching."""
from __future__ import annotations

import json

import pytest

from app.db.connection import connect
from app.review import batch
from evals.batch_review_eval import correct, gold_for, norm_date


def test_gold_is_read_only_when_unambiguous():
    body = "Resolution 212 (1965) of 20 September 1965 The Security Council ... Adopted unanimously at the 1243rd meeting"
    assert gold_for("Security Council resolution 212 (1965) [on the Maldives]", body) == {
        "number": "212", "meeting": "1243", "date": "1965-09-20"}
    assert gold_for("Security Council resolution 5 (1946)", body + " and at its 99th meeting") is None


def test_answer_matching_normalises_numbers_and_dates():
    assert correct("meeting", "the 3,549th meeting", "3549")
    assert correct("date", "Adopted on June 27, 2023", "2023-06-27")
    assert norm_date("1965-09-20") == "1965-09-20"
    assert not correct("number", "", "212")


def _fake_llm(calls: list):
    def call(messages):
        calls.append(1)
        body = messages[-1]["content"]
        first = body.split("PASSAGES:")[1].split("\n")[1]
        quote = " ".join(first.split("] ", 1)[1].split()[:6])
        return json.dumps({"answers": [{"q": 1, "answer": "x", "quote": quote, "passage": 1, "not_found": False},
                                       {"q": 2, "answer": "", "not_found": True}]})
    return call


@pytest.fixture(scope="module")
def some_docs(seeded):
    with connect() as conn:
        rows = conn.execute(
            "SELECT d.document_id FROM documents d JOIN permissions p USING (matter_id) WHERE NOT p.restricted"
            " AND EXISTS (SELECT 1 FROM chunks c WHERE c.document_id = d.document_id) ORDER BY d.document_id LIMIT 6"
        ).fetchall()
    return [r["document_id"] for r in rows]


def test_every_document_gets_one_call_and_verified_quotes(some_docs):
    calls: list = []
    with connect() as conn:
        out = batch.review_documents(conn, some_docs, ["q one?", "q two?"], None, llm=_fake_llm(calls), use_cache=False)
    assert len(calls) == len(some_docs) and [r["document_id"] for r in out["rows"]] == some_docs
    first = out["rows"][0]["cells"]
    assert first[0]["verified"] and first[1]["not_found"] and not first[1]["answer"]


def test_cached_rerun_makes_no_model_calls(some_docs):
    calls: list = []
    with connect() as conn:
        batch.review_documents(conn, some_docs, ["cache me?"], None, llm=_fake_llm(calls), use_cache=True)
        n = len(calls)
        again = batch.review_documents(conn, some_docs, ["cache me?"], None, llm=_fake_llm(calls), use_cache=True)
    if again["stats"]["cached"] == 0:
        pytest.skip("Redis not available")
    assert len(calls) == n and again["stats"]["cached"] == len(some_docs)


def test_one_failing_document_does_not_sink_the_batch(some_docs):
    def flaky(messages):
        if "PASSAGES" in messages[-1]["content"] and flaky.n == 0:
            flaky.n += 1
            raise RuntimeError("boom")
        return json.dumps({"answers": [{"q": 1, "not_found": True}]})
    flaky.n = 0
    with connect() as conn:
        out = batch.review_documents(conn, some_docs, ["q?"], None, llm=flaky, use_cache=False, concurrency=1)
    assert out["stats"]["errors"] == 1 and len(out["rows"]) == len(some_docs)


def test_restricted_documents_are_dropped_for_outsiders(walls):
    w = walls[0]
    with connect() as conn:
        out = batch.review_documents(conn, [w.document_id], ["q?"], w.outsider, llm=_fake_llm([]), use_cache=False)
    assert out["rows"] == [] and out["documents"] == 0


def test_batch_route_uses_the_signed_in_member(client, walls):
    from tests.conftest import as_member

    w = walls[0]
    r = client.post("/api/reviews/batch", json={"document_ids": [w.document_id], "questions": ["q?"], "mode": "screen"},
                    headers=as_member(w.outsider))
    assert r.status_code == 200 and r.json()["rows"] == []


def test_review_run_ignores_member_id_in_the_body(client, walls, monkeypatch):
    """The legacy review route must use the signed-in member, never one named in the request."""
    from app.api.routers import reviews
    from tests.conftest import as_member

    seen = {}

    async def fake_run_review(**kwargs):
        seen.update(kwargs)

        class _R:
            def to_dict(self):
                return {}
        return _R()

    monkeypatch.setattr(reviews.review_engine, "run_review", fake_run_review)
    w = walls[0]
    client.post("/api/reviews/run", json={"document_ids": [w.document_id], "member_id": w.insider},
                headers=as_member(w.outsider))
    assert seen["member_id"] == w.outsider
