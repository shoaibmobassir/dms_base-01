"""Document privacy: Private / Restricted on top of matter access (plan 17, P1b).

    matter      the document follows its matter (no row in ``document_access``)
    private     only the owner and the people/teams they share it with
    restricted  named people/teams, plus the matter's managers (lead, manage grants)

Both only narrow matter access. Holders of walls.manage can always read (audited on every
read, see ``access.document_access``). The database compiles who may see the document into
``documents.visible_to`` / ``chunks.visible_to`` (migration 20260928c), which every read
path filters on.

Who may change it:
    from matter     the document's author or a matter manager (they become the owner)
    private         the owner only
    restricted      the owner or a matter manager
Changes use optimistic concurrency (``row_version``) and are audited.
"""
from __future__ import annotations

from typing import Any

from app import access
from app.audit import events as audit
from app.documents.editing import EditError, _document, _member_name, _one, record_event

VISIBILITY = ("matter", "private", "restricted")
MAX_SHARES = 200


def _require(conn, member_id: str | None, document_id: str, level: str) -> dict:
    try:
        return access.require_document_level(conn, member_id, document_id, level, via="privacy")
    except access.AccessError as exc:
        raise EditError(exc.status, "Document not found or access denied" if exc.status == 404
                        else "You can view but not change this document") from exc


def _state(conn, document_id: str) -> dict | None:
    return _one(conn, "SELECT * FROM document_access WHERE document_id = %s", (document_id,))


def _author(conn, doc_id: str) -> str | None:
    """Who wrote the document: its recorded author, or whoever created its first version."""
    row = _one(conn, """
        SELECT coalesce(d.author_id,
                        (SELECT v.created_by_member_id FROM document_versions v
                         WHERE v.document_id = d.document_id AND v.created_by_member_id IS NOT NULL
                         ORDER BY v.version_number LIMIT 1)) AS author
        FROM documents d WHERE d.document_id = %s""", (doc_id,))
    return row["author"] if row else None


def _shares(conn, document_id: str) -> list[dict]:
    return conn.execute(
        """SELECT s.principal_type, s.principal_id, s.level, coalesce(m.name, t.name) AS name
           FROM document_shares s
           LEFT JOIN members m ON s.principal_type = 'member' AND m.member_id = s.principal_id
           LEFT JOIN teams t ON s.principal_type = 'team' AND t.team_id = s.principal_id
           WHERE s.document_id = %s ORDER BY s.principal_type, name""", (document_id,)).fetchall()


def _may_change(conn, member_id: str | None, doc: dict, state: dict | None) -> bool:
    if member_id is None:
        return True  # dev mode (auth off): the server trusts the header
    manages = access._manages_matter(conn, member_id, doc["matter_id"])
    if state is None:  # follows the matter today
        return manages or member_id == _author(conn, doc["document_id"])
    if state["visibility"] == "private":
        return state["owner_member_id"] == member_id
    return manages or state["owner_member_id"] == member_id


def get_privacy(conn, document_id: str, member_id: str | None) -> dict[str, Any]:
    doc = _document(conn, document_id)
    info = _require(conn, member_id, doc["document_id"], "read")
    state = _state(conn, doc["document_id"])
    owner = state["owner_member_id"] if state else None
    return {
        "document_id": doc["document_id"],
        "visibility": state["visibility"] if state else "matter",
        "owner": {"member_id": owner, "name": _member_name(conn, owner)} if owner else None,
        "shares": _shares(conn, doc["document_id"]) if state else [],
        "row_version": state["row_version"] if state else 0,
        "can_change": info["level"] in ("edit", "manage") and not info["privileged"] and _may_change(conn, member_id, doc, state),
    }


def _validate_shares(conn, doc: dict, shares: list[dict]) -> list[dict]:
    if len(shares) > MAX_SHARES:
        raise EditError(422, f"At most {MAX_SHARES} people and teams")
    out, seen = [], set()
    for s in shares:
        kind, pid, level = s.get("principal_type"), str(s.get("principal_id") or ""), s.get("level", "read")
        if kind not in ("member", "team") or not pid or level not in ("read", "edit"):
            raise EditError(422, "Each share needs principal_type (member|team), principal_id and level (read|edit)")
        if (kind, pid) in seen:
            continue
        seen.add((kind, pid))
        if kind == "member":
            if _one(conn, "SELECT 1 AS ok FROM members WHERE member_id = %s", (pid,)) is None:
                raise EditError(422, f"Unknown person {pid}")
            if access.matter_level(conn, pid, doc["matter_id"]) == "none":
                raise EditError(422, f"{_member_name(conn, pid)} cannot see this matter; give them matter access first")
        elif _one(conn, "SELECT 1 AS ok FROM teams WHERE team_id = %s", (pid,)) is None:
            raise EditError(422, f"Unknown team {pid}")
        out.append({"principal_type": kind, "principal_id": pid, "level": level})
    return out


