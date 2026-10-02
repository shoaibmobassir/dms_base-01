"""Legal research over the firm's held authorities, against the seeded database.

Encodes the design-doc research tests (§22.16) that R1-local must pass.
"""
from __future__ import annotations

import pytest

from app.chat.agent import dispatch_tool_call
from app.chat.spotlight import generate_nonce
from app.db.connection import connect
from app.research import local_provider as lp
from app.research.citations import parse_citation
from app.research.legal_systems import Forum
from app.research.verify import verify_citations

MEMBER = "MEM-00001"


@pytest.fixture(scope="module")
def conn(seeded):
    with connect() as c:
        held = c.execute("SELECT count(*) AS n FROM documents WHERE document_type = 'Security Council Resolution'").fetchone()
        if not held or not held["n"]:
            pytest.skip("authority corpus (UNSC/PCIJ) not loaded")
        yield c


def _verify(conn, text):
    return {r["citation"]: r for r in verify_citations(conn, text, MEMBER, forum=Forum("international"))["citations"]}


def test_resolve_existing_wrong_year_and_missing(conn):
    ok = lp.resolve(conn, parse_citation("S/RES/1373 (2001)"), MEMBER)
    assert ok["resolution"] == "resolved" and ok["authorities"][0]["citation"]["number"] == 1373
    wrong_year = lp.resolve(conn, parse_citation("S/RES/1373 (2003)"), MEMBER)
    assert wrong_year["resolution"] == "not_found" and "2001" in wrong_year["reason"]
    assert lp.resolve(conn, parse_citation("S/RES/9999 (2030)"), MEMBER)["resolution"] == "not_found"


def test_unheld_collections_are_never_verified(conn):
    for cite in ("(2008) 4 SCC 755", "I.C.J. Reports 1986, p. 14", "467 U.S. 837"):
        res = lp.resolve(conn, parse_citation(cite), MEMBER)
        assert res["resolution"] == "not_held" and "not verified" in res["reason"]


def test_pcij_principal_decision_first_then_opinions(conn):
    res = lp.resolve(conn, parse_citation("P.C.I.J., Series A/B, No. 63"), MEMBER)
    roles = [a["role"] for a in res["authorities"]]
    assert roles[0] == "majority" and {"dissent", "separate_opinion"} <= set(roles)
    wimbledon = lp.resolve(conn, parse_citation("PCIJ Series A No. 1"), MEMBER)["authorities"][0]
    assert wimbledon["decision_date"] == "1923-08-17"  # the merits judgment, not the intervention judgment


def test_r1_fabricated_citation_not_verified(conn):
    rows = _verify(conn, "As decided in S/RES/1373 (2003), all States shall act.")
    assert rows["S/RES/1373 (2003)"]["verdict"] == "not_verified"


def test_r2_quote_not_in_authority(conn):
    rows = _verify(conn, 'The Council said "all States shall immediately annex neighbouring territory" (S/RES/1373 (2001)).')
    row = rows["S/RES/1373 (2001)"]
    assert row["quote_found"] is False and row["verdict"] == "verified_with_caution"


def test_r3_expired_mandate_disclosed(conn):
    st = lp.status(conn, lp.resolve(conn, parse_citation("S/RES/2813 (2026)"), MEMBER)["authorities"][0]["authority_id"],
                   MEMBER, as_of="2026-10-02")
    assert st["status"]["signal"] == "expired" and st["status"]["source"] == "derived"
    assert st["status"]["signal"] != "good_law"


def test_r11_wrong_pinpoints_flagged(conn):
    rows = _verify(conn, "S/RES/1373 (2001), para. 40. PCIJ Series A No. 1, p. 400. PCIJ Series A No. 1, p. 12.")
    assert rows["S/RES/1373 (2001), para. 40"]["issues"]
    assert rows["PCIJ Series A No. 1, p. 400"]["issues"]
    assert rows["PCIJ Series A No. 1, p. 12"]["verdict"] == "verified"


