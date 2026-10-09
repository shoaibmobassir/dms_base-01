"""Playbooks (plan 22, W5): reusable ways of doing a job.

Two kinds: *instructions* (Markdown the Assistant reads and follows, within the system rules) and *columns* (a set of
review questions that starts a tabular review). Three sources:

- shipped  — files in ``app/playbooks/catalog`` (front matter + Markdown), synced into the table by content hash;
             everyone reads them, nobody edits them (duplicate to change one)
- firm     — published by people with ``km.publish``; everyone reads them, publishers edit them
- personal — the owner's; shared with people or teams to view or edit
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from pathlib import Path
from typing import Any

import yaml

from app import access
from app.api.acl import doc_read
from app.audit import events as audit
from app.firm import FirmError, check_version, guard, one
from app.workspaces import rows

CATALOG = Path(__file__).parent / "catalog"
KINDS = ("instructions", "columns")
LEVELS = access.LEVELS
_synced: dict[str, float] = {}
_sync_lock = threading.Lock()


def _parse(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path.name}: front matter missing")
    _, front, body = text.split("---\n", 2)
    meta = yaml.safe_load(front) or {}
    return {"meta": meta, "body": body.strip(), "sha": hashlib.sha256(text.encode()).hexdigest()}


def sync_shipped(conn, force: bool = False) -> int:
    """Bring the shipped catalog into the table: new files added, changed files updated (version + 1), removed files
    archived. Personal and firm copies of a shipped playbook are never touched. Returns rows changed."""
    stamp = max((p.stat().st_mtime for p in CATALOG.glob("*.md")), default=0.0)
    with _sync_lock:
        if not force and _synced.get("catalog") == stamp:
            return 0
        changed = 0
        seen = []
        for path in sorted(CATALOG.glob("*.md")):
            parsed = _parse(path)
            meta = parsed["meta"]
            pid = "PBK-" + path.name.removesuffix(".md").replace(".", "-").upper()
            seen.append(pid)
            kind = meta.get("kind") or ("columns" if path.name.endswith(".columns.md") else "instructions")
            columns = _clean_columns(meta.get("columns") or []) if kind == "columns" else []
            row = one(conn, "SELECT content_sha256 FROM playbooks WHERE playbook_id = %s", (pid,))
            if row and row["content_sha256"] == parsed["sha"]:
                continue
            conn.execute(
                """INSERT INTO playbooks (playbook_id, kind, source, title, summary, practice_area, jurisdiction, language,
                                         body_md, columns, content_sha256)
                   VALUES (%(id)s, %(kind)s, 'shipped', %(title)s, %(summary)s, %(pa)s, %(jur)s, %(lang)s, %(body)s,
                           %(cols)s::jsonb, %(sha)s)
                   ON CONFLICT (playbook_id) DO UPDATE SET kind = EXCLUDED.kind, title = EXCLUDED.title,
                       summary = EXCLUDED.summary, practice_area = EXCLUDED.practice_area,
                       jurisdiction = EXCLUDED.jurisdiction, language = EXCLUDED.language, body_md = EXCLUDED.body_md,
                       columns = EXCLUDED.columns, content_sha256 = EXCLUDED.content_sha256,
                       version = playbooks.version + 1, updated_at = now(), archived_at = NULL""",
                {"id": pid, "kind": kind, "title": meta.get("title") or path.stem, "summary": meta.get("summary"),
                 "pa": meta.get("practice_area"), "jur": meta.get("jurisdiction"), "lang": meta.get("language"),
                 "body": parsed["body"], "cols": json.dumps(columns), "sha": parsed["sha"]})
            changed += 1
        gone = conn.execute("""UPDATE playbooks SET archived_at = now() WHERE source = 'shipped' AND archived_at IS NULL
                               AND NOT (playbook_id = ANY(%s)) RETURNING playbook_id""", (seen,)).fetchall()
        conn.commit()
        _synced["catalog"] = stamp
        return changed + len(gone)


def _clean_columns(columns: list) -> list[dict]:
    from app.tabular import _column_input

    try:
        return [_column_input(dict(c)) for c in columns]
    except FirmError as exc:
        raise FirmError(422, f"Columns: {exc.detail}") from exc


def _shared_level(conn, actor: str, playbook_id: str) -> int:
    row = one(conn, """
        SELECT max(CASE s.level WHEN 'edit' THEN 2 ELSE 1 END) AS lvl FROM playbook_shares s
        LEFT JOIN team_members tm ON s.principal_type = 'team' AND tm.team_id = s.principal_id
        WHERE s.playbook_id = %(p)s AND ((s.principal_type = 'member' AND s.principal_id = %(u)s) OR tm.member_id = %(u)s)
        """, {"p": playbook_id, "u": actor})
    return int(row["lvl"] or 0) if row else 0


def level_of(conn, actor: str | None, pb: dict) -> str:
    """none | read | edit | manage for one playbook."""
    if pb["archived_at"] is not None and pb["source"] != "personal":
        return "none"
    if actor is None:
        return "manage"
    if pb["source"] == "shipped":
        return "read"
    if pb["source"] == "firm":
        return "manage" if access.has_permission(conn, actor, "km.publish") else "read"
    if pb["owner_member_id"] == actor:
        return "manage"
    return LEVELS[_shared_level(conn, actor, pb["playbook_id"])]


def _playbook(conn, actor: str | None, playbook_id: str, needed: str) -> dict:
    pb = one(conn, "SELECT * FROM playbooks WHERE playbook_id = %s", (playbook_id,))
    if pb is None:
        raise FirmError(404, "Playbook not found")
    level = level_of(conn, actor, pb)
    if level == "none":
        raise FirmError(404, "Playbook not found")
    if LEVELS.index(level) < LEVELS.index(needed):
        if pb["source"] == "shipped":
            raise FirmError(403, "Shipped playbooks cannot be changed; duplicate it to make your own")
        raise FirmError(403, f"Requires {needed} access to this playbook")
    return {**pb, "my_level": level}


def _text(value: Any, field: str, limit: int, required: bool = False) -> str | None:
    text = str(value or "").strip()
    if required and not text:
        raise FirmError(422, f"{field} is required")
    if len(text) > limit:
        raise FirmError(422, f"{field} is limited to {limit} characters")
    return text or None


def _input(data: dict, kind: str) -> dict:
    out = {"title": _text(data.get("title"), "title", 200, required=True),
           "summary": _text(data.get("summary"), "summary", 500),
           "practice_area": _text(data.get("practice_area"), "practice_area", 100),
           "jurisdiction": _text(data.get("jurisdiction"), "jurisdiction", 100),
           "language": _text(data.get("language"), "language", 50),
           "body_md": _text(data.get("body_md"), "body_md", 60000) or ""}
    out["columns"] = _clean_columns(data.get("columns") or []) if kind == "columns" else []
    if kind == "columns" and not out["columns"]:
        raise FirmError(422, "A column set needs at least one column")
    if kind == "instructions" and not out["body_md"]:
        raise FirmError(422, "Write the instructions")
    return out


def _out(conn, actor: str | None, pb: dict, full: bool = False) -> dict:
    base = {k: pb[k] for k in ("playbook_id", "kind", "source", "title", "summary", "practice_area", "jurisdiction", "language",
                               "owner_member_id", "origin_playbook_id", "version", "row_version", "updated_at", "archived_at")}
    base["my_level"] = pb.get("my_level") or level_of(conn, actor, pb)
    base["column_count"] = len(pb["columns"] or [])
    if full:
        base["body_md"] = pb["body_md"]
        base["columns"] = pb["columns"]
        base["files"] = rows(conn, f"""
            SELECT d.document_id, d.title FROM playbook_files f JOIN documents d USING (document_id)
            LEFT JOIN permissions p ON p.matter_id = d.matter_id
            WHERE f.playbook_id = %(p)s AND d.archived_at IS NULL AND {doc_read('d')} ORDER BY f.position""",
            {"p": pb["playbook_id"], "member_id": actor})
        base["shares"] = rows(conn, """
            SELECT s.principal_type, s.principal_id, s.level, coalesce(m.name, t.name) AS name FROM playbook_shares s
            LEFT JOIN members m ON s.principal_type = 'member' AND m.member_id = s.principal_id
            LEFT JOIN teams t ON s.principal_type = 'team' AND t.team_id = s.principal_id
            WHERE s.playbook_id = %s ORDER BY name""", (pb["playbook_id"],)) if base["my_level"] == "manage" else []
    return base


# ── read ─────────────────────────────────────────────────────────────────────

@guard
def list_playbooks(conn, actor: str | None, *, kind: str | None = None, q: str | None = None,
                   source: str | None = None) -> list[dict]:
    sync_shipped(conn)
    params: dict[str, Any] = {"u": actor, "kind": kind, "source": source, "q": f"%{q.strip()}%" if q and q.strip() else None}
    found = rows(conn, """
        SELECT pb.* FROM playbooks pb
        WHERE pb.archived_at IS NULL
          AND (%(kind)s::text IS NULL OR pb.kind = %(kind)s)
          AND (%(source)s::text IS NULL OR pb.source = %(source)s)
          AND (%(q)s::text IS NULL OR pb.title ILIKE %(q)s OR pb.summary ILIKE %(q)s OR pb.practice_area ILIKE %(q)s)
          AND (pb.source <> 'personal' OR %(u)s::text IS NULL OR pb.owner_member_id = %(u)s
               OR EXISTS (SELECT 1 FROM playbook_shares s
                          LEFT JOIN team_members tm ON s.principal_type = 'team' AND tm.team_id = s.principal_id
                          WHERE s.playbook_id = pb.playbook_id
                            AND ((s.principal_type = 'member' AND s.principal_id = %(u)s) OR tm.member_id = %(u)s)))
        ORDER BY CASE pb.source WHEN 'personal' THEN 0 WHEN 'firm' THEN 1 ELSE 2 END, lower(pb.title)""", params)
    return [_out(conn, actor, pb) for pb in found]


@guard
def get_playbook(conn, actor: str | None, playbook_id: str) -> dict:
    sync_shipped(conn)
    return _out(conn, actor, _playbook(conn, actor, playbook_id, "read"), full=True)


# ── write ────────────────────────────────────────────────────────────────────

def _set_files(conn, actor: str | None, playbook_id: str, document_ids: list[str]) -> None:
    """Reference documents: only ones the editor can read; others who open the playbook see those they can read."""
    ids = list(dict.fromkeys(i.upper() for i in document_ids if i))[:20]
    ok = {r["document_id"] for r in rows(conn, f"""
        SELECT d.document_id FROM documents d LEFT JOIN permissions p ON p.matter_id = d.matter_id
        WHERE d.document_id = ANY(%(ids)s) AND {doc_read('d')}""", {"ids": ids, "member_id": actor})}
    conn.execute("DELETE FROM playbook_files WHERE playbook_id = %s", (playbook_id,))
    for i, d in enumerate(x for x in ids if x in ok):
        conn.execute("INSERT INTO playbook_files (playbook_id, document_id, position) VALUES (%s, %s, %s)", (playbook_id, d, i))


@guard
def create_playbook(conn, actor: str | None, data: dict) -> dict:
    kind = data.get("kind")
    if kind not in KINDS:
        raise FirmError(422, "kind must be instructions or columns")
    clean = _input(data, kind)
    pid = f"PBK-{uuid.uuid4().hex[:10].upper()}"
    conn.execute(
        """INSERT INTO playbooks (playbook_id, kind, source, title, summary, practice_area, jurisdiction, language, body_md,
                                  columns, owner_member_id)
           VALUES (%(id)s, %(kind)s, 'personal', %(title)s, %(summary)s, %(practice_area)s, %(jurisdiction)s, %(language)s,
                   %(body_md)s, %(columns)s::jsonb, %(owner)s)""",
        {**clean, "columns": json.dumps(clean["columns"]), "id": pid, "kind": kind, "owner": actor})
    _set_files(conn, actor, pid, data.get("document_ids") or [])
    conn.commit()
    audit.record("playbook.create", member_id=actor, object_type="playbook", object_id=pid, detail={"kind": kind})
    return get_playbook(conn, actor, pid)


@guard
def update_playbook(conn, actor: str | None, playbook_id: str, changes: dict, row_version: int | None) -> dict:
    pb = _playbook(conn, actor, playbook_id, "edit")
    check_version(pb["row_version"], row_version, "playbook")
    merged = _input({**{k: pb[k] for k in ("title", "summary", "practice_area", "jurisdiction", "language", "body_md", "columns")},
                     **{k: v for k, v in changes.items() if k != "document_ids"}}, pb["kind"])
    conn.execute(
        """UPDATE playbooks SET title = %(title)s, summary = %(summary)s, practice_area = %(practice_area)s,
                  jurisdiction = %(jurisdiction)s, language = %(language)s, body_md = %(body_md)s, columns = %(columns)s::jsonb,
                  version = version + 1, row_version = row_version + 1, updated_at = now()
           WHERE playbook_id = %(id)s""",
        {**merged, "columns": json.dumps(merged["columns"]), "id": playbook_id})
    if "document_ids" in changes:
        _set_files(conn, actor, playbook_id, changes["document_ids"] or [])
    conn.commit()
    audit.record("playbook.update", member_id=actor, object_type="playbook", object_id=playbook_id)
    return get_playbook(conn, actor, playbook_id)


@guard
def duplicate_playbook(conn, actor: str | None, playbook_id: str, title: str | None = None) -> dict:
    pb = _playbook(conn, actor, playbook_id, "read")
    pid = f"PBK-{uuid.uuid4().hex[:10].upper()}"
    conn.execute(
        """INSERT INTO playbooks (playbook_id, kind, source, title, summary, practice_area, jurisdiction, language, body_md,
                                  columns, owner_member_id, origin_playbook_id)
           SELECT %s, kind, 'personal', %s, summary, practice_area, jurisdiction, language, body_md, columns, %s, playbook_id
           FROM playbooks WHERE playbook_id = %s""",
        (pid, (title or "").strip()[:200] or f"{pb['title']} (my copy)", actor, playbook_id))
    conn.execute("""INSERT INTO playbook_files (playbook_id, document_id, position)
                    SELECT %s, document_id, position FROM playbook_files WHERE playbook_id = %s""", (pid, playbook_id))
    conn.commit()
    audit.record("playbook.duplicate", member_id=actor, object_type="playbook", object_id=pid, detail={"from": playbook_id})
    return get_playbook(conn, actor, pid)


@guard
def publish_playbook(conn, actor: str | None, playbook_id: str) -> dict:
    """A personal playbook becomes a firm playbook everyone can use (km.publish)."""
    access.require_permission(conn, actor, "km.publish")
    pb = _playbook(conn, actor, playbook_id, "manage")
    if pb["source"] != "personal":
        raise FirmError(409, "Only a personal playbook can be published")
    conn.execute("UPDATE playbooks SET source = 'firm', updated_at = now(), row_version = row_version + 1 WHERE playbook_id = %s",
                 (playbook_id,))
    conn.execute("DELETE FROM playbook_shares WHERE playbook_id = %s", (playbook_id,))
    conn.commit()
    audit.record("playbook.publish", member_id=actor, object_type="playbook", object_id=playbook_id)
    return get_playbook(conn, actor, playbook_id)


@guard
def share_playbook(conn, actor: str | None, playbook_id: str, principal_type: str, principal_id: str, level: str | None) -> dict:
    """Share a personal playbook (view or edit), or stop sharing (level None). Owner only."""
    pb = _playbook(conn, actor, playbook_id, "manage")
    if pb["source"] != "personal":
        raise FirmError(409, "Firm and shipped playbooks are already available to everyone")
    if principal_type not in ("member", "team"):
        raise FirmError(422, "principal_type must be member or team")
    if level is None:
        conn.execute("DELETE FROM playbook_shares WHERE playbook_id = %s AND principal_type = %s AND principal_id = %s",
                     (playbook_id, principal_type, principal_id))
    else:
        if level not in ("view", "edit"):
            raise FirmError(422, "level must be view or edit")
        table = "members" if principal_type == "member" else "teams"
        key = "member_id" if principal_type == "member" else "team_id"
        if one(conn, f"SELECT 1 AS ok FROM {table} WHERE {key} = %s", (principal_id,)) is None:
            raise FirmError(422, f"Unknown {principal_type} {principal_id}")
        conn.execute("""INSERT INTO playbook_shares (playbook_id, principal_type, principal_id, level, added_by)
                        VALUES (%s, %s, %s, %s, %s) ON CONFLICT (playbook_id, principal_type, principal_id)
                        DO UPDATE SET level = EXCLUDED.level""", (playbook_id, principal_type, principal_id, level, actor))
    conn.commit()
    audit.record("playbook.share", member_id=actor, object_type="playbook", object_id=playbook_id,
                 detail={"principal_type": principal_type, "principal_id": principal_id, "level": level})
    return get_playbook(conn, actor, playbook_id)


@guard
def archive_playbook(conn, actor: str | None, playbook_id: str) -> dict:
    pb = _playbook(conn, actor, playbook_id, "manage")
    if pb["source"] == "shipped":
        raise FirmError(403, "Shipped playbooks cannot be removed")
    conn.execute("UPDATE playbooks SET archived_at = now() WHERE playbook_id = %s", (playbook_id,))
    conn.commit()
    audit.record("playbook.archive", member_id=actor, object_type="playbook", object_id=playbook_id)
    return {"playbook_id": playbook_id, "archived": True}


# ── for the Assistant ────────────────────────────────────────────────────────

def for_assistant_list(conn, actor: str | None) -> list[dict]:
    return [{"id": p["playbook_id"], "title": p["title"], "summary": p["summary"], "kind": p["kind"], "source": p["source"],
             "practice_area": p["practice_area"]} for p in list_playbooks(conn, actor)]


def for_assistant_read(conn, actor: str | None, playbook_id: str, nonce: str) -> dict:
    """The playbook to follow, fenced as user-selected instructions (the system prompt's workflow policy)."""
    from app.chat.spotlight import spotlight_workflow

    pb = get_playbook(conn, actor, playbook_id)
    out = {"id": pb["playbook_id"], "title": pb["title"], "kind": pb["kind"],
           "instructions": spotlight_workflow(pb["body_md"], nonce) if pb["body_md"] else "",
           "reference_documents": [{"document_id": f["document_id"], "title": f["title"]} for f in pb["files"]]}
    if pb["kind"] == "columns":
        out["columns"] = pb["columns"]
        out["how_to_use"] = "This is a set of review questions: offer to start a tabular review with them, or use review_documents."
    return out