def set_privacy(conn, document_id: str, member_id: str | None, *, visibility: str, shares: list[dict],
                row_version: int | None) -> dict[str, Any]:
    if visibility not in VISIBILITY:
        raise EditError(422, "visibility must be matter, private or restricted")
    doc = _document(conn, document_id)
    doc_id = doc["document_id"]
    info = _require(conn, member_id, doc_id, "edit")
    state = _state(conn, doc_id)
    current = state["row_version"] if state else 0
    if row_version is not None and row_version != current:
        raise EditError(409, "Someone changed who can see this document; reload and try again", {"row_version": current})
    if info["privileged"] or not _may_change(conn, member_id, doc, state):
        if state and state["visibility"] == "private":
            raise EditError(403, "Only the owner can change a private document")
        raise EditError(403, "Only the document's author or a matter manager can change who sees it")
    clean = _validate_shares(conn, doc, shares) if visibility != "matter" else []
    before = {"visibility": state["visibility"] if state else "matter", "shares": _shares(conn, doc_id) if state else []}

    if visibility == "matter":
        conn.execute("DELETE FROM document_shares WHERE document_id = %s", (doc_id,))
        conn.execute("DELETE FROM document_access WHERE document_id = %s", (doc_id,))
    else:
        owner = state["owner_member_id"] if state else (member_id or _author(conn, doc_id))
        if owner is None:
            raise EditError(422, "Sign in to make a document private")
        conn.execute(
            """INSERT INTO document_access (document_id, visibility, owner_member_id, updated_by)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (document_id) DO UPDATE SET visibility = EXCLUDED.visibility, updated_by = EXCLUDED.updated_by,
                   updated_at = now(), row_version = document_access.row_version + 1""",
            (doc_id, visibility, owner, member_id),
        )
        conn.execute("DELETE FROM document_shares WHERE document_id = %s", (doc_id,))
        for s in clean:
            conn.execute(
                "INSERT INTO document_shares (document_id, principal_type, principal_id, level, added_by) VALUES (%s, %s, %s, %s, %s)",
                (doc_id, s["principal_type"], s["principal_id"], s["level"], member_id),
            )
    record_event(conn, doc_id, member_id, "privacy.change", doc.get("current_version_id"),
                 {"from": before["visibility"], "to": visibility, "shares": len(clean)})
    conn.commit()
    audit.record("document.privacy.change", member_id=member_id, object_type="document", object_id=doc_id,
                 matter_id=doc["matter_id"], detail={"before": before, "after": {"visibility": visibility, "shares": clean}})
    _refresh_matter_profile(doc["matter_id"])
    return get_privacy(conn, doc_id, member_id)


def _refresh_matter_profile(matter_id: str) -> None:
    """The shared matter profile lists document titles; rebuild it without private ones."""
    from app.documents.editing import _embedder_pool
    from app.km.resolver import invalidate

    invalidate()

    def job() -> None:
        from app.db.connection import connect
        from app.km import profiles

        try:
            with connect() as conn:
                profiles.rebuild(conn, [matter_id])
        except Exception:  # the next full rebuild catches up
            pass

    _embedder_pool.submit(job)


def make_private_on_create(conn, document_id: str, member_id: str) -> None:
    """A new upload marked private: its uploader owns it and nobody else is named."""
    conn.execute(
        """INSERT INTO document_access (document_id, visibility, owner_member_id, updated_by)
           VALUES (%s, 'private', %s, %s) ON CONFLICT (document_id) DO NOTHING""",
        (document_id, member_id, member_id),
    )
    record_event(conn, document_id, member_id, "privacy.change", None, {"from": "matter", "to": "private", "on": "create"})
    conn.commit()
    audit.record("document.privacy.change", member_id=member_id, object_type="document", object_id=document_id,
                 detail={"after": {"visibility": "private"}, "on": "create"})


def share_targets(conn, document_id: str, member_id: str | None) -> dict[str, Any]:
    """People who can see the document's matter (only they can be given the document) and teams."""
    doc = _document(conn, document_id)
    _require(conn, member_id, doc["document_id"], "read")
    people = conn.execute(
        """SELECT mb.member_id, mb.name, mb.role, mb.office FROM members mb
           JOIN permissions p ON p.matter_id = %s
           WHERE (p.restricted = FALSE OR mb.member_id = ANY (p.allowed_members))
             AND NOT (mb.member_id = ANY (p.denied_members))
           ORDER BY mb.name""", (doc["matter_id"],)).fetchall()
    teams = conn.execute(
        """SELECT t.team_id, t.name, count(tm.member_id) AS members FROM teams t
           LEFT JOIN team_members tm USING (team_id) GROUP BY t.team_id, t.name ORDER BY t.name""").fetchall()
    return {"people": people, "teams": teams}
