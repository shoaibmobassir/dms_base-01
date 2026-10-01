"""Ask the Firm (app.km) against the seeded database.

Expected values are read from Postgres, never hard-coded, so these check the
pipeline's behaviour rather than one corpus. The LLM is stubbed wherever the
assertion is about evidence gathering, scope, ACL or fallbacks; the live
answer quality is measured by evals/km_live_eval.py.
"""
from __future__ import annotations

import re
import threading
import time

import pytest

from app.answers.citations import extract_document_ids
from app.db.connection import connect
from app.km import answer as km_answer
from app.km import directory
from app.km.answer import ask_the_firm
from app.km.intent import classify
from app.km.resolver import resolve_matter
from app.km.scope import resolve_scope
from app.query.understand import understand
from tests.conftest import as_member

ACME = "CORP/BLR/0901/2026"


def _one(sql: str, params: tuple = ()):
    with connect() as conn:
        return conn.execute(sql, params).fetchone()


@pytest.fixture(scope="module")
def staffed_matter(seeded):
    """An unrestricted matter with a lead, facts and documents."""
    row = _one(
        """
        SELECT m.matter_id, m.matter_code, m.title, cl.name AS client_name
        FROM matters m JOIN clients cl USING (client_id) JOIN permissions p USING (matter_id)
        WHERE NOT p.restricted AND cardinality(m.facts) > 0
          AND EXISTS (SELECT 1 FROM matter_members mm WHERE mm.matter_id = m.matter_id AND mm.role_on_matter = 'Lead')
          AND EXISTS (SELECT 1 FROM documents d WHERE d.matter_id = m.matter_id)
        ORDER BY m.matter_id LIMIT 1
        """
    )
    if not row:
        pytest.skip("no staffed matter with facts")
    return row


@pytest.fixture(scope="module")
def acme(seeded):
    row = _one("SELECT matter_id FROM matters WHERE matter_code = %s", (ACME,))
    if not row:
        pytest.skip("Acme demo matter not seeded (scripts/seed_acme.py)")
    return row["matter_id"]