def test_r12_dissent_quoted_as_holding_is_flagged(conn):
    rows = _verify(conn, 'The Court held that "I regret that I cannot concur either in the decision reached in the '
                         'foregoing judgment" (P.C.I.J., Series A/B, No. 63).')
    row = rows["P.C.I.J., Series A/B, No. 63"]
    assert row["quote_found"] is True
    assert any("dissent" in issue for issue in row["issues"])
    assert row["binding"]["label"] == "not_binding"


def test_r14_r15_operative_paragraph_labels(conn):
    rows = _verify(conn, "S/RES/1373 (2001), para. 1 and S/RES/1373 (2001), para. 3 and S/RES/678 (1990), para. 2")
    assert rows["S/RES/1373 (2001), para. 1"]["binding"]["label"] == "binding"         # decides, Chapter VII
    assert rows["S/RES/1373 (2001), para. 3"]["binding"]["label"] == "recommendatory"  # calls upon
    assert rows["S/RES/678 (1990), para. 2"]["binding"]["label"] == "not_binding"       # authorizes


def test_search_returns_typed_authorities_only(conn):
    hits = lp.search(conn, "reparation for breach of an engagement", MEMBER, limit=5)
    assert hits and all(h["authority_id"].startswith("local:") for h in hits)
    assert all(h["binding"]["label"] and h["binding"]["reason"] for h in hits)
    assert any("Chorzow" in h["citation"] for h in hits)


def test_citing_ignores_editorial_summaries(conn):
    aid = lp.resolve(conn, parse_citation("S/RES/1718 (2006)"), MEMBER)["authorities"][0]["authority_id"]
    cites = lp.citing(conn, aid, MEMBER, limit=10)["citing"]
    assert cites and all(c["in"] != "headnote" for c in cites)
    assert all(c["treatment_source"] == "derived" for c in cites)


def test_read_authority_stores_paged_text_without_headnote(conn):
    idx, store, nonce = {}, {}, generate_nonce()
    res, events = dispatch_tool_call("read_authority", {"authority": "S/RES/1373 (2001)", "paras": "1-3"},
                                     idx, store, conn, nonce, member_id=MEMBER)
    assert [p["para"] for p in res["operative_paragraphs"]] == ["1", "2", "3"]
    assert store[res["doc_id"]].startswith("[Page 1]\n[Editorial summary omitted")
    assert events[0]["type"] == "authority_read"
    pcij, _ = dispatch_tool_call("read_authority", {"authority": "Series A/B No. 63", "pages": "2"},
                                 idx, store, conn, nonce, member_id=MEMBER)
    assert pcij["role"] == "majority" and "[Page 2]" in store[pcij["doc_id"]]


def test_acl_negative_authority_hidden_from_outsider(conn):
    """A member outside a restricted matter must not search, read or resolve its authorities."""
    row = conn.execute("""SELECT d.matter_id FROM documents d WHERE d.document_type = 'Judgment'
                          ORDER BY d.document_id LIMIT 1""").fetchone()
    matter_id = row["matter_id"]
    try:
        conn.execute("UPDATE permissions SET restricted = true, allowed_members = '{MEM-00002}' WHERE matter_id = %s",
                     (matter_id,))
        title = conn.execute("SELECT title FROM matters WHERE matter_id = %s", (matter_id,)).fetchone()["title"]
        cite = "PCIJ " + title.split("PCIJ ", 1)[1].replace("Series AB", "Series A/B")
        assert lp.resolve(conn, parse_citation(cite), "MEM-00002")["resolution"] == "resolved"
        assert lp.resolve(conn, parse_citation(cite), MEMBER)["resolution"] == "not_found"
        docs = [r["document_id"] for r in conn.execute("SELECT document_id FROM documents WHERE matter_id = %s", (matter_id,))]
        assert all(lp.get(conn, d, MEMBER) is None for d in docs)
        hits = lp.search(conn, title.split(" — ")[0], MEMBER, limit=12)
        assert not {h["document_id"] for h in hits} & set(docs)
    finally:
        conn.rollback()
