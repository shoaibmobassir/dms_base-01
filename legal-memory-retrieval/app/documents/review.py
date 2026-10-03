"""Word review in Precentis (plan 18): who changed what, accept/reject, comments both ways.

    index_version     per version: each person's tracked changes and comments in the file
                      (``document_revision_authors``) and the file's Word comments imported
                      into Precentis comments (once per comment, across versions)
    get_review        the reviewing pane: grouped changes, people, what is outside the body
    contributors      one timeline per person across every version: what they changed in
                      the file (Word) and what they did in Precentis (uploads, saves, reviews,
                      comments)
    apply_review      accept or reject changes → the next version, attributed to the member
    sync_comments     Precentis comments, replies and resolutions written into a .docx
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app import access
from app.audit import events as audit
from app.documents import docx_comments, docx_review
from app.documents.editing import (
    DOCX_MIME,
    EditError,
    _check_can_write,
    _create,
    _document,
    _file_of,
    _member_name,
    _next_number,
    _one,
    _require,
    _store_version_file,
    _version,
    record_event,
)


def _members_by_name(conn, names: list[str]) -> dict[str, str]:
    rows = conn.execute("SELECT member_id, name FROM members WHERE lower(name) = ANY(%s)",
                        ([n.lower() for n in names],)).fetchall()
    return {r["name"].lower(): r["member_id"] for r in rows}


def _docx_of(conn, doc: dict, version_id: str | None) -> tuple[bytes | None, dict | None]:
    ver = _version(conn, doc["document_id"], version_id or doc["current_version_id"])
    data, kind = _file_of(doc, ver)
    return (data if kind == "docx" else None), ver


# ── indexing ─────────────────────────────────────────────────────────────────

def index_version(conn, doc: dict, version_id: str, data: bytes | None = None) -> None:
    """Record who changed what in this version's file and import its Word comments (idempotent)."""
    if data is None:
        data, _ = _docx_of(conn, doc, version_id)
    if data is None:
        conn.execute("UPDATE document_versions SET review_indexed_at = now() WHERE version_id = %s", (version_id,))
        conn.commit()
        return
    people = docx_review.contributors(data)
    names = _members_by_name(conn, [p["author"] for p in people])
    conn.execute("DELETE FROM document_revision_authors WHERE version_id = %s", (version_id,))
    for p in people:
        conn.execute(
            """INSERT INTO document_revision_authors (version_id, document_id, author_name, member_id, insertions, deletions,
                   formats, moves, paragraphs, words_added, words_removed, comments, replies, first_at, last_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (version_id, doc["document_id"], p["author"], names.get(p["author"].lower()), p["insertions"], p["deletions"],
             p["formats"], p["moves"], p["paragraphs"], p["words_added"], p["words_removed"], p["comments"], p["replies"],
             p["first_at"], p["last_at"]),
        )
    _import_comments(conn, doc, version_id, data)
    conn.execute("UPDATE document_versions SET review_indexed_at = now() WHERE version_id = %s", (version_id,))
    conn.commit()


def _import_comments(conn, doc: dict, version_id: str, data: bytes) -> int:
    """Word comments not yet known for this document become Precentis comment threads."""
    comments = docx_comments.read_comments(data)
    if not comments:
        return 0
    known = {r["external_id"]: r for r in conn.execute(
        "SELECT annotation_id, external_id, status, parent_id FROM annotations WHERE document_id = %s AND external_id IS NOT NULL",
        (doc["document_id"],))}
    names = _members_by_name(conn, [c["author"] for c in comments])
    by_para = {c["para_id"]: c for c in comments if c["para_id"]}
    ids: dict[str, str] = {}   # Word paraId → annotation id
    added = 0
    # Roots first so replies find their thread.
    for c in sorted(comments, key=lambda c: c["parent_para_id"] is not None):
        ext = docx_comments.external_id(c)
        row = known.get(ext) or (known.get(c["para_id"]) if c["para_id"] else None)
        if row is not None:
            ids[c["para_id"]] = row["annotation_id"]
            if row["parent_id"] is None:  # a thread resolved or reopened in Word follows
                want = "resolved" if c["done"] else "active"
                if row["status"] != want:
                    conn.execute("UPDATE annotations SET status = %s, updated_at = now() WHERE annotation_id = %s",
                                 (want, row["annotation_id"]))
            continue
        parent_ann = None
        if c["parent_para_id"]:
            parent_ann = ids.get(c["parent_para_id"])
            if parent_ann is None and c["parent_para_id"] in by_para:
                parent = by_para[c["parent_para_id"]]
                prow = known.get(docx_comments.external_id(parent))
                parent_ann = prow["annotation_id"] if prow else None
        ann_id = "CMT-W" + hashlib.sha1(f"{doc['document_id']}:{ext}".encode()).hexdigest()[:11].upper()
        try:
            created = datetime.fromisoformat(c["date"].replace("Z", "+00:00")) if c["date"] else None
        except ValueError:
            created = None
        conn.execute(
            """INSERT INTO annotations (annotation_id, document_id, version_id, annotation_type, author_id, author_name,
                   page_number, start_offset, end_offset, quoted_text, text_hash, content, rects, parent_id, status,
                   source, external_id, anchor_pid, created_at, updated_at)
               VALUES (%s, %s, %s, 'comment', %s, %s, 1, 0, 0, %s, %s, %s, '[]'::jsonb, %s, %s, 'word', %s, %s,
                       coalesce(%s, now()), now())
               ON CONFLICT DO NOTHING""",
            (ann_id, doc["document_id"], version_id, names.get(c["author"].lower()), c["author"],
             "" if parent_ann else c["quote"], hashlib.sha256(c["quote"].encode()).hexdigest()[:64], c["text"], parent_ann,
             "resolved" if (c["done"] and not parent_ann) else "active", ext, c["pid"], created),
        )
        ids[c["para_id"]] = ann_id
        known[ext] = {"annotation_id": ann_id, "external_id": ext, "status": "active", "parent_id": parent_ann}
        added += 1
    if added:
        record_event(conn, doc["document_id"], None, "comment.import", version_id, {"imported": added})
    return added


def ensure_indexed(conn, doc: dict, version_id: str | None) -> None:
    vid = version_id or doc["current_version_id"]
    if not vid:
        return
    row = _one(conn, "SELECT review_indexed_at FROM document_versions WHERE version_id = %s", (vid,))
    if row is not None and row["review_indexed_at"] is None:
        index_version(conn, doc, vid)


# ── reading ──────────────────────────────────────────────────────────────────

def get_review(conn, document_id: str, member_id: str | None, version_id: str | None = None) -> dict[str, Any]:
    doc = _document(conn, document_id)
    level = _require(conn, member_id, doc, "read")
    data, ver = _docx_of(conn, doc, version_id)
    if ver is None:
        raise EditError(404, "Version not found")
    base = {"document_id": doc["document_id"], "version_id": ver["version_id"], "version_number": ver["version_number"],
            "is_current": ver["version_id"] == doc["current_version_id"], "can_review": level in ("edit", "manage")}
    if data is None:
        return {**base, "word": False, "changes": [], "people": [], "outside_body": {}, "properties": {}, "total": 0}
    ensure_indexed(conn, doc, ver["version_id"])
    revs = docx_review.read_revisions(data)
    changes = docx_review.as_dicts(docx_review.group_changes(data, revs))
    people = docx_review.contributors(data, revs)
    names = _members_by_name(conn, [p["author"] for p in people])
    for p in people:
        p["member_id"] = names.get(p["author"].lower())
    return {**base, "word": True, "total": len(revs), "changes": changes, "people": people,
            "outside_body": docx_review.other_part_counts(data), "properties": docx_review.core_properties(data)}


def contributors(conn, document_id: str, member_id: str | None) -> dict[str, Any]:
    """Everyone who worked on the document, across all its versions."""
    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "read")
    for v in conn.execute("SELECT version_id FROM document_versions WHERE document_id = %s AND review_indexed_at IS NULL",
                          (doc["document_id"],)).fetchall():
        index_version(conn, doc, v["version_id"])
    people: dict[str, dict] = {}

    def person(name: str, member: str | None) -> dict:
        key = (member or name).lower()
        p = people.setdefault(key, {"name": name, "member_id": member, "external": member is None, "word": {
            "insertions": 0, "deletions": 0, "formats": 0, "moves": 0, "words_added": 0, "words_removed": 0,
            "comments": 0, "replies": 0}, "precentis": {}, "versions": [], "first_at": None, "last_at": None})
        return p

    def seen(p: dict, when) -> None:
        if when is None:
            return
        w = when.isoformat() if hasattr(when, "isoformat") else str(when)
        p["first_at"] = min(filter(None, [p["first_at"], w]))
        p["last_at"] = max(filter(None, [p["last_at"], w]))

    # Word: a revision stays in every later file until it is accepted or rejected, so per person
    # take the largest count seen in any version (and list the versions they appear in).
    for r in conn.execute(
        """SELECT a.*, v.version_number FROM document_revision_authors a JOIN document_versions v USING (version_id)
           WHERE a.document_id = %s ORDER BY v.version_number""", (doc["document_id"],)).fetchall():
        p = person(r["author_name"], r["member_id"])
        for k in p["word"]:
            p["word"][k] = max(p["word"][k], r[k])
        if r["version_number"] not in p["versions"]:
            p["versions"].append(r["version_number"])
        seen(p, r["first_at"])
        seen(p, r["last_at"])
    # Precentis: what they did here.
    for r in conn.execute(
        """SELECT e.member_id, m.name, e.action, count(*) AS n, min(e.occurred_at) AS first_at, max(e.occurred_at) AS last_at
           FROM document_events e JOIN members m USING (member_id)
           WHERE e.document_id = %s AND e.action IN ('edit.save', 'version.upload', 'review.accept', 'review.reject',
                 'comment.add', 'comment.reply', 'comment.resolve', 'privacy.change')
           GROUP BY 1, 2, 3""", (doc["document_id"],)).fetchall():
        p = person(r["name"], r["member_id"])
        p["precentis"][r["action"]] = r["n"]
        seen(p, r["first_at"])
        seen(p, r["last_at"])
    for r in conn.execute(
        """SELECT v.created_by_member_id AS member_id, m.name, v.version_number, v.created_at FROM document_versions v
           JOIN members m ON m.member_id = v.created_by_member_id WHERE v.document_id = %s""", (doc["document_id"],)).fetchall():
        p = person(r["name"], r["member_id"])
        if r["version_number"] not in p["versions"]:
            p["versions"].append(r["version_number"])
        seen(p, r["created_at"])
    out = sorted(people.values(), key=lambda p: p["last_at"] or "", reverse=True)
    for p in out:
        p["versions"].sort()
    return {"document_id": doc["document_id"], "people": out}


# ── accept / reject ──────────────────────────────────────────────────────────

def apply_review(conn, document_id: str, member_id: str | None, *, base_version_id: str, action: str,
                 keys: list[str] | None = None, authors: list[str] | None = None, everything: bool = False,
                 note: str = "", token: str | None = None) -> dict[str, Any]:
    if action not in ("accept", "reject"):
        raise EditError(422, "action must be accept or reject")
    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "edit")
    if member_id is None:
        raise EditError(400, "Sign in to review changes")
    _check_can_write(conn, document_id, member_id, token)
    if base_version_id != doc["current_version_id"]:
        raise EditError(409, "Someone saved a newer version while you were reviewing; reload to see it",
                        {"current_version_id": doc["current_version_id"]})
    data, ver = _docx_of(conn, doc, base_version_id)
    if data is None:
        raise EditError(422, "Only Word files have tracked changes")
    revs = docx_review.read_revisions(data)
    if everything:
        chosen = [r.key for r in revs]
    elif authors:
        chosen = [r.key for r in revs if r.author in set(authors)]
    else:
        valid = {r.key for r in revs}
        chosen = [k for k in (keys or []) if k in valid]
    if not chosen:
        raise EditError(422, "No matching tracked changes")
    by_author: dict[str, int] = {}
    for r in revs:
        if r.key in set(chosen):
            by_author[r.author] = by_author.get(r.author, 0) + 1
    out, done = docx_review.resolve(data, chosen, accept=action == "accept")
    out = sync_comments(conn, doc, out)
    verb = "Accepted" if action == "accept" else "Rejected"
    summary = note.strip() or f"{verb} " + ", ".join(f"{n} change{'s' if n != 1 else ''} by {a}" for a, n in by_author.items())
    from pathlib import Path

    from app.ingest.extractors.dispatch import extract_from_bytes

    number = _next_number(conn, document_id)
    name = Path(doc["title"]).stem + ".docx"
    uri = _store_version_file(doc, number, name, out, DOCX_MIME)
    extracted = extract_from_bytes(name, docx_review.accept_everything(out))
    version = _create(conn, doc, member_id, text=extracted.text, note=summary[:1000], origin="review", label=None,
                      storage_uri=uri, mime=DOCX_MIME, size=len(out), page_spans=extracted.pages)
    stats = {"action": action, "changes": done, "by_author": by_author}
    record_event(conn, document_id, member_id, f"review.{action}", version["version_id"], stats)
    conn.commit()
    index_version(conn, doc, version["version_id"], out)
    audit.record(f"document.review.{action}", member_id=member_id, object_type="document", object_id=document_id,
                 matter_id=doc["matter_id"], detail={"version_id": version["version_id"], **stats})
    return {"version_id": version["version_id"], "version_number": version["version_number"], **stats, "note": summary}


# ── comments into the file ───────────────────────────────────────────────────

def _threads(conn, document_id: str) -> list[dict]:
    """Every comment thread of the document, roots before replies, for writing into a file."""
    rows = conn.execute(
        """SELECT a.annotation_id, a.parent_id, a.source, a.external_id, a.author_name, a.content, a.status,
                  a.quoted_text, a.anchor_pid, a.created_at, coalesce(root.status, a.status) AS root_status
           FROM annotations a LEFT JOIN annotations root ON root.annotation_id = a.parent_id
           WHERE a.document_id = %s AND a.annotation_type = 'comment'
           ORDER BY (a.parent_id IS NOT NULL), a.created_at, a.annotation_id""", (document_id,)).fetchall()
    return [{"annotation_id": r["annotation_id"], "parent_id": r["parent_id"], "source": r["source"],
             "external_id": r["external_id"], "author": r["author_name"] or "Precentis", "text": r["content"] or "",
             "status": "resolved" if r["status"] == "resolved" else "open", "quote": r["quoted_text"] or "",
             "pid": r["anchor_pid"], "date": r["created_at"].strftime("%Y-%m-%dT%H:%M:%SZ") if r["created_at"] else None}
            for r in rows]


def sync_comments(conn, doc: dict, data: bytes) -> bytes:
    """Write Precentis comments, replies and resolved states into ``data`` and remember the ids."""
    threads = _threads(conn, doc["document_id"])
    if not threads:
        return data
    out, written = docx_comments.write_comments(data, threads)
    for ann_id, ext in written.items():
        conn.execute("UPDATE annotations SET external_id = %s WHERE annotation_id = %s AND external_id IS NULL", (ext, ann_id))
    conn.commit()
    return out


def download_with_comments(conn, document_id: str, member_id: str | None, version_id: str | None = None) -> tuple[bytes, str]:
    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "read")
    data, ver = _docx_of(conn, doc, version_id)
    if data is None:
        raise EditError(422, "Only Word files carry comments")
    ensure_indexed(conn, doc, ver["version_id"])
    from pathlib import Path

    audit.record("document.download", member_id=member_id, object_type="document", object_id=document_id,
                 matter_id=doc["matter_id"], detail={"version_id": ver["version_id"], "with_comments": True})
    return sync_comments(conn, doc, data), Path(doc["title"]).stem + ".docx"


def _json(v: Any) -> str:
    return json.dumps(v, default=str)
