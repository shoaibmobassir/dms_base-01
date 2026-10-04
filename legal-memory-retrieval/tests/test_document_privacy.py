"""Document privacy (plan 17, P1b): a wall matrix across every surface that reads documents,
plus regressions for the unchecked paths closed in the same sweep. Real API, real database.
"""
from __future__ import annotations

import uuid

import pytest

from app import access
from app.db.connection import connect
from tests.conftest import as_member

TOKEN = f"Quillonberry{uuid.uuid4().hex[:6]}"
BODY = (f"Side letter on the {TOKEN} arrangement. The parties agree that the {TOKEN} payment schedule "
        "stays confidential and that no disclosure is made to the wider deal team before signing.")


def _rows(sql: str, params=()) -> list[dict]:
    with connect() as conn:
        return list(conn.execute(sql, params).fetchall())


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    from app.km import answer as km_answer

    monkeypatch.setattr(km_answer, "_llm", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm in tests")))


@pytest.fixture(scope="module")
def cast(seeded):
    """An open matter with a lead and another fee earner (the author), three firm members
    outside the team, and a risk officer with walls.manage."""
    with connect() as conn:
        wallers = {r["member_id"] for r in conn.execute(
            "SELECT DISTINCT mr.member_id FROM member_roles mr JOIN role_permissions rp USING (role_key) "
            "WHERE rp.permission = 'walls.manage'")}
        admins = wallers | {r["member_id"] for r in conn.execute(
            "SELECT member_id FROM member_roles WHERE role_key IN ('firm_admin', 'risk_compliance')")}
        everyone = [r["member_id"] for r in conn.execute("SELECT member_id FROM members ORDER BY member_id")]
        for m in conn.execute(
                """SELECT m.matter_id, m.matter_code FROM matters m JOIN matter_access a USING (matter_id)
                   WHERE a.mode = 'open' ORDER BY m.matter_id""").fetchall():
            team = conn.execute("SELECT member_id, lower(coalesce(role_on_matter, '')) AS role FROM matter_members "
                                "WHERE matter_id = %s AND ended_at IS NULL", (m["matter_id"],)).fetchall()
            leads = [t["member_id"] for t in team if t["role"] == "lead" and t["member_id"] not in admins]
            staff = [t["member_id"] for t in team if t["role"] != "lead" and t["member_id"] not in admins]
            members = {t["member_id"] for t in team}
            outsiders = [x for x in everyone if x not in members and x not in admins]
            if leads and staff and len(outsiders) >= 3 and wallers:
                auditor = sorted(wallers - members)[0] if wallers - members else None
                if auditor:
                    return {"matter_id": m["matter_id"], "matter_code": m["matter_code"], "lead": leads[0],
                            "author": staff[0], "shared": outsiders[0], "via_team": outsiders[1],
                            "stranger": outsiders[2], "auditor": auditor}
    pytest.skip("no open matter with a lead, staff, three outsiders and an auditor")


@pytest.fixture
def team(cast):
    """A throwaway team holding one outsider (to share with)."""
    team_id = f"TEAM-T{uuid.uuid4().hex[:8].upper()}"
    with connect() as conn:
        conn.execute("INSERT INTO teams (team_id, name) VALUES (%s, %s)", (team_id, f"Privacy test {team_id}"))
        conn.execute("INSERT INTO team_members (team_id, member_id) VALUES (%s, %s)", (team_id, cast["via_team"]))
        conn.commit()
    yield team_id
    with connect() as conn:
        conn.execute("DELETE FROM document_shares WHERE principal_type = 'team' AND principal_id = %s", (team_id,))
        conn.execute("DELETE FROM teams WHERE team_id = %s", (team_id,))
        conn.commit()


@pytest.fixture
def doc(client, cast, document_cleanup):
    """A document written by the fee earner, found by its unusual words."""
    r = client.post("/api/documents/ingest", headers=as_member(cast["author"]), json={
        "title": f"{TOKEN} side letter", "matter_id": cast["matter_id"], "body": BODY, "document_type": "Letter"})
    assert r.status_code == 200, r.text
    doc_id = r.json()["document_id"]
    document_cleanup.append(doc_id)
    yield doc_id
    from app.documents.editing import wait_for_indexing

    wait_for_indexing()


def _privacy(client, doc_id, member, visibility, shares=(), row_version=None):
    return client.put(f"/api/editor/documents/{doc_id}/privacy", headers=as_member(member),
                      json={"visibility": visibility, "shares": list(shares), "row_version": row_version})


def _reach(client, cast, doc_id: str, member: str) -> dict[str, bool]:
    """Every surface that can reveal the document, for one person."""
    h = as_member(member)
    mid = cast["matter_id"]
    chunk_id = _rows("SELECT chunk_id FROM chunks WHERE document_id = %s ORDER BY chunk_index LIMIT 1", (doc_id,))[0]["chunk_id"]
    listed = client.get("/api/documents", params={"q": TOKEN}, headers=h).json().get("items", [])
    search = client.get("/api/search", params={"q": TOKEN}, headers=h).json().get("results", [])
    hits = client.post("/api/retrieval", json={"query": f"{TOKEN} payment schedule side letter", "k": 20}, headers=h).json()
    hits = hits.get("hits") or hits.get("results") or []
    matter = client.get(f"/api/matters/{mid}", headers=h).json()
    timeline = client.get(f"/api/matters/{mid}/timeline", headers=h).json().get("timeline", [])
    with connect() as conn:
        from app.chat.tools.document_tools import DocEntry, resolve_document_text
        from app.km.directory import matter_cards
        from app.km.passages import scoped_passages
        from app.review.batch import resolve_documents

        cards = matter_cards(conn, [mid], member)
        passages = scoped_passages(conn, f"{TOKEN} payment schedule", [mid], member)
        reviewable = resolve_documents(conn, [doc_id], member, 10)
        assistant = resolve_document_text(DocEntry("D1", doc_id, "x"), {}, conn, member)
    return {
        "document": client.get(f"/api/documents/{doc_id}", headers=h).status_code == 200,
        "text": client.get(f"/api/documents/{doc_id}/text", headers=h).status_code == 200,
        "versions": client.get(f"/api/documents/{doc_id}/versions", headers=h).status_code == 200,
        "chunks": client.get(f"/api/documents/{doc_id}/chunks", headers=h).status_code == 200,
        "chunk_context": client.get(f"/api/documents/chunks/{chunk_id}/context", headers=h).status_code == 200,
        "editor": client.get(f"/api/editor/documents/{doc_id}", headers=h).status_code == 200,
        "comments": client.get(f"/api/editor/documents/{doc_id}/comments", headers=h).status_code == 200,
        "list": any(d["document_id"] == doc_id for d in listed),
        "search": any(r.get("id") == doc_id for r in search),
        "retrieval": any(x.get("document_id") == doc_id for x in hits),
        "matter_page": any(d["document_id"] == doc_id for d in matter.get("documents", [])),
        "timeline": any(t["doc_id"] == doc_id for t in timeline),
        "ask_cards": any(d["document_id"] == doc_id for c in cards for d in c.get("documents") or []),
        "ask_passages": any(p["document_id"] == doc_id for p in passages),
        "review": any(d["document_id"] == doc_id for d in reviewable),
        "assistant": TOKEN in assistant,
    }


def _all(reach: dict[str, bool]) -> bool:
    assert all(reach.values()), f"not reachable: {sorted(k for k, v in reach.items() if not v)}"
    return True


def _none(reach: dict[str, bool]) -> bool:
    assert not any(reach.values()), f"leaked through: {sorted(k for k, v in reach.items() if v)}"
    return True


def test_a_normal_document_follows_its_matter(client, cast, doc):
    for who in ("author", "lead", "stranger"):
        r = _reach(client, cast, doc, cast[who])
        assert _all(r), (who, r)


def test_private_document_wall_matrix(client, cast, doc, team):
    r = _privacy(client, doc, cast["author"], "private", [
        {"principal_type": "member", "principal_id": cast["shared"]},
        {"principal_type": "team", "principal_id": team},
    ])
    assert r.status_code == 200, r.text
    assert r.json()["visibility"] == "private" and r.json()["owner"]["member_id"] == cast["author"]
    for who in ("author", "shared", "via_team", "auditor"):
        reach = _reach(client, cast, doc, cast[who])
        assert _all(reach), (who, reach)
    for who in ("lead", "stranger"):  # private: even the matter lead is out
        reach = _reach(client, cast, doc, cast[who])
        assert _none(reach), (who, reach)


def test_restricted_document_lets_matter_managers_in(client, cast, doc):
    assert _privacy(client, doc, cast["author"], "restricted").status_code == 200
    assert _all(_reach(client, cast, doc, cast["lead"]))
    assert _all(_reach(client, cast, doc, cast["author"]))
    assert _none(_reach(client, cast, doc, cast["stranger"]))


def test_auditor_reads_are_audited(client, cast, doc):
    assert _privacy(client, doc, cast["author"], "private").status_code == 200
    before = _rows("SELECT count(*) AS n FROM audit_events WHERE action = 'document.privileged_read' AND object_id = %s", (doc,))[0]["n"]
    assert client.get(f"/api/documents/{doc}/text", headers=as_member(cast["auditor"])).status_code == 200
    assert client.get(f"/api/editor/documents/{doc}", headers=as_member(cast["auditor"])).status_code == 200
    after = _rows("SELECT count(*) AS n FROM audit_events WHERE action = 'document.privileged_read' AND object_id = %s", (doc,))[0]["n"]
    assert after >= before + 2
    # ...but they only read: no editing, no changing who sees it.
    assert client.post(f"/api/editor/documents/{doc}/lock", headers=as_member(cast["auditor"])).status_code == 403
    assert _privacy(client, doc, cast["auditor"], "matter").status_code == 403
    # The owner's own reads are not "privileged".
    client.get(f"/api/documents/{doc}/text", headers=as_member(cast["author"]))
    assert _rows("SELECT count(*) AS n FROM audit_events WHERE action = 'document.privileged_read' AND object_id = %s "
                 "AND member_id = %s", (doc, cast["author"]))[0]["n"] == 0


def test_who_may_change_privacy(client, cast, doc):
    # A fee earner who did not write it cannot make someone else's document private.
    assert _privacy(client, doc, cast["stranger"], "private").status_code in (403, 404)
    r = _privacy(client, doc, cast["author"], "private", [{"principal_type": "member", "principal_id": cast["shared"]}])
    version = r.json()["row_version"]
    # Private: only the owner — not the lead, not someone it is shared with.
    assert _privacy(client, doc, cast["lead"], "matter").status_code in (403, 404)
    assert _privacy(client, doc, cast["shared"], "matter", row_version=version).status_code == 403
    # Optimistic concurrency.
    assert _privacy(client, doc, cast["author"], "restricted", row_version=version + 5).status_code == 409
    r = _privacy(client, doc, cast["author"], "restricted", row_version=version)
    assert r.status_code == 200 and r.json()["visibility"] == "restricted"
    # Restricted: a matter manager may change it back.
    r = _privacy(client, doc, cast["lead"], "matter", row_version=r.json()["row_version"])
    assert r.status_code == 200 and r.json()["visibility"] == "matter"
    assert _all(_reach(client, cast, doc, cast["stranger"]))
    assert _rows("SELECT count(*) AS n FROM audit_events WHERE action = 'document.privacy.change' AND object_id = %s", (doc,))[0]["n"] >= 3


def test_shares_are_validated(client, cast, doc):
    assert _privacy(client, doc, cast["author"], "private",
                    [{"principal_type": "member", "principal_id": "MEM-NOPE"}]).status_code == 422
    assert _privacy(client, doc, cast["author"], "private",
                    [{"principal_type": "team", "principal_id": "TEAM-NOPE"}]).status_code == 422


def test_team_membership_changes_follow_through(client, cast, doc, team):
    _privacy(client, doc, cast["author"], "private", [{"principal_type": "team", "principal_id": team}])
    assert _reach(client, cast, doc, cast["via_team"])["text"]
    with connect() as conn:
        conn.execute("DELETE FROM team_members WHERE team_id = %s AND member_id = %s", (team, cast["via_team"]))
        conn.commit()
    assert _none(_reach(client, cast, doc, cast["via_team"]))


def test_new_versions_of_a_private_document_stay_private(client, cast, doc):
    _privacy(client, doc, cast["author"], "private")
    r = client.post(f"/api/editor/documents/{doc}/versions", headers=as_member(cast["author"]),
                    files={"file": ("v2.txt", f"Revised {TOKEN} side letter with a new payment schedule.".encode(), "text/plain")})
    assert r.status_code == 201, r.text
    assert _rows("SELECT count(*) AS n FROM chunks WHERE document_id = %s AND visible_to IS NULL", (doc,))[0]["n"] == 0
    assert _none(_reach(client, cast, doc, cast["stranger"]))


def test_private_upload(client, cast, document_cleanup):
    r = client.post("/api/documents/ingest", headers=as_member(cast["author"]), json={
        "title": f"{TOKEN} private note", "matter_id": cast["matter_id"], "body": BODY, "document_type": "Note",
        "visibility": "private"})
    assert r.status_code == 200, r.text
    doc = r.json()["document_id"]
    document_cleanup.append(doc)
    assert r.json()["visibility"] == "private"
    assert _rows("SELECT count(*) AS n FROM chunks WHERE document_id = %s AND visible_to IS NULL", (doc,))[0]["n"] == 0
    assert client.get(f"/api/documents/{doc}/text", headers=as_member(cast["author"])).status_code == 200
    assert client.get(f"/api/documents/{doc}/text", headers=as_member(cast["stranger"])).status_code == 404


def test_privacy_changes_move_the_cache_epoch(client, cast, doc):
    from app.api.acl import acl_epoch

    before = acl_epoch()
    _privacy(client, doc, cast["author"], "private")
    assert acl_epoch() != before


# ── holes closed in the same sweep ───────────────────────────────────────────

def test_chunk_context_respects_the_wall(client, walls):
    w = walls[0]
    chunk = _rows("SELECT chunk_id FROM chunks WHERE document_id = %s LIMIT 1", (w.document_id,))
    if not chunk:
        pytest.skip("restricted document has no chunks")
    url = f"/api/documents/chunks/{chunk[0]['chunk_id']}/context"
    assert client.get(url, headers=as_member(w.outsider)).status_code == 404
    assert client.get(url, headers=as_member(w.insider)).status_code == 200


def test_review_jobs_and_findings_respect_the_wall(client, walls):
    w = walls[0]
    job_id = f"REV-T{uuid.uuid4().hex[:8].upper()}"
    with connect() as conn:
        conn.execute("""INSERT INTO review_jobs (job_id, matter_id, title, features_requested, target_document_ids, status,
                            total_documents, relevant_documents_count, findings_count, duration_ms, created_by)
                        VALUES (%s, %s, 'wall test', '{}', %s, 'completed', 1, 1, 0, 1, %s)""",
                     (job_id, w.matter_id, [w.document_id], w.insider))
        conn.commit()
    try:
        assert client.get(f"/api/reviews/{job_id}", headers=as_member(w.outsider)).status_code == 404
        assert client.get(f"/api/reviews/{job_id}/findings", headers=as_member(w.outsider)).status_code == 404
        assert client.get(f"/api/reviews/{job_id}", headers=as_member(w.insider)).status_code == 200
    finally:
        with connect() as conn:
            conn.execute("DELETE FROM review_jobs WHERE job_id = %s", (job_id,))
            conn.commit()


def test_review_run_skips_documents_outside_access(walls):
    from app.review import review_engine

    w = walls[0]
    assert review_engine._fetch_candidate_documents(None, [w.document_id], w.outsider) == []
    assert [d["document_id"] for d in review_engine._fetch_candidate_documents(None, [w.document_id], w.insider)] == [w.document_id]


def test_tabular_reviews_run_as_the_session_member_and_are_private(client, walls):
    w = walls[0]
    r = client.post("/api/tabular/reviews", headers=as_member(w.outsider), json={
        "title": "wall test", "document_ids": [w.document_id], "columns": []})
    assert r.status_code == 200, r.text
    rid = r.json()["review_id"]
    assert r.json()["document_ids"] == [] and r.json()["member_id"] == w.outsider
    assert client.get(f"/api/tabular/reviews/{rid}", headers=as_member(w.insider)).status_code == 404
    assert rid not in {x["review_id"] for x in client.get("/api/tabular/reviews", headers=as_member(w.insider)).json()}
    assert client.get(f"/api/tabular/reviews/{rid}", headers=as_member(w.outsider)).status_code == 200


def test_assistant_reader_rechecks_access(walls):
    from app.chat.tools.document_tools import DocEntry, resolve_document_text

    w = walls[0]
    store = {"D1": "text cached earlier in the conversation"}
    with connect() as conn:
        out = resolve_document_text(DocEntry("D1", w.document_id, "x"), store, conn, w.outsider)
    assert out == "Document could not be read." and "D1" not in store


def test_lapsed_staffing_loses_team_access(cast):
    """A team-mode matter: someone whose assignment ended no longer counts as the team."""
    mid, who = cast["matter_id"], cast["author"]
    with connect() as conn:
        mode = conn.execute("SELECT mode FROM matter_access WHERE matter_id = %s", (mid,)).fetchone()["mode"]
        conn.execute("UPDATE matter_access SET mode = 'team' WHERE matter_id = %s", (mid,))
        conn.commit()
        try:
            assert access.can_see_matter(conn, who, mid)
            conn.execute("UPDATE matter_members SET ended_at = current_date - 1 WHERE matter_id = %s AND member_id = %s", (mid, who))
            conn.commit()
            assert not access.can_see_matter(conn, who, mid)
            assert access.matter_level(conn, who, mid) == "none"
            # A list left stale by the passing of time is repaired by the refresher.
            conn.execute("UPDATE permissions SET allowed_members = array_append(allowed_members, %s) WHERE matter_id = %s", (who, mid))
            conn.commit()
            assert access.can_see_matter(conn, who, mid)
            conn.execute("SELECT acl_refresh_lapsed()")
            conn.commit()
            assert not access.can_see_matter(conn, who, mid)
        finally:
            conn.execute("UPDATE matter_members SET ended_at = NULL WHERE matter_id = %s AND member_id = %s", (mid, who))
            conn.execute("UPDATE matter_access SET mode = %s WHERE matter_id = %s", (mode, mid))
            conn.commit()


ADMIN = "MEM-00011"


def test_an_archived_document_is_reachable_by_nobody_until_restored(client, cast, doc):
    # Staff without manage access cannot archive; the lead can, and must say why.
    assert client.post(f"/api/documents/{doc}/archive", json={"reason": "obsolete"}, headers=as_member(cast["stranger"])).status_code in (403, 404)
    assert client.post(f"/api/documents/{doc}/archive", json={"reason": ""}, headers=as_member(cast["lead"])).status_code == 422
    done = client.post(f"/api/documents/{doc}/archive", json={"reason": "Filed in error"}, headers=as_member(cast["lead"]))
    assert done.status_code == 200, done.text
    assert client.post(f"/api/documents/{doc}/archive", json={"reason": "again"}, headers=as_member(cast["lead"])).status_code in (404, 409)

    for who in ("author", "lead", "auditor", "stranger"):
        assert _none(_reach(client, cast, doc, cast[who])), who

    # Only an administrator sees the archive and restores from it.
    assert client.get("/api/documents/archived", headers=as_member(cast["lead"])).status_code == 403
    listed = client.get("/api/documents/archived", headers=as_member(ADMIN)).json()["items"]
    assert any(d["document_id"] == doc and d["archive_reason"] == "Filed in error" for d in listed)
    assert client.post(f"/api/documents/{doc}/restore", headers=as_member(cast["lead"])).status_code == 403
    assert client.post(f"/api/documents/{doc}/restore", headers=as_member(ADMIN)).status_code == 200

    for who in ("author", "lead", "stranger"):
        assert _all(_reach(client, cast, doc, cast[who])), who