@pytest.fixture
def no_llm(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("llm disabled in test")

    monkeypatch.setattr(km_answer, "_llm", _boom)


# ── identifiers ──────────────────────────────────────────────────────────────

def test_hex_document_ids_are_extracted():
    assert extract_document_ids("see (DOC-E9058749C1) and DOC-00071") == ["DOC-E9058749C1", "DOC-00071"]


def test_four_letter_matter_codes_parse():
    assert understand(f"{ACME}: explain this").matter_codes == [ACME]


def test_intent_flags():
    assert classify("who is working on this matter?").people
    assert not classify("who was the other side in this matter?").people
    assert classify("explain this", scoped=True).overview
    assert classify("which matters have we handled for France?").matter_list


# ── scope ────────────────────────────────────────────────────────────────────

def test_structured_prefix_and_inline_scope_agree(staffed_matter):
    code, mid = staffed_matter["matter_code"], staffed_matter["matter_id"]
    with connect() as conn:
        structured = resolve_scope(conn, "explain this", {"type": "matter", "value": code}, None)
        prefixed = resolve_scope(conn, f"{code}: explain this", None, None)
        inline = resolve_scope(conn, f"what happened in {code}?", None, None)
    assert structured.matter_ids == prefixed.matter_ids == inline.matter_ids == [mid]
    assert prefixed.question == "explain this"


def test_prefix_that_is_not_a_scope_is_left_alone():
    with connect() as conn:
        res = resolve_scope(conn, "Note: what did we argue about jurisdiction?", None, None)
    assert res.matters == [] and res.question.startswith("Note:")


def test_client_scope_lists_every_client_matter(staffed_matter):
    client = staffed_matter["client_name"]
    expected = {r["matter_id"] for r in _all(
        "SELECT m.matter_id FROM matters m JOIN clients cl USING (client_id) JOIN permissions p USING (matter_id)"
        " WHERE cl.name = %s AND NOT p.restricted", (client,))}
    with connect() as conn:
        res = resolve_scope(conn, "what have we done?", {"type": "client", "value": client}, None)
    assert res.kind == "client" and expected <= set(res.matter_ids)


def _all(sql: str, params: tuple = ()):
    with connect() as conn:
        return conn.execute(sql, params).fetchall()


# ── evidence ─────────────────────────────────────────────────────────────────

def test_scoped_fact_passage_reaches_the_evidence(acme, no_llm):
    """The screenshot bug: a scoped fact question must surface the clause, not headings."""
    with connect() as conn:
        out = ask_the_firm(conn, "what is the long stop date?", "MEM-00007", {"type": "matter", "value": ACME})
    texts = " ".join(h["text"] for h in out["hits"])
    assert "Long Stop Date" in texts
    assert all(len(h["text"].strip()) >= 60 for h in out["hits"]), "heading-only chunks leaked into evidence"
    assert out["provider"] == "records" and out["answer"], "LLM failure must degrade to a records answer"


def test_team_question_uses_staffing_records(staffed_matter, no_llm):
    team = {r["name"] for r in _all(
        "SELECT mb.name FROM matter_members mm JOIN members mb USING (member_id) WHERE mm.matter_id = %s",
        (staffed_matter["matter_id"],))}
    with connect() as conn:
        out = ask_the_firm(conn, "who is working on this matter?", None,
                           {"type": "matter", "value": staffed_matter["matter_code"]})
    assert {t["name"] for t in out["matter_cards"][0]["team"]} == team
    assert all(name in out["answer"] for name in team)


def test_people_search_ranks_the_specialist(seeded):
    row = _one("SELECT member_id, specializations[1] AS spec FROM members WHERE cardinality(specializations) > 0 ORDER BY member_id LIMIT 1")
    with connect() as conn:
        people = directory.people_search(conn, f"who is an expert in {row['spec'].lower()}?", None)
    assert people and people[0]["member_id"] == row["member_id"]


# ── resolver ─────────────────────────────────────────────────────────────────

def test_lowercase_paraphrase_resolves(acme):
    with connect() as conn:
        res = resolve_matter(conn, "the series b deal where a seed investor sold its preference shares to a growth fund", None)
    assert [c["matter_id"] for c in res.resolved] == [acme]


def test_verbatim_title_beats_longer_sibling(staffed_matter):
    title = staffed_matter["title"]
    with connect() as conn:
        res = resolve_matter(conn, f"who led our work on {title}?", None)
    assert res.resolved and res.resolved[0]["matter_id"] == staffed_matter["matter_id"]


@pytest.mark.parametrize("question", [
    "what did we advise Zephyrine Robotics on in its dispute with Obelisk Bank?",
    "the arbitration between Norland Shipping and Kestrel Insurance over a sunk tanker",
])
def test_unknown_matters_do_not_resolve(seeded, question):
    with connect() as conn:
        assert resolve_matter(conn, question, None).resolved == []


# ── ethical walls ────────────────────────────────────────────────────────────

def test_restricted_matter_never_resolves_for_outsider(walls):
    w = walls[0]
    with connect() as conn:
        scoped = resolve_scope(conn, "explain this", {"type": "matter", "value": w.matter_code}, w.outsider)
        described = resolve_matter(conn, f"summarise {w.title}", w.outsider)
        people = directory.people_search(conn, "who worked on matters", w.outsider, limit=50)
    assert scoped.unresolved and not scoped.matters
    assert w.matter_id not in {c["matter_id"] for c in described.candidates}
    assert w.matter_id not in {m["matter_id"] for p in people for m in p["matters"]}


def test_restricted_matter_resolves_for_insider(walls):
    w = walls[0]
    with connect() as conn:
        scoped = resolve_scope(conn, "explain this", {"type": "matter", "value": w.matter_code}, w.insider)
    assert scoped.matter_ids == [w.matter_id]


# ── HTTP contract ────────────────────────────────────────────────────────────

def test_api_structured_scope_contract(client, staffed_matter, no_llm):
    body = {"query": "explain this", "scope": {"type": "matter", "value": staffed_matter["matter_code"]}}
    r = client.post("/api/answers", json=body, headers=as_member("MEM-00011"))
    assert r.status_code == 200
    out = r.json()
    assert out["resolved_scope"]["matter_ids"] == [staffed_matter["matter_id"]]
    assert out["matchedMatters"][0]["matter_id"] == staffed_matter["matter_id"]
    assert out["answer"] and not out["abstained"]
    for key in ("key_finding", "sources", "hits", "people", "matter_cards", "latency_ms"):
        assert key in out


def test_api_unknown_scope_is_explicit(client, no_llm):
    body = {"query": "explain this", "scope": {"type": "matter", "value": "ZZZ/NOPE/0000/0000"}}
    out = client.post("/api/answers", json=body, headers=as_member("MEM-00011")).json()
    assert out["abstained"] and out["reason"] == "scope_not_found"


def test_api_rejects_empty_scope_value(client):
    r = client.post("/api/answers", json={"query": "x", "scope": {"type": "matter", "value": ""}},
                    headers=as_member("MEM-00011"))
    assert r.status_code == 422


# ── concurrency / pool regression ────────────────────────────────────────────

def test_concurrent_retrieval_does_not_stall(seeded):
    """Before per-loop pools, concurrent sync retrievals stranded connections and
    later channels waited the 30 s pool timeout. Every call must finish promptly
    with no channel timeouts."""
    from app.db.pool import pool_stats
    from app.retrieval.engine import retrieve

    errors: list[str] = []
    slow: list[float] = []

    def worker(i: int) -> None:
        try:
            with connect() as conn:
                t0 = time.perf_counter()
                _hits, lat = retrieve(conn, f"permanent court jurisdiction treaty {i} {time.time_ns()}", None, k=5)
                slow.append(time.perf_counter() - t0)
                if lat.get("channel_timeouts"):
                    errors.append(f"timeouts {lat['channel_timeouts']}")
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(120)
    assert not errors, errors
    assert max(slow) < 25, f"slowest retrieval {max(slow):.1f}s"
    assert pool_stats().get("requests_errors", 0) == 0


def test_evidence_ids_in_answers_are_validated():
    payload = {"status": "answered", "answer": "Closing is due (DOC-E9058749C1) per DOC-99999999ZZ.", "citations": ["DOC-E9058749C1", "MEM-99999"]}
    out = km_answer._validate(payload, {"DOC-E9058749C1"})
    assert out["citations"] == ["DOC-E9058749C1"]
    assert not re.search(r"MEM-99999", " ".join(out["citations"]))
