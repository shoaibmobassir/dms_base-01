"""Comments on the exact (page) view of a document version (plan 16, E6).

A comment marks an area of a rendered page — the text the reader selected, as boxes in
page fractions (0..1) — and says something about it. Replies form one level of thread;
a thread is resolved or reopened as a whole. Works for every file the exact view shows
(PDF, Word, …), and is the way to mark up PDFs, whose text is not edited in the browser.

Rules: anyone who can read the matter may comment and reply; the author or anyone with
edit rights resolves; only the author (or a matter manager) deletes. Authors always come
from the session. Every action lands in ``document_events``.
"""
from __future__ import annotations

import hashlib
import json
import uuid

from app.documents.editing import EditError, _document, _member_name, _one, _require, record_event

MAX_BODY = 5000
MAX_QUOTE = 2000
MAX_RECTS = 60


def _version_of(conn, doc: dict, version_id: str | None) -> str:
    vid = version_id or doc["current_version_id"]
    if not vid or _one(conn, "SELECT 1 FROM document_versions WHERE version_id = %s AND document_id = %s",
                       (vid, doc["document_id"])) is None:
        raise EditError(404, "Version not found")
    return vid


def _clean_rects(rects: list[dict]) -> list[dict]:
    if len(rects) > MAX_RECTS:
        raise EditError(422, "Too many highlighted areas")
    out = []
    for r in rects:
        try:
            x0, y0, x1, y1 = (float(r[k]) for k in ("x0", "y0", "x1", "y1"))
        except (KeyError, TypeError, ValueError) as exc:
            raise EditError(422, "Each area needs x0, y0, x1, y1") from exc
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise EditError(422, "Areas are page fractions between 0 and 1")
        out.append({"x0": round(x0, 5), "y0": round(y0, 5), "x1": round(x1, 5), "y1": round(y1, 5)})
    return out


def _row(conn, doc: dict, comment_id: str) -> dict:
    row = _one(conn, "SELECT * FROM annotations WHERE annotation_id = %s AND document_id = %s AND annotation_type = 'comment'",
               (comment_id, doc["document_id"]))
    if row is None:
        raise EditError(404, "Comment not found")
    return row


def _public(row: dict) -> dict:
    return {
        "comment_id": row["annotation_id"],
        "version_id": row["version_id"],
        "version_number": row.get("version_number"),
        "parent_id": row["parent_id"],
        "page": row["page_number"],
        "rects": row["rects"] or [],
        "quote": row["quoted_text"],
        "body": row["content"] or "",
        "author_id": row["author_id"],
        "author": row["author_name"],
        "status": "resolved" if row["status"] == "resolved" else "open",
        "resolved_by": row.get("resolved_by_name"),
        "resolved_at": row["resolved_at"],
        "created_at": row["created_at"],
    }


def list_comments(conn, document_id: str, member_id: str | None, version_id: str | None = None) -> dict:
    """Threads for one version (default: current), in page order.

    Open threads started on *earlier* versions come along, marked ``carried``: their anchor
    (quote + page) belongs to the version they were made on, and the viewer re-finds the
    quote in this version's pages — or shows the thread as "text changed". Resolved threads
    stay on their own version.
    """
    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "read")
    if version_id is None and not doc["current_version_id"]:
        # A text-only record without versions has nothing to comment on yet.
        return {"document_id": doc["document_id"], "version_id": None, "version_number": None,
                "is_current": True, "threads": [], "on_other_versions": 0}
    vid = _version_of(conn, doc, version_id)
    number = _one(conn, "SELECT version_number FROM document_versions WHERE version_id = %s", (vid,))["version_number"]
    rows = conn.execute(
        """SELECT a.*, v.version_number, r.name AS resolved_by_name,
                  root.version_id AS thread_version_id
           FROM annotations a
           JOIN document_versions v ON v.version_id = a.version_id
           LEFT JOIN members r ON r.member_id = a.resolved_by_member_id
           LEFT JOIN annotations root ON root.annotation_id = coalesce(a.parent_id, a.annotation_id)
           JOIN document_versions rv ON rv.version_id = root.version_id
           WHERE a.document_id = %s AND a.annotation_type = 'comment'
             AND (root.version_id = %s
                  OR (rv.version_number < %s AND root.status = 'active'))
           ORDER BY a.created_at, a.annotation_id""",
        (doc["document_id"], vid, number),
    ).fetchall()
    threads: dict[str, dict] = {}
    for row in rows:
        if row["parent_id"] is None:
            threads[row["annotation_id"]] = {**_public(row), "carried": row["version_id"] != vid, "replies": []}
    for row in rows:
        if row["parent_id"] in threads:
            threads[row["parent_id"]]["replies"].append(_public(row))
    ordered = sorted(threads.values(), key=lambda t: (t["page"], (t["rects"][0]["y0"] if t["rects"] else 0), str(t["created_at"])))
    shown = set(threads)
    other = conn.execute(
        "SELECT count(*) AS n FROM annotations WHERE document_id = %s AND annotation_type = 'comment' "
        "AND parent_id IS NULL AND NOT (annotation_id = ANY(%s))",
        (doc["document_id"], list(shown)),
    ).fetchone()["n"]
    return {"document_id": doc["document_id"], "version_id": vid, "version_number": number,
            "is_current": vid == doc["current_version_id"], "threads": ordered, "on_other_versions": other}


def add_comment(conn, document_id: str, member_id: str | None, *, body: str, version_id: str | None = None,
                page: int | None = None, rects: list[dict] | None = None, quote: str = "",
                parent_id: str | None = None) -> dict:
    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "read")
    if member_id is None:
        raise EditError(400, "Sign in to comment")
    body = (body or "").strip()
    if not body:
        raise EditError(422, "Write a comment")
    if len(body) > MAX_BODY:
        raise EditError(422, f"Comments are limited to {MAX_BODY} characters")
    if parent_id:
        parent = _row(conn, doc, parent_id)
        if parent["parent_id"] is not None:
            raise EditError(422, "Reply to the first comment of the thread")
        vid, page, clean, quote = parent["version_id"], parent["page_number"], [], ""
    else:
        vid = _version_of(conn, doc, version_id)
        if not page or page < 1:
            raise EditError(422, "A comment needs the page it is on")
        clean = _clean_rects(rects or [])
        quote = (quote or "").strip()[:MAX_QUOTE]
    cid = f"CMT-{uuid.uuid4().hex[:12].upper()}"
    conn.execute(
        """INSERT INTO annotations (annotation_id, document_id, version_id, annotation_type, author_id, author_name,
                                    page_number, start_offset, end_offset, quoted_text, text_hash, content, rects, parent_id)
           VALUES (%s, %s, %s, 'comment', %s, %s, %s, 0, 0, %s, %s, %s, %s::jsonb, %s)""",
        (cid, doc["document_id"], vid, member_id, _member_name(conn, member_id), page, quote,
         hashlib.sha256(quote.encode()).hexdigest()[:64], body, json.dumps(clean), parent_id),
    )
    record_event(conn, doc["document_id"], member_id, "comment.reply" if parent_id else "comment.add", vid,
                 {"comment_id": cid, "parent_id": parent_id, "page": page})
    conn.commit()
    row = _one(conn, "SELECT a.*, NULL AS resolved_by_name FROM annotations a WHERE annotation_id = %s", (cid,))
    return _public(row)


def set_status(conn, document_id: str, member_id: str | None, comment_id: str, status: str) -> dict:
    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "read")
    row = _row(conn, doc, comment_id)
    if row["parent_id"] is not None:
        raise EditError(422, "Resolve the thread, not a reply")
    if row["author_id"] != member_id:
        _require(conn, member_id, doc, "edit")
    if status not in ("open", "resolved"):
        raise EditError(422, "status must be open or resolved")
    if status == "resolved":
        conn.execute("UPDATE annotations SET status = 'resolved', resolved_by_member_id = %s, resolved_at = now(), "
                     "updated_at = now() WHERE annotation_id = %s", (member_id, comment_id))
    else:
        conn.execute("UPDATE annotations SET status = 'active', resolved_by_member_id = NULL, resolved_at = NULL, "
                     "updated_at = now() WHERE annotation_id = %s", (comment_id,))
    record_event(conn, doc["document_id"], member_id, f"comment.{'resolve' if status == 'resolved' else 'reopen'}",
                 row["version_id"], {"comment_id": comment_id})
    conn.commit()
    row = _one(conn, """SELECT a.*, r.name AS resolved_by_name FROM annotations a
                        LEFT JOIN members r ON r.member_id = a.resolved_by_member_id WHERE annotation_id = %s""", (comment_id,))
    return _public(row)


def delete_comment(conn, document_id: str, member_id: str | None, comment_id: str) -> None:
    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "read")
    row = _row(conn, doc, comment_id)
    if row["author_id"] != member_id:
        try:
            _require(conn, member_id, doc, "manage")
        except EditError as exc:
            raise EditError(403, "Only the author can delete a comment") from exc
    conn.execute("DELETE FROM annotations WHERE annotation_id = %s", (comment_id,))
    record_event(conn, doc["document_id"], member_id, "comment.delete", row["version_id"],
                 {"comment_id": comment_id, "parent_id": row["parent_id"]})
    conn.commit()
