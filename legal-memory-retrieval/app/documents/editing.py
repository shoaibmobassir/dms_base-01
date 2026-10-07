"""In-browser editing, file-based versions, locks and compare (plan 16, E1–E2).

The browser edits *paragraphs* of the current version; the server writes those edits
into the version's own file, so everything the editor did not touch keeps its exact
Word formatting:

    edit model   the file's body paragraphs as they read with every change accepted →
                 [{pid, style, text, runs, pending?, locked?}]; pending changes of other
                 reviewers stay in the file and lock their paragraph (plan 18)
    save         file + ops → Word tracked changes by the signed-in member
                 (text: ``app/drafting/docx_tracked.py``; bold/italic/underline and
                 paragraph style: ``app/documents/docx_format.py``) → stored as the next
                 version; the accepted text is what gets indexed for search
    clean save   the same, with every change accepted

Documents without an original Word file (text-only corpus entries) are edited as text
and saved as a text version. PDFs are view-only here (annotate in the viewer).

One person edits at a time: ``document_locks`` (TTL, heartbeat). A save must be based
on the current version — a stale base is refused, never merged silently. Authors always
come from the session, never from the request.
"""
from __future__ import annotations

import difflib
import io
import re
import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app import access
from app.audit import events as audit

log = logging.getLogger(__name__)

# Short enough that a lock left by a closed or crashed browser clears within minutes;
# the open editor renews it every 90 s.
LOCK_TTL_SECONDS = 5 * 60
MAX_OPS = 5000
MAX_OP_TEXT = 20_000
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class EditError(Exception):
    def __init__(self, status: int, detail: str, extra: dict | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.extra = extra or {}


def _one(conn, sql: str, params: tuple | dict = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── document, access, file ───────────────────────────────────────────────────

def _document(conn, document_id: str) -> dict:
    doc = _one(conn, "SELECT document_id, matter_id, title, current_version_id, source_uri, mime_type, client_id "
                     "FROM documents WHERE document_id = %s", (document_id,))
    if doc is None:
        raise EditError(404, "Document not found or access denied")
    return doc


def _require(conn, member_id: str | None, doc: dict, level: str) -> str:
    """The member's level on this document (matter access narrowed by document privacy)."""
    try:
        return access.require_document_level(conn, member_id, doc["document_id"], level, via="editor")["level"]
    except access.AccessError as exc:
        raise EditError(404 if exc.status == 404 else exc.status,
                        "Document not found or access denied" if exc.status == 404 else "You can view but not edit this document") from exc


def _member_name(conn, member_id: str | None) -> str:
    if member_id is None:
        return "Precentis user"
    row = _one(conn, "SELECT name FROM members WHERE member_id = %s", (member_id,))
    return row["name"] if row else member_id


def _version(conn, document_id: str, version_id: str | None) -> dict | None:
    """One version of the document; a purged version is gone (410) for every use that needs its content."""
    if not version_id:
        return None
    row = _one(conn, "SELECT version_id, version_number, storage_uri, mime_type, body, author_name, "
                     "created_by_member_id, created_at, change_summary, deleted_at FROM document_versions "
                     "WHERE document_id = %s AND version_id = %s", (document_id, version_id))
    if row and row["deleted_at"] is not None:
        raise EditError(410, f"Version {row['version_number']} was deleted and cannot be opened, compared or restored")
    return row


def _file_of(doc: dict, ver: dict | None) -> tuple[bytes | None, str]:
    """(bytes, kind) of a version's original file; kind docx | pdf | other | none."""
    from app.storage.object_store import get_object_store

    uri = (ver or {}).get("storage_uri") or doc.get("source_uri")
    if not uri:
        return None, "none"
    try:
        data = get_object_store().get(uri)
    except (FileNotFoundError, OSError):
        return None, "none"
    if data[:5] == b"%PDF-":
        return data, "pdf"
    if data[:2] == b"PK":  # a zip: Word only if python-docx can open it
        try:
            from docx import Document

            Document(io.BytesIO(data))
            return data, "docx"
        except Exception:
            return data, "other"
    return data, "other"


def _zip_has_revisions(data: bytes) -> bool:
    from app.documents.docx_review import has_revisions

    return has_revisions(data)


def _accepted(data: bytes) -> bytes:
    """The file with every tracked change accepted — text, moves, formatting, paragraph marks."""
    from app.documents.docx_review import accept_everything

    return accept_everything(data)


# Private marker on body paragraphs while a save runs (removed before the file is written):
# lets later passes tell a paragraph that was there from copies this save inserted after it.
PCT_PID = "{urn:precentis:edit}pid"


def _tag_paragraphs(data: bytes) -> bytes:
    from app.documents.docx_review import Package, q

    pkg = Package(data)
    for i, p in enumerate(pkg.document.find(q("body")).findall(q("p"))):
        p.set(PCT_PID, str(i))
    pkg.set_xml("word/document.xml", pkg.document)
    return pkg.save()


def _finish_tagged(data: bytes, drop: set[int]) -> bytes:
    """After a save: remove own inserted paragraphs the editor deleted; on paragraphs this save
    inserted, drop identity and revision marks copied from the paragraph they follow; untag."""
    from app.documents.docx_review import W14, Package, q

    pkg = Package(data)
    body = pkg.document.find(q("body"))
    seen: set[str] = set()
    for p in list(body.findall(q("p"))):
        tag = p.get(PCT_PID)
        if tag is None:
            continue
        del p.attrib[PCT_PID]
        if tag not in seen:
            seen.add(tag)
            if int(tag) in drop:
                body.remove(p)
            continue
        for name in ("paraId", "textId"):
            p.attrib.pop(f"{{{W14}}}{name}", None)
        for change in list(p.iter(q("pPrChange"), q("rPrChange"))):
            change.getparent().remove(change)
    pkg.set_xml("word/document.xml", pkg.document)
    return pkg.save()


def _final_runs(p) -> list[dict]:
    """A paragraph's runs as they read with every change accepted (for paragraphs with pending changes)."""
    from docx.text.run import Run

    from app.documents.docx_review import q

    out: list[dict] = []
    for r in p._p.iter(q("r")):
        if any(a.tag in (q("del"), q("moveFrom")) for a in r.iterancestors()):
            continue
        run = Run(r, p)
        text = run.text
        if not text:
            continue
        flags = (bool(run.bold), bool(run.italic), bool(run.underline))
        if out and (out[-1]["bold"], out[-1]["italic"], out[-1]["underline"]) == flags:
            out[-1]["text"] += text
        else:
            out.append({"text": text, "bold": flags[0], "italic": flags[1], "underline": flags[2]})
    return out


LOCKING_TYPES = ("paragraph_delete", "move_from")


def _review_paragraphs(data: bytes, me: str | None) -> tuple[list[dict], dict]:
    """The edit model of a Word file *with* its pending changes: each body paragraph as it reads
    in the Final view, the changes still pending in it, and whether it is locked for this
    member (someone else's pending changes, or a pending deletion)."""
    from docx import Document

    from app.documents.docx_review import paragraph_pending, read_revisions
    from app.ingest.extractors.docx import style_namer

    document = Document(io.BytesIO(data))
    style_of = style_namer(document)
    revs = read_revisions(data)
    pending = paragraph_pending(data, revs)
    summary = {"total": len(revs), "people": sorted({r.author for r in revs})}  # tables included
    out = []
    for i, p in enumerate(document.paragraphs):
        pend = pending.get(i)
        if not pend:
            runs = [{"text": r.text, "bold": bool(r.bold), "italic": bool(r.italic), "underline": bool(r.underline)}
                    for r in p.runs if r.text]
            out.append({"pid": i, "style": style_of(p) or "Normal", "text": p.text, "runs": runs})
            continue
        runs = _final_runs(p)
        others = sorted({x["author"] for x in pend if x["author"] != me})
        deleting = any(t in LOCKING_TYPES for x in pend for t in x["types"])
        out.append({"pid": i, "style": style_of(p) or "Normal", "text": "".join(r["text"] for r in runs), "runs": runs,
                    "pending": pend, "locked": bool(others) or deleting,
                    "locked_reason": "others" if others else ("deleted" if deleting else None)})
    return out, summary


def _docx_paragraphs(data: bytes) -> list[dict]:
    from docx import Document

    from app.ingest.extractors.docx import style_namer

    document = Document(io.BytesIO(data))
    style_of = style_namer(document)
    out = []
    for i, p in enumerate(document.paragraphs):
        runs = [{"text": r.text, "bold": bool(r.bold), "italic": bool(r.italic), "underline": bool(r.underline)}
                for r in p.runs if r.text]
        out.append({"pid": i, "style": style_of(p) or "Normal", "text": p.text, "runs": runs})
    return out


def _text_paragraphs(body: str) -> list[dict]:
    parts = [p.strip() for p in (body or "").replace("\r", "").split("\n")]
    return [{"pid": i, "style": "Normal", "text": t, "runs": [{"text": t, "bold": False, "italic": False, "underline": False}] if t else []}
            for i, t in enumerate(parts)]


# ── events and locks ─────────────────────────────────────────────────────────

def record_event(conn, document_id: str, member_id: str | None, action: str, version_id: str | None = None,
                 detail: dict | None = None) -> None:
    import json

    conn.execute(
        "INSERT INTO document_events (document_id, version_id, member_id, action, detail) VALUES (%s, %s, %s, %s, %s::jsonb)",
        (document_id, version_id, member_id, action, json.dumps(detail or {}, default=str)),
    )


def lock_status(conn, document_id: str) -> dict | None:
    """The live lock (holder, source, times) — never the token."""
    row = _lock_row(conn, document_id)
    if row:
        row.pop("lock_token", None)
    return row


def _lock_row(conn, document_id: str) -> dict | None:
    return _one(conn, """
        SELECT l.member_id, m.name, l.source, l.acquired_at, l.expires_at, l.lock_token
        FROM document_locks l JOIN members m USING (member_id)
        WHERE l.document_id = %s AND l.expires_at > now()""", (document_id,))


def _public_lock(row: dict) -> dict:
    return {k: v for k, v in row.items() if k != "lock_token"}


def acquire_lock(conn, document_id: str, member_id: str | None, source: str = "web",
                 token: str | None = None, takeover: bool = False) -> dict:
    """Open the document for editing in one window.

    Each window holds its own token. The same window re-acquiring (reload) presents its
    token and keeps the lock. Another window of the same person, or another person, gets
    409 unless it takes over: anyone may take over from themselves, and matter managers
    from others. The window that lost the lock finds out on its next heartbeat.
    """
    doc = _document(conn, document_id)
    level = _require(conn, member_id, doc, "edit")
    if member_id is None:
        raise EditError(400, "Sign in to edit documents")
    held = _lock_row(conn, document_id)
    same_window = held is not None and held["member_id"] == member_id and token is not None and token == held["lock_token"]
    if held and not same_window:
        mine = held["member_id"] == member_id
        if not takeover:
            if mine:
                raise EditError(409, "You are editing this document in another window",
                                {"lock": _public_lock(held), "reason": "held_by_you_elsewhere"})
            raise EditError(409, f"{held['name']} is editing this document",
                            {"lock": _public_lock(held), "reason": "held", "can_take_over": level == "manage"})
        if not mine and level != "manage":
            raise EditError(403, "Only a matter manager can take over someone else's editing")
    new_token = token if same_window else secrets.token_urlsafe(16)
    expires = _now() + timedelta(seconds=LOCK_TTL_SECONDS)
    conn.execute(
        """
        INSERT INTO document_locks (document_id, member_id, source, lock_token, expires_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (document_id) DO UPDATE SET member_id = EXCLUDED.member_id, source = EXCLUDED.source,
            lock_token = EXCLUDED.lock_token, acquired_at = now(), expires_at = EXCLUDED.expires_at
        """,
        (document_id, member_id, source, new_token, expires),
    )
    if held and not same_window:
        record_event(conn, document_id, member_id, "lock.takeover",
                     detail={"source": source, "from_member_id": held["member_id"]})
        conn.commit()
        audit.record("document.lock.takeover", member_id=member_id, object_type="document", object_id=document_id,
                     matter_id=doc["matter_id"], detail={"from_member_id": held["member_id"]})
    elif not held:
        record_event(conn, document_id, member_id, "lock", detail={"source": source})
    conn.commit()
    return {"member_id": member_id, "name": _member_name(conn, member_id), "expires_at": expires.isoformat(),
            "source": source, "lock_token": new_token}


def _superseded(held: dict | None) -> EditError:
    who = f"{held['name']} took over editing" if held else "Your editing session ended"
    return EditError(409, f"{who}; your changes are kept as your draft",
                     {"lock": _public_lock(held) if held else None, "reason": "superseded"})


def heartbeat(conn, document_id: str, member_id: str | None, token: str | None = None) -> dict:
    held = _lock_row(conn, document_id)
    if not held or held["member_id"] != member_id or (token is not None and token != held["lock_token"]):
        raise _superseded(held)
    expires = _now() + timedelta(seconds=LOCK_TTL_SECONDS)
    conn.execute("UPDATE document_locks SET expires_at = %s WHERE document_id = %s AND member_id = %s",
                 (expires, document_id, member_id))
    conn.commit()
    return {"member_id": member_id, "expires_at": expires.isoformat()}


def release_lock(conn, document_id: str, member_id: str | None, token: str | None = None) -> None:
    """Release this window's lock (a window that was superseded releases nothing)."""
    if token is not None:
        row = _one(conn, "DELETE FROM document_locks WHERE document_id = %s AND member_id = %s AND lock_token = %s "
                         "RETURNING document_id", (document_id, member_id, token))
    else:
        row = _one(conn, "DELETE FROM document_locks WHERE document_id = %s AND member_id = %s RETURNING document_id",
                   (document_id, member_id))
    if row:
        record_event(conn, document_id, member_id, "unlock")
    conn.commit()


def _check_can_write(conn, document_id: str, member_id: str | None, token: str | None = None) -> None:
    """Saving needs the lock to be free or ours — and, when the window sends its token, this window's."""
    held = _lock_row(conn, document_id)
    if not held:
        return
    if held["member_id"] != member_id:
        raise EditError(409, f"{held['name']} is editing this document", {"lock": _public_lock(held), "reason": "held"})
    if token is not None and token != held["lock_token"]:
        raise _superseded(held)


def _check_draft_window(conn, document_id: str, member_id: str | None, token: str | None) -> None:
    """Drafts are per person: a superseded window of the *same* person must stop writing the draft
    (the window that took over owns it now). Someone else's takeover leaves our draft alone."""
    held = _lock_row(conn, document_id)
    if held and token is not None and held["member_id"] == member_id and token != held["lock_token"]:
        raise _superseded(held)


# ── edit model and drafts ────────────────────────────────────────────────────

def edit_model(conn, document_id: str, member_id: str | None) -> dict:
    doc = _document(conn, document_id)
    level = _require(conn, member_id, doc, "read")
    ver = _version(conn, document_id, doc["current_version_id"])
    data, kind = _file_of(doc, ver)
    styles: list[str] = []
    summary: dict = {}
    if kind == "docx":
        from docx import Document

        from app.documents.docx_format import paragraph_styles

        paragraphs, summary = _review_paragraphs(data, _member_name(conn, member_id) if member_id else None)
        defined = paragraph_styles(Document(io.BytesIO(data)))
        styles = [name for name in EDITOR_STYLES if name in defined]
        mode = "docx"
    elif kind == "pdf":
        paragraphs, mode = [], "pdf"
    else:
        paragraphs = _text_paragraphs((ver or {}).get("body") or "")
        mode = "text"
    draft = _one(conn, "SELECT base_version_id, ops, updated_at FROM document_drafts WHERE document_id = %s AND member_id = %s",
                 (document_id, member_id)) if member_id else None
    return {
        "document_id": document_id,
        "title": doc["title"],
        "matter_id": doc["matter_id"],
        "mode": mode,                      # docx | text | pdf (view-only)
        "editable": mode in ("docx", "text") and access.LEVELS.index(level) >= access.LEVELS.index("edit"),
        "base_version_id": doc["current_version_id"],
        "version_number": (ver or {}).get("version_number"),
        "has_revisions": bool(data) and kind == "docx" and _zip_has_revisions(data),
        # Tracked changes still pending in the file (accept/reject them in the Review panel).
        "pending_changes": summary.get("total", 0),
        "pending_people": summary.get("people", []),
        "paragraphs": paragraphs,
        "styles": styles,                  # paragraph styles the editor may apply (docx only)
        "lock": lock_status(conn, document_id),
        "draft": draft,
    }


def save_draft(conn, document_id: str, member_id: str | None, base_version_id: str, ops: list[dict],
               token: str | None = None) -> dict:
    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "edit")
    _validate_ops(ops)
    _check_draft_window(conn, document_id, member_id, token)
    import json

    conn.execute(
        """
        INSERT INTO document_drafts (document_id, member_id, base_version_id, ops, updated_at)
        VALUES (%s, %s, %s, %s::jsonb, now())
        ON CONFLICT (document_id, member_id) DO UPDATE SET base_version_id = EXCLUDED.base_version_id,
            ops = EXCLUDED.ops, updated_at = now()
        """,
        (document_id, member_id, base_version_id, json.dumps(ops)),
    )
    conn.commit()
    return {"saved_at": _now().isoformat(), "ops": len(ops)}


def discard_draft(conn, document_id: str, member_id: str | None) -> None:
    conn.execute("DELETE FROM document_drafts WHERE document_id = %s AND member_id = %s", (document_id, member_id))
    conn.commit()


TEXT_OPS = ("replace", "delete", "insert_after")
# Paragraph styles the editor offers (when the document defines them).
EDITOR_STYLES = ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3")


def _validate_ops(ops: list[dict]) -> None:
    """Shape checks. ``replace`` / ``insert_after`` may carry ``style`` and ``runs`` (the
    paragraph's text split by bold/italic/underline); ``format`` changes only those."""
    if not isinstance(ops, list) or len(ops) > MAX_OPS:
        raise EditError(422, f"At most {MAX_OPS} edits per save")
    for op in ops:
        if op.get("op") not in (*TEXT_OPS, "format") or not isinstance(op.get("pid"), int) or op["pid"] < 0:
            raise EditError(422, "Each edit needs op (replace, delete, insert_after, format) and a paragraph id")
        if len(str(op.get("text") or "")) > MAX_OP_TEXT:
            raise EditError(422, "A paragraph is too long")
        runs = op.get("runs")
        if runs is not None:
            if op["op"] == "delete" or not isinstance(runs, list):
                raise EditError(422, "runs go with replace, insert_after or format")
            if op["op"] != "format" and "".join(str(r.get("text") or "") for r in runs) != str(op.get("text") or ""):
                raise EditError(422, "The formatted runs must spell the paragraph's text")
        if op["op"] == "format" and op.get("style") is None and runs is None:
            raise EditError(422, "A format edit needs a style or runs")


def _apply_text_ops(paragraphs: list[str], ops: list[dict]) -> list[str]:
    replaced = {op["pid"]: str(op.get("text") or "") for op in ops if op["op"] == "replace"}
    deleted = {op["pid"] for op in ops if op["op"] == "delete"}
    inserts: dict[int, list[str]] = {}
    for op in ops:
        if op["op"] == "insert_after":
            inserts.setdefault(op["pid"], []).append(str(op.get("text") or ""))
    out: list[str] = []
    for i, text in enumerate(paragraphs):
        if i not in deleted:
            out.append(replaced.get(i, text))
        out += inserts.get(i, [])
    return out


# ── save / upload → new version ──────────────────────────────────────────────

def _store_version_file(doc: dict, version_number: int, filename: str, data: bytes, mime: str) -> str:
    from app.config import settings
    from app.storage.object_store import build_storage_key, get_object_store

    key = build_storage_key(tenant_id=settings.tenant_id, client_id=doc.get("client_id") or "unknown",
                            matter_id=doc["matter_id"], document_id=doc["document_id"],
                            version_number=version_number, filename=filename)
    return get_object_store().put(key, data, content_type=mime)


def _store_source_file(doc: dict, version_number: int, filename: str, data: bytes, mime: str) -> str:
    """The file as it was uploaded, beside the version's own (clean) file: ``versions/vNNN/uploaded.<ext>``.

    The store names a version's file ``original.<ext>``, so the raw copy needs its own key.
    """
    from app.config import settings
    from app.storage.object_store import build_storage_key, get_object_store

    key = build_storage_key(tenant_id=settings.tenant_id, client_id=doc.get("client_id") or "unknown",
                            matter_id=doc["matter_id"], document_id=doc["document_id"],
                            version_number=version_number, filename=filename)
    return get_object_store().put(key.rsplit("/", 1)[0] + "/uploaded." + key.rsplit(".", 1)[-1], data, content_type=mime)


def _next_number(conn, document_id: str) -> int:
    row = _one(conn, "SELECT coalesce(max(version_number), 0) + 1 AS n FROM document_versions WHERE document_id = %s", (document_id,))
    return int(row["n"]) if row else 1


def _create(conn, doc: dict, member_id: str | None, *, text: str, note: str, origin: str, label: str | None,
            storage_uri: str | None, mime: str | None, size: int | None, page_spans=None,
            is_clean: bool | None = None, restored_from: str | None = None, source_uri: str | None = None,
            author_name: str | None = None) -> dict:
    from app.documents import create_version, sync_page_count

    author = author_name or _member_name(conn, member_id)
    # Replacing the document's chunks must not interleave with the background embedder
    # writing vectors to them (row locks taken in opposite orders deadlock).
    conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (_INDEX_LOCK + doc["document_id"],))
    try:
        _snapshot_vectors(conn, doc["document_id"])
        version = create_version(
            document_id=doc["document_id"], body=text[:500_000], author_name=author,
            source="edit" if origin in ("editor", "restore") else "upload", version_status="developing", version_label=label,
            change_summary=note or None, storage_uri=storage_uri, page_spans=page_spans,
        )
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_INDEX_LOCK + doc["document_id"],))
    conn.execute(
        "UPDATE document_versions SET created_by_member_id = %s, origin = %s, mime_type = coalesce(%s, mime_type), "
        "file_size_bytes = coalesce(%s, file_size_bytes), is_clean = %s, restored_from_version_id = %s, "
        "source_storage_uri = %s WHERE version_id = %s",
        (member_id, origin, mime, size, is_clean, restored_from, source_uri, version["version_id"]),
    )
    if mime:
        conn.execute("UPDATE documents SET mime_type = %s WHERE document_id = %s", (mime, doc["document_id"]))
    conn.commit()
    sync_page_count(version["version_id"])
    _index_vectors(conn, doc["document_id"], version["version_id"])
    return version


_embedder_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="edit-embed")


def _snapshot_vectors(conn, document_id: str) -> None:
    """Keep the current version's chunk vectors (by text) before the new version replaces
    its chunks — the search index holds only the current version."""
    conn.execute("DROP TABLE IF EXISTS pg_temp.edit_prev_vectors")
    conn.execute(
        """CREATE TEMP TABLE edit_prev_vectors AS
           SELECT DISTINCT ON (md5(text)) md5(text) AS h, embedding
           FROM chunks WHERE document_id = %s AND embedding IS NOT NULL""",
        (document_id,),
    )


def _index_vectors(conn, document_id: str, version_id: str) -> None:
    """Give the new version's chunks their vectors without holding up the save.

    An edit leaves most chunks word-for-word unchanged, so those take the vector of the
    identical chunk from the previous version (the embedder is deterministic on the text).
    The rest are embedded on a background worker; full-text search covers them meanwhile
    and the embedding backfill retries anything that fails.
    """
    # The new chunks are hashed once and joined by hash (the planner's statistics predate
    # these rows, so without this it compares every pair); document_id keeps it on the index.
    conn.execute("ANALYZE pg_temp.edit_prev_vectors")
    conn.execute(
        """UPDATE chunks c SET embedding = p.embedding
           FROM (SELECT chunk_id, md5(text) AS h FROM chunks
                 WHERE document_id = %s AND version_id = %s AND embedding IS NULL) n
           JOIN pg_temp.edit_prev_vectors p ON p.h = n.h
           WHERE c.chunk_id = n.chunk_id""",
        (document_id, version_id),
    )
    conn.execute("DROP TABLE IF EXISTS pg_temp.edit_prev_vectors")
    conn.commit()
    _embedder_pool.submit(_embed_rest, document_id, version_id)


_INDEX_LOCK = "doc-index:"
_EMBED_BATCH = 64


def _embed_rest(document_id: str, version_id: str) -> None:
    """Embed the version's remaining chunks in small batches. Encoding runs unlocked; each
    batch is written under the document's index lock, so a save waits at most one batch.
    Stops when the version's chunks are gone (a newer version replaced them)."""
    try:
        from pgvector import Vector
        from pgvector.psycopg import register_vector

        from app.db.connection import connect
        from app.embeddings.pending import _get_embedder

        embedder = _get_embedder()
        with connect() as conn:
            register_vector(conn)
            while True:
                rows = conn.execute(
                    "SELECT chunk_id, text FROM chunks WHERE document_id = %s AND version_id = %s AND embedding IS NULL "
                    "ORDER BY chunk_id LIMIT %s",
                    (document_id, version_id, _EMBED_BATCH),
                ).fetchall()
                conn.commit()
                if not rows:
                    return
                vectors = embedder.encode([r["text"] for r in rows])
                conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (_INDEX_LOCK + document_id,))
                with conn.cursor() as cur:
                    cur.executemany("UPDATE chunks SET embedding = %s WHERE chunk_id = %s AND version_id = %s",
                                    [(Vector(v), r["chunk_id"], version_id) for r, v in zip(rows, vectors)])
                conn.commit()
    except Exception:
        log.exception("embedding after an edit failed for %s; the backfill will retry", document_id)


def wait_for_indexing(timeout: float = 120.0) -> None:
    """Block until queued embeddings have run (tests and evals)."""
    _embedder_pool.submit(lambda: None).result(timeout=timeout)


def _edit_docx(data: bytes, ops: list[dict], author: str, mode: str = "tracked") -> tuple[bytes, dict]:
    """The editor's ops written into a Word file as tracked changes by ``author`` (no database):
    other reviewers' pending changes stay; paragraphs holding them cannot be edited."""
    from docx import Document

    from app.documents import docx_review
    from app.documents.docx_format import apply_formatting, paragraph_styles, wants_formatting
    from app.drafting.docx_tracked import apply_tracked_changes

    # Work on the file as it is: other reviewers' pending changes stay exactly where they are.
    base = data
    revs = docx_review.read_revisions(base)
    pending = docx_review.paragraph_pending(base, revs)
    touched = {op["pid"] for op in ops if op["op"] in ("replace", "delete", "format")}
    locked = sorted(pid for pid in touched if pid in pending and (
        any(x["author"] != author for x in pending[pid])
        or any(t in LOCKING_TYPES for x in pending[pid] for t in x["types"])))
    if locked:
        names = sorted({x["author"] for pid in locked for x in pending[pid] if x["author"] != author})
        raise EditError(422, "Accept or reject the pending changes in these paragraphs first"
                        + (f" (by {', '.join(names)})" if names else ""), {"locked_pids": locked})
    own = sorted(pid for pid in touched if pid in pending)
    own_inserted = {pid for pid in own if any("paragraph_insert" in x["types"] for x in pending[pid])}
    if own:
        # Your own earlier changes in a paragraph you edit again are redone against its original text.
        keys = [r.key for r in revs if r.pid in set(own) and r.author == author
                and r.type not in ("paragraph_insert", "paragraph_delete")]
        # A paragraph only restyled keeps its text: its final text is written back as it read.
        texted = {op["pid"] for op in ops if op["op"] in TEXT_OPS}
        restyled = [pid for pid in own if pid not in texted]
        if restyled:
            paras = docx_review._body(docx_review.Package(base)).findall(docx_review.q("p"))
            ops = [{"op": "replace", "pid": pid, "text": docx_review._final_text(paras[pid])} for pid in restyled] + ops
        base, _ = docx_review.resolve(base, keys, accept=False)
    base = _tag_paragraphs(base)
    base_doc = Document(io.BytesIO(base))
    n_paras = len(base_doc.paragraphs)
    if any(op["pid"] >= n_paras for op in ops):
        raise EditError(422, "An edit refers to a paragraph that does not exist")
    styles = paragraph_styles(base_doc)
    unknown = {op["style"] for op in ops if op.get("style") is not None and op["style"] not in styles}
    if unknown:
        raise EditError(422, f"This document has no paragraph style {', '.join(sorted(unknown))}")
    tracked, stats = apply_tracked_changes(base, [op for op in ops if op["op"] in TEXT_OPS], author=author)
    if any(wants_formatting(op) for op in ops):
        tracked, fstats = apply_formatting(tracked, ops, author=author)
        stats = {**stats, **fstats}
    # A paragraph you inserted earlier and now delete simply goes (it never existed for others).
    out = _finish_tagged(tracked, {op["pid"] for op in ops if op["op"] == "delete" and op["pid"] in own_inserted})
    if mode == "clean":  # untracked: accept your own changes only, never other reviewers'
        out, _ = docx_review.resolve(out, docx_review.keys_by(out, authors=[author]), accept=True)
    return out, stats


def _amendable(conn, doc: dict, member_id: str | None, turn_id: str | None) -> dict | None:
    """The current version, when more edits accepted from the same Assistant turn should amend it rather than make
    another version (plan 22 W2a, W-R9): it was made by this person from this turn, is still the newest, and nobody
    has commented on it or reviewed it yet. Anything else makes a new version, so nothing is rewritten under someone
    else's feet."""
    if not turn_id or not member_id:
        return None
    head = _one(conn, """SELECT v.* FROM document_versions v WHERE v.version_id = %s""", (doc["current_version_id"],))
    if not head or head.get("source_turn_id") != turn_id or head.get("created_by_member_id") != member_id:
        return None
    if head.get("origin") != "assistant" or head.get("deleted_at") is not None:
        return None
    attached = _one(conn, """SELECT (EXISTS (SELECT 1 FROM annotations WHERE version_id = %(v)s)
                                     OR EXISTS (SELECT 1 FROM findings WHERE version_id = %(v)s)) AS used""",
                    {"v": head["version_id"]})
    return None if attached and attached["used"] else head


def _amend(conn, doc: dict, head: dict, member_id: str, *, text: str, note: str, storage_uri: str | None,
           size: int | None, page_spans=None, is_clean: bool | None = None) -> dict:
    """Rewrite the newest version in place (same number): its text, file, and index."""
    from app.documents import content_sha256, save_canonical_blocks, stored_headings, sync_page_count
    from app.documents.canonical import parse_canonical_blocks
    from app.documents.hierarchical_chunks import build_hierarchical_chunks, save_version_chunks

    vid = head["version_id"]
    summary = head.get("change_summary") or ""
    if note and note not in summary:
        summary = f"{summary}; {note.removeprefix('Assistant: ')}" if summary else note
    conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (_INDEX_LOCK + doc["document_id"],))
    try:
        _snapshot_vectors(conn, doc["document_id"])
        conn.execute(
            """UPDATE document_versions SET body = %s, content_sha256 = %s, storage_uri = coalesce(%s, storage_uri),
                      file_size_bytes = coalesce(%s, file_size_bytes), change_summary = %s, is_clean = %s
               WHERE version_id = %s""",
            (text[:500_000], content_sha256(text[:500_000]), storage_uri, size, summary, is_clean, vid))
        conn.execute("UPDATE documents SET body = %s, updated_at = now() WHERE document_id = %s",
                     (text[:500_000], doc["document_id"]))
        for table in ("document_blocks", "document_intelligence", "evidence_anchors"):
            conn.execute(f"DELETE FROM {table} WHERE version_id = %s", (vid,))
        conn.execute("DELETE FROM version_diffs WHERE source_version_id = %s OR target_version_id = %s", (vid, vid))
        conn.commit()
        blocks = parse_canonical_blocks(text[:500_000], doc["document_id"], vid, page_spans=page_spans,
                                        headings=stored_headings(storage_uri or head.get("storage_uri")))
        save_canonical_blocks(blocks)
        save_version_chunks(build_hierarchical_chunks(blocks, document_id=doc["document_id"], version_id=vid,
                                                      matter_id=doc["matter_id"], folder_path=doc.get("folder_path") or ""))
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_INDEX_LOCK + doc["document_id"],))
    conn.commit()
    sync_page_count(vid)
    _index_vectors(conn, doc["document_id"], vid)
    return {**head, "change_summary": summary}


def _add_revision_authors(conn, doc: dict, version_id: str, marked: bytes) -> None:
    """An amended version: add this save's changes to who-changed-what (the earlier steps are already counted)."""
    from app.documents import docx_review
    from app.documents.review import _members_by_name

    people = docx_review.contributors(marked)
    names = _members_by_name(conn, [p["author"] for p in people])
    for p in people:
        conn.execute(
            """INSERT INTO document_revision_authors (version_id, document_id, author_name, member_id, insertions, deletions,
                   formats, moves, paragraphs, words_added, words_removed, comments, replies, first_at, last_at)
               VALUES (%(v)s, %(d)s, %(a)s, %(m)s, %(ins)s, %(del)s, %(fmt)s, %(mov)s, %(par)s, %(wa)s, %(wr)s, 0, 0, %(f)s, %(l)s)
               ON CONFLICT (version_id, author_name) DO UPDATE SET
                   insertions = document_revision_authors.insertions + EXCLUDED.insertions,
                   deletions = document_revision_authors.deletions + EXCLUDED.deletions,
                   formats = document_revision_authors.formats + EXCLUDED.formats,
                   moves = document_revision_authors.moves + EXCLUDED.moves,
                   paragraphs = document_revision_authors.paragraphs + EXCLUDED.paragraphs,
                   words_added = document_revision_authors.words_added + EXCLUDED.words_added,
                   words_removed = document_revision_authors.words_removed + EXCLUDED.words_removed,
                   last_at = greatest(document_revision_authors.last_at, EXCLUDED.last_at)""",
            {"v": version_id, "d": doc["document_id"], "a": p["author"], "m": names.get(p["author"].lower()),
             "ins": p["insertions"], "del": p["deletions"], "fmt": p["formats"], "mov": p["moves"], "par": p["paragraphs"],
             "wa": p["words_added"], "wr": p["words_removed"], "f": p["first_at"], "l": p["last_at"]})
    conn.commit()


def save_edits(conn, document_id: str, member_id: str | None, base_version_id: str, ops: list[dict],
               note: str = "", mode: str = "tracked", token: str | None = None, origin: str = "editor",
               turn_id: str | None = None) -> dict:
    """Write the editor's paragraph edits as the next version (see module docstring).

    ``origin`` names who made it ("editor", "assistant"); edits accepted from one Assistant turn (``turn_id``) amend
    that turn's version while it is still the newest (see ``_amendable``)."""
    from app.ingest.extractors.dispatch import extract_from_bytes

    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "edit")
    if member_id is None:
        raise EditError(400, "Sign in to edit documents")
    _validate_ops(ops)
    if not ops:
        raise EditError(422, "No changes to save")
    _check_can_write(conn, document_id, member_id, token)
    if base_version_id != doc["current_version_id"]:
        raise EditError(409, "Someone saved a newer version while you were editing; reload to see it",
                        {"current_version_id": doc["current_version_id"]})
    if mode not in ("tracked", "clean"):
        raise EditError(422, "mode must be tracked or clean")

    ver = _version(conn, document_id, base_version_id)
    data, kind = _file_of(doc, ver)
    author = _member_name(conn, member_id)
    head = _amendable(conn, doc, member_id, turn_id) if origin == "assistant" else None
    number = head["version_number"] if head else _next_number(conn, document_id)
    if kind == "docx":
        from app.documents import docx_review
        from app.documents.review import index_version, sync_comments

        out, stats = _edit_docx(data, ops, author, mode)
        # The stored file is the clean document; what this save changed is the difference to its parent. A file
        # that still carries someone else's pending changes (an old row not yet cleaned) keeps them: accepting them
        # here would decide, for the reviewer, that their proposals are in.
        clean = not docx_review.has_revisions(data)
        marked = out  # this save as tracked changes by ``author``: the record of who changed what
        if clean:
            out = docx_review.accept_everything(out)
            mode = "clean"
        out = sync_comments(conn, doc, out)
        name = Path(doc["title"]).stem + ".docx"
        uri = _store_version_file(doc, number, name, out, DOCX_MIME)
        extracted = extract_from_bytes(name, docx_review.accept_everything(out))
        if head:
            version = _amend(conn, doc, head, member_id, text=extracted.text, note=note, storage_uri=uri, size=len(out),
                             page_spans=extracted.pages, is_clean=clean)
            _add_revision_authors(conn, doc, version["version_id"], marked)
        else:
            version = _create(conn, doc, member_id, text=extracted.text, note=note, origin=origin, label=None,
                              storage_uri=uri, mime=DOCX_MIME, size=len(out), page_spans=extracted.pages,
                              is_clean=clean)
            index_version(conn, doc, version["version_id"], marked if clean else out)
    elif kind == "pdf":
        raise EditError(422, "PDFs cannot be edited in the browser; upload a Word version to edit the text")
    else:
        paras = [p["text"] for p in _text_paragraphs((ver or {}).get("body") or "")]
        if any(op["pid"] >= len(paras) for op in ops):
            raise EditError(422, "An edit refers to a paragraph that does not exist")
        ops = [op for op in ops if op["op"] in TEXT_OPS]  # text versions carry no formatting
        if not ops:
            raise EditError(422, "Text-only documents have no formatting to change")
        new_text = "\n".join(_apply_text_ops(paras, ops))
        stats = {"replaced": sum(o["op"] == "replace" for o in ops), "deleted": sum(o["op"] == "delete" for o in ops),
                 "inserted": sum(o["op"] == "insert_after" for o in ops)}
        if head:
            version = _amend(conn, doc, head, member_id, text=new_text, note=note, storage_uri=None, size=None)
        else:
            version = _create(conn, doc, member_id, text=new_text, note=note, origin=origin, label=None,
                              storage_uri=None, mime=None, size=None)
    if turn_id and not head:
        conn.execute("UPDATE document_versions SET source_turn_id = %s WHERE version_id = %s", (turn_id, version["version_id"]))
    if origin == "editor":
        conn.execute("DELETE FROM document_drafts WHERE document_id = %s AND member_id = %s", (document_id, member_id))
    from app.observability.metrics import WORKBENCH_SAVES

    WORKBENCH_SAVES.labels(path="assistant_amend" if head else ("assistant" if origin == "assistant" else "paragraph_editor")).inc()
    record_event(conn, document_id, member_id, "edit.amend" if head else "edit.save", version["version_id"],
                 {"mode": mode, **stats, "note": note, "origin": origin})
    conn.commit()
    audit.record("document.edit", member_id=member_id, object_type="document", object_id=document_id,
                 matter_id=doc["matter_id"], detail={"version_id": version["version_id"], "mode": mode, "origin": origin,
                                                     "amended": bool(head), **stats})
    return {"version_id": version["version_id"], "version_number": version["version_number"], "stats": stats, "mode": mode,
            "amended": bool(head)}


def save_docx(conn, document_id: str, member_id: str | None, base_version_id: str, data: bytes, note: str = "",
              token: str | None = None) -> dict:
    """The full Word editor's save (plan 22, W2b): the edited .docx becomes the next version.

    The editor writes tracked changes in the browser; their author and date are re-stamped here for every change that
    was not already in the base version (``docx_restamp``), so a browser can never credit a change to someone else.
    As with every save, the stored file is the clean document when the base was clean, and the tracked form is kept
    only as the record of who changed what.
    """
    from app.config import settings
    from app.documents import docx_review
    from app.documents.docx_restamp import restamp_new_revisions
    from app.documents.review import index_version, sync_comments
    from app.ingest.extractors.dispatch import extract_from_bytes

    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "edit")
    if member_id is None:
        raise EditError(400, "Sign in to edit documents")
    if not data or data[:2] != b"PK":
        raise EditError(422, "The editor did not send a Word file")
    if len(data) > settings.max_upload_file_mb * 1024 * 1024:
        raise EditError(413, f"Files are limited to {settings.max_upload_file_mb} MB")
    _check_can_write(conn, document_id, member_id, token)
    if base_version_id != doc["current_version_id"]:
        raise EditError(409, "Someone saved a newer version while you were editing; reload to see it",
                        {"current_version_id": doc["current_version_id"]})
    ver = _version(conn, document_id, base_version_id)
    base, kind = _file_of(doc, ver)
    if kind not in ("docx", "none"):
        raise EditError(422, "Only Word documents open in the full editor")
    author = _member_name(conn, member_id)
    marked, restamped = restamp_new_revisions(base, data, author)
    clean = base is None or not docx_review.has_revisions(base)
    out = docx_review.accept_everything(marked) if clean else marked
    out = sync_comments(conn, doc, out)
    number = _next_number(conn, document_id)
    name = Path(doc["title"]).stem + ".docx"
    uri = _store_version_file(doc, number, name, out, DOCX_MIME)
    extracted = extract_from_bytes(name, docx_review.accept_everything(out))
    version = _create(conn, doc, member_id, text=extracted.text, note=note, origin="editor", label=None,
                      storage_uri=uri, mime=DOCX_MIME, size=len(out), page_spans=extracted.pages, is_clean=clean)
    index_version(conn, doc, version["version_id"], marked if clean else out)
    conn.execute("DELETE FROM document_drafts WHERE document_id = %s AND member_id = %s", (document_id, member_id))
    conn.commit()
    discard_docx_draft(conn, document_id, member_id)
    from app.observability.metrics import WORKBENCH_SAVES

    WORKBENCH_SAVES.labels(path="word_editor").inc()
    record_event(conn, document_id, member_id, "edit.save", version["version_id"],
                 {"mode": "full-editor", "note": note, "changes": restamped})
    conn.commit()
    audit.record("document.edit", member_id=member_id, object_type="document", object_id=document_id,
                 matter_id=doc["matter_id"], detail={"version_id": version["version_id"], "mode": "full-editor",
                                                     "changes": restamped})
    return {"version_id": version["version_id"], "version_number": version["version_number"], "changes": restamped}


def _docx_draft_key(document_id: str, member_id: str) -> str:
    from app.config import settings
    from app.storage.object_store import sanitize_segment

    return f"{sanitize_segment(settings.tenant_id)}/drafts/{sanitize_segment(document_id)}/{sanitize_segment(member_id)}.docx"


def save_docx_draft(conn, document_id: str, member_id: str | None, base_version_id: str, data: bytes,
                    token: str | None = None) -> dict:
    """Keep the Word editor's unsaved file for this person (autosave). Nothing becomes a version."""
    from app.config import settings
    from app.storage.object_store import get_object_store

    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "edit")
    if member_id is None:
        raise EditError(400, "Sign in to edit documents")
    if not data or data[:2] != b"PK":
        raise EditError(422, "The editor did not send a Word file")
    if len(data) > settings.max_upload_file_mb * 1024 * 1024:
        raise EditError(413, f"Files are limited to {settings.max_upload_file_mb} MB")
    _check_draft_window(conn, document_id, member_id, token)
    uri = get_object_store().put(_docx_draft_key(document_id, member_id), data, content_type=DOCX_MIME)
    conn.execute(
        """INSERT INTO document_docx_drafts (document_id, member_id, base_version_id, storage_uri, size_bytes, updated_at)
           VALUES (%s, %s, %s, %s, %s, now())
           ON CONFLICT (document_id, member_id) DO UPDATE SET base_version_id = EXCLUDED.base_version_id,
               storage_uri = EXCLUDED.storage_uri, size_bytes = EXCLUDED.size_bytes, updated_at = now()""",
        (document_id, member_id, base_version_id, uri, len(data)))
    conn.commit()
    return {"saved_at": _now().isoformat(), "bytes": len(data)}


def docx_draft_info(conn, document_id: str, member_id: str | None) -> dict | None:
    """The person's saved draft, and whether it still sits on the current version."""
    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "edit")
    row = _one(conn, "SELECT base_version_id, size_bytes, updated_at FROM document_docx_drafts "
                     "WHERE document_id = %s AND member_id = %s", (document_id, member_id))
    if row is None:
        return None
    return {**row, "current": row["base_version_id"] == doc["current_version_id"]}


def read_docx_draft(conn, document_id: str, member_id: str | None) -> bytes:
    from app.storage.object_store import get_object_store

    info = docx_draft_info(conn, document_id, member_id)
    if info is None or not info["current"]:
        raise EditError(404, "No draft on the current version")
    try:
        return get_object_store().get(_docx_draft_key(document_id, member_id))
    except FileNotFoundError:
        raise EditError(404, "No draft on the current version") from None


def discard_docx_draft(conn, document_id: str, member_id: str | None) -> None:
    from app.storage.object_store import get_object_store

    if member_id is None:
        return
    gone = _one(conn, "DELETE FROM document_docx_drafts WHERE document_id = %s AND member_id = %s RETURNING storage_uri",
                (document_id, member_id))
    conn.commit()
    if gone:
        try:
            get_object_store().delete(gone["storage_uri"])
        except FileNotFoundError:
            pass


def upload_version(conn, document_id: str, member_id: str | None, filename: str, data: bytes,
                   base_version_id: str | None, note: str = "", label: str | None = None,
                   token: str | None = None) -> dict:
    """A file the member uploads becomes the next version of the document."""
    from app.config import settings
    from app.ingest.extractors.dispatch import extract_from_bytes
    from app.storage.object_store import guess_mime

    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "edit")
    if member_id is None:
        raise EditError(400, "Sign in to upload versions")
    if not data:
        raise EditError(422, "The file is empty")
    if len(data) > settings.max_upload_file_mb * 1024 * 1024:
        raise EditError(413, f"Files are limited to {settings.max_upload_file_mb} MB")
    suffix = Path(filename or "").suffix.lower()
    if suffix not in (".docx", ".pdf", ".txt", ".md"):
        raise EditError(415, "Upload a .docx, .pdf or .txt file")
    _check_can_write(conn, document_id, member_id, token)
    if base_version_id and base_version_id != doc["current_version_id"]:
        raise EditError(409, "A newer version was saved since you opened this document; compare before uploading",
                        {"current_version_id": doc["current_version_id"]})
    if suffix == ".docx" and _zip_has_revisions(data):
        return _import_reviewed(conn, doc, member_id, filename, data, note, label)
    extracted = extract_from_bytes(filename, _accepted(data) if suffix == ".docx" else data)
    number = _next_number(conn, document_id)
    mime = guess_mime(filename)
    uri = _store_version_file(doc, number, filename, data, mime)
    version = _create(conn, doc, member_id, text=extracted.text, note=note, origin="upload", label=label,
                      storage_uri=uri, mime=mime, size=len(data), page_spans=extracted.pages,
                      is_clean=True if suffix == ".docx" else None)
    if suffix == ".docx":  # who changed what in the file, and its Word comments
        from app.documents.review import index_version

        index_version(conn, doc, version["version_id"], data)
    record_event(conn, document_id, member_id, "version.upload", version["version_id"], {"filename": filename, "note": note})
    conn.commit()
    audit.record("document.version.upload", member_id=member_id, object_type="document", object_id=document_id,
                 matter_id=doc["matter_id"], detail={"version_id": version["version_id"], "filename": filename})
    return {"version_id": version["version_id"], "version_number": version["version_number"]}


def copy_from(conn, document_id: str, member_id: str | None, source_document_id: str, source_version_id: str | None,
              base_version_id: str | None, note: str = "", token: str | None = None) -> dict:
    """Replace this document's content with another document's (a version of it) as this document's next version
    (plan 22, W-R10). The source document is not changed, moved or deleted; it keeps its own history."""
    from app import access

    src_id = source_document_id.upper()
    if src_id == document_id:
        raise EditError(422, "Choose another document to copy from (use Restore for this document's own versions)")
    try:
        access.require_document_level(conn, member_id, src_id, "read", via="copy_from")
    except access.AccessError as exc:
        raise EditError(exc.status, exc.detail) from exc
    src = _document(conn, src_id)
    ver = _version(conn, src_id, source_version_id or src["current_version_id"])
    if ver is None:
        raise EditError(404, "Source version not found")
    data, kind = _file_of(src, ver)
    message = note or f"Content replaced with {src['title']} (v{ver['version_number']})"
    if data:
        ext = {"docx": ".docx", "pdf": ".pdf"}.get(kind, Path(ver.get("storage_uri") or "").suffix or ".txt")
        out = upload_version(conn, document_id, member_id, Path(src["title"]).stem + ext, data, base_version_id,
                             note=message, token=token)
    else:
        doc = _document(conn, document_id)
        _require(conn, member_id, doc, "edit")
        _check_can_write(conn, document_id, member_id, token)
        if base_version_id and base_version_id != doc["current_version_id"]:
            raise EditError(409, "A newer version was saved since you opened this document",
                            {"current_version_id": doc["current_version_id"]})
        version = _create(conn, doc, member_id, text=ver.get("body") or "", note=message, origin="copy", label=None,
                          storage_uri=None, mime=None, size=None)
        out = {"version_id": version["version_id"], "version_number": version["version_number"]}
    conn.execute("UPDATE document_versions SET origin = 'copy' WHERE version_id = %s", (out["version_id"],))
    record_event(conn, document_id, member_id, "version.copy_from", out["version_id"],
                 {"source_document_id": src_id, "source_version_id": ver["version_id"]})
    conn.commit()
    return {**out, "source": {"document_id": src_id, "version_id": ver["version_id"], "title": src["title"],
                              "unchanged": True,
                              "note": "The source document is unchanged and keeps its own history."}}


def _same_text(a: str, b: str) -> bool:
    return " ".join((a or "").split()) == " ".join((b or "").split())


def _import_reviewed(conn, doc: dict, member_id: str | None, filename: str, data: bytes, note: str,
                     label: str | None) -> dict:
    """A Word file that carries other people's tracked changes becomes commits, so the current version stays clean.

    1. the file's own text before the changes (rejected) — skipped when that is already the current version, which
       is the usual case: someone took the current version, reviewed it in Word, and sent it back;
    2. the file with the changes accepted, credited to the people who made them. The raw file is kept as evidence.
    """
    from app.documents import docx_review
    from app.documents.review import index_version
    from app.ingest.extractors.dispatch import extract_from_bytes

    revs = docx_review.read_revisions(data)
    authors = sorted({r.author for r in revs if r.author}) or ["Unknown"]
    credited = ", ".join(authors[:3]) + (f" +{len(authors) - 3}" if len(authors) > 3 else "")
    name = Path(filename).stem + ".docx"
    base_file, final_file = docx_review.reject_everything(data), docx_review.accept_everything(data)
    base_text, final_text = extract_from_bytes(name, base_file), extract_from_bytes(name, final_file)
    head = _version(conn, doc["document_id"], doc["current_version_id"])
    made: list[dict] = []

    if head is None or not _same_text(base_text.text, head.get("body") or ""):
        number = _next_number(conn, doc["document_id"])
        uri = _store_version_file(doc, number, name, base_file, DOCX_MIME)
        v = _create(conn, doc, member_id, text=base_text.text, origin="import", label=None, storage_uri=uri,
                    note=f"Text of {filename} before its {len(revs)} tracked changes", mime=DOCX_MIME,
                    size=len(base_file), page_spans=base_text.pages, is_clean=True)
        made.append(v)

    number = _next_number(conn, doc["document_id"])
    uri = _store_version_file(doc, number, name, final_file, DOCX_MIME)
    raw_uri = _store_source_file(doc, number, name, data, DOCX_MIME)
    message = f"Imported {len(revs)} tracked change{'s' if len(revs) != 1 else ''} from {credited}"
    v = _create(conn, doc, member_id, text=final_text.text, origin="upload", label=label, storage_uri=uri,
                note=message + (f": {note}" if note else ""), mime=DOCX_MIME, size=len(final_file),
                page_spans=final_text.pages, is_clean=True, source_uri=raw_uri, author_name=credited)
    made.append(v)
    index_version(conn, doc, v["version_id"], data)  # who changed what, and the Word comments, from the raw file
    record_event(conn, doc["document_id"], member_id, "version.upload", v["version_id"],
                 {"filename": filename, "note": note, "tracked_changes": len(revs), "authors": authors,
                  "commits": len(made)})
    conn.commit()
    audit.record("document.version.upload", member_id=member_id, object_type="document", object_id=doc["document_id"],
                 matter_id=doc["matter_id"], detail={"version_id": v["version_id"], "filename": filename,
                                                     "tracked_changes": len(revs), "commits": len(made)})
    return {"version_id": v["version_id"], "version_number": v["version_number"],
            "commits": [{"version_id": m["version_id"], "version_number": m["version_number"]} for m in made],
            "tracked_changes": len(revs), "authors": authors}


def restore_version(conn, document_id: str, member_id: str | None, version_id: str, base_version_id: str,
                    note: str = "", token: str | None = None) -> dict:
    """Make an earlier version current again as a NEW version (history is never rewritten, like ``git revert``)."""
    from app.documents import docx_review
    from app.documents.review import index_version
    from app.ingest.extractors.dispatch import extract_from_bytes
    from app.storage.object_store import guess_mime

    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "edit")
    if member_id is None:
        raise EditError(400, "Sign in to restore a version")
    _check_can_write(conn, document_id, member_id, token)
    if base_version_id != doc["current_version_id"]:
        raise EditError(409, "Someone saved a newer version while you were looking; reload to see it",
                        {"current_version_id": doc["current_version_id"]})
    target = _version(conn, document_id, version_id)
    if target is None:
        raise EditError(404, "Version not found")
    if target["version_id"] == doc["current_version_id"]:
        raise EditError(422, "That is already the current version")

    message = f"Restored version {target['version_number']}" + (f": {note}" if note else "")
    number = _next_number(conn, document_id)
    data, kind = _file_of(doc, target) if target.get("storage_uri") else (None, "none")
    if target.get("storage_uri") and data is None:
        raise EditError(422, "The file of that version is not available, so it cannot be restored")
    if kind == "docx":
        data = docx_review.accept_everything(data)  # a version not yet cleaned restores as it reads in the Final view
        name = Path(doc["title"]).stem + ".docx"
        mime = DOCX_MIME
    elif data is not None:
        name = Path(target["storage_uri"]).name
        mime = target.get("mime_type") or guess_mime(name)
    if data is not None:
        extracted = extract_from_bytes(name, data)
        uri = _store_version_file(doc, number, name, data, mime)
        version = _create(conn, doc, member_id, text=extracted.text, note=message, origin="restore", label=None,
                          storage_uri=uri, mime=mime, size=len(data), page_spans=extracted.pages,
                          is_clean=True if kind == "docx" else None, restored_from=target["version_id"])
        if kind == "docx":
            index_version(conn, doc, version["version_id"], data)
    else:  # a text-only document: the version is its text
        version = _create(conn, doc, member_id, text=target.get("body") or "", note=message, origin="restore",
                          label=None, storage_uri=None, mime=None, size=None, restored_from=target["version_id"])
    conn.execute("DELETE FROM document_drafts WHERE document_id = %s AND member_id = %s", (document_id, member_id))
    record_event(conn, document_id, member_id, "version.restore", version["version_id"],
                 {"restored": target["version_id"], "restored_number": target["version_number"], "note": note})
    conn.commit()
    audit.record("document.version.restore", member_id=member_id, object_type="document", object_id=document_id,
                 matter_id=doc["matter_id"], detail={"version_id": version["version_id"],
                                                     "restored": target["version_id"]})
    return {"version_id": version["version_id"], "version_number": version["version_number"],
            "restored_version_id": target["version_id"], "restored_version_number": target["version_number"]}


# ── compare ──────────────────────────────────────────────────────────────────

def _version_paragraphs(conn, doc: dict, version_id: str) -> tuple[list[str], bytes | None, dict]:
    ver = _version(conn, doc["document_id"], version_id)
    if ver is None:
        raise EditError(404, "Version not found")
    data, kind = _file_of(doc, ver) if ver.get("storage_uri") else (None, "none")
    if kind == "docx":
        base = _accepted(data)
        return [p["text"] for p in _docx_paragraphs(base)], base, ver
    return [p["text"] for p in _text_paragraphs(ver.get("body") or "")], None, ver


def _word_diff(a: str, b: str) -> list[dict]:
    from app.documents.tokens import tokenize, word_ops

    ta, tb = tokenize(a), tokenize(b)
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in word_ops(ta, tb):
        if tag == "equal":
            out.append({"t": "eq", "text": "".join(ta[i1:i2])})
        else:
            if i2 > i1:
                out.append({"t": "del", "text": "".join(ta[i1:i2])})
            if j2 > j1:
                out.append({"t": "ins", "text": "".join(tb[j1:j2])})
    return out


PAIR_SIMILARITY = 0.5


def _diff_blocks(old: list[str], new: list[str]):
    """Yield (kind, i, j): equal / replace (similar paragraphs paired) / delete / insert.

    Inside a changed region a paragraph is paired with a new one only when they are
    similar; an unrelated paragraph in the same place is a deletion plus an insertion,
    not a "change" with a word-by-word mess. ``i``/``j`` index old/new; for inserts ``i``
    is the old paragraph the new one follows (-1 = before the first).
    """
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                yield "equal", i1 + k, j1 + k
            continue
        j = j1
        last_old = i1 - 1
        for i in range(i1, i2):
            match = None
            for jj in range(j, j2):
                if difflib.SequenceMatcher(None, old[i], new[jj], autojunk=False).ratio() >= PAIR_SIMILARITY:
                    match = jj
                    break
            if match is None:
                yield "delete", i, None
                continue
            for jj in range(j, match):
                yield "insert", last_old, jj
            yield "replace", i, match
            last_old, j = i, match + 1
        for jj in range(j, j2):
            yield "insert", i2 - 1, jj


def paragraph_ops(old: list[str], new: list[str]) -> list[dict]:
    """Paragraph edit ops turning ``old`` into ``new`` (for tracked-changes compare files)."""
    ops: list[dict] = []
    for kind, i, j in _diff_blocks(old, new):
        if kind == "replace" and old[i] != new[j]:
            ops.append({"op": "replace", "pid": i, "text": new[j]})
        elif kind == "delete":
            ops.append({"op": "delete", "pid": i})
        elif kind == "insert" and i >= 0:
            ops.append({"op": "insert_after", "pid": i, "text": new[j]})
    return ops


def compare(conn, document_id: str, member_id: str | None, from_id: str, to_id: str) -> dict:
    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "read")
    old, _, v_old = _version_paragraphs(conn, doc, from_id)
    new, _, v_new = _version_paragraphs(conn, doc, to_id)
    blocks: list[dict] = []
    stats = {"inserted": 0, "deleted": 0, "changed": 0, "unchanged": 0}
    for kind, i, j in _diff_blocks(old, new):
        if kind == "equal" or (kind == "replace" and old[i] == new[j]):
            stats["unchanged"] += 1
            if blocks and blocks[-1]["op"] == "equal":
                blocks[-1]["count"] += 1
            else:
                blocks.append({"op": "equal", "count": 1, "from": i})
        elif kind == "replace":
            stats["changed"] += 1
            blocks.append({"op": "replace", "old": old[i], "new": new[j], "segments": _word_diff(old[i], new[j])})
        elif kind == "delete":
            stats["deleted"] += 1
            blocks.append({"op": "delete", "old": old[i]})
        else:
            stats["inserted"] += 1
            blocks.append({"op": "insert", "new": new[j]})

    def count_words(kind: str) -> int:
        """Words inserted ("ins") or removed ("del") across the compared blocks."""
        n = 0
        for b in blocks:
            for seg in b.get("segments", []):
                if seg["t"] == kind:
                    n += len(re.findall(r"\w+", seg["text"]))
            if kind == "ins" and b["op"] == "insert":
                n += len(re.findall(r"\w+", b["new"]))
            if kind == "del" and b["op"] == "delete":
                n += len(re.findall(r"\w+", b["old"]))
        return n

    stats["words_added"], stats["words_removed"] = count_words("ins"), count_words("del")

    def meta(v: dict) -> dict:
        return {"version_id": v["version_id"], "version_number": v["version_number"], "author": v["author_name"],
                "created_at": v["created_at"], "note": v["change_summary"]}

    return {"document_id": document_id, "from": meta(v_old), "to": meta(v_new), "stats": stats, "blocks": blocks}


def compare_docx(conn, document_id: str, member_id: str | None, from_id: str, to_id: str) -> tuple[bytes, str]:
    """The *from* version's own Word file with the differences to *to* as tracked changes."""
    from app.drafting.docx_tracked import apply_tracked_changes

    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "read")
    old, base, _ = _version_paragraphs(conn, doc, from_id)
    new, _, v_new = _version_paragraphs(conn, doc, to_id)
    if base is None:
        raise EditError(422, "The earlier version has no Word file to mark up")
    out, _stats = apply_tracked_changes(base, paragraph_ops(old, new), author=v_new.get("author_name") or "Precentis")
    name = f"{Path(doc['title']).stem} v{_version(conn, document_id, from_id)['version_number']}-v{v_new['version_number']} redline.docx"
    return out, name


def history(conn, document_id: str, member_id: str | None, limit: int = 100) -> list[dict]:
    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "read")
    rows = conn.execute(
        """
        SELECT e.seq, e.action, e.version_id, e.member_id, m.name, e.detail, e.occurred_at
        FROM document_events e LEFT JOIN members m USING (member_id)
        WHERE e.document_id = %s ORDER BY e.seq DESC LIMIT %s
        """,
        (document_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ── commits and blame ────────────────────────────────────────────────────────

def commits(conn, document_id: str, member_id: str | None, limit: int = 100) -> list[dict]:
    """The document's versions as a commit log, newest first: message, author, kind, size change."""
    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "read")
    rows = [dict(r) for r in conn.execute(
        """
        SELECT v.version_id, v.version_number, v.version_label, v.change_summary AS message, v.author_name,
               v.created_by_member_id, v.origin, v.created_at, v.parent_version_id, v.restored_from_version_id,
               v.is_clean, v.mime_type, v.source_storage_uri IS NOT NULL AS has_source_file, length(v.body) AS chars,
               v.deleted_at, v.delete_reason, dm.name AS deleted_by_name
        FROM document_versions v LEFT JOIN members dm ON dm.member_id = v.deleted_by
        WHERE v.document_id = %s ORDER BY v.version_number DESC LIMIT %s
        """, (document_id, limit + 1)).fetchall()]
    older = {r["version_id"]: r for r in rows}
    out = []
    for r in rows[:limit]:
        parent = older.get(r["parent_version_id"] or "")
        deleted = r["deleted_at"] is not None
        out.append({**r, "is_current": r["version_id"] == doc["current_version_id"],
                    "kind": r["origin"] or "upload", "deleted": deleted,
                    "chars_delta": None if deleted or not parent or parent["deleted_at"] else r["chars"] - parent["chars"]})
    return out


def purge_version(conn, document_id: str, member_id: str | None, version_id: str, reason: str) -> dict:
    """Delete one earlier version's content for good (plan 22 W-R8), e.g. on a client's instruction.

    Its file (unless another version or document still uses the same bytes), raw upload, text, index, comments
    and computed diffs are removed; the row stays in the history as "deleted — cannot be restored", with who and
    why. The current version cannot be deleted (restore or save another first). Needs manage access.
    """
    from app.storage.blobs import is_referenced
    from app.storage.object_store import get_object_store

    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "manage")
    why = (reason or "").strip()
    if len(why) < 3:
        raise EditError(422, "Say why this version is being deleted")
    ver = _one(conn, "SELECT * FROM document_versions WHERE document_id = %s AND version_id = %s FOR UPDATE",
               (document_id, version_id))
    if ver is None:
        raise EditError(404, "Version not found")
    if ver["deleted_at"] is not None:
        raise EditError(409, "This version was already deleted")
    if version_id == doc["current_version_id"]:
        raise EditError(409, "The current version cannot be deleted; restore or save another version first")
    uris = [u for u in (ver["storage_uri"], ver["source_storage_uri"]) if u]
    store = get_object_store()
    digests = []
    for u in uris:
        try:
            import hashlib

            digests.append(hashlib.sha256(store.get(u)).hexdigest())
        except Exception:  # noqa: BLE001 — a missing file is already gone
            pass
    conn.execute(
        """UPDATE document_versions SET body = '', storage_uri = NULL, source_storage_uri = NULL, file_size_bytes = NULL,
                  page_count = NULL, deleted_at = now(), deleted_by = %s, delete_reason = %s
           WHERE version_id = %s""", (member_id, why[:500], version_id))
    for table in ("document_blocks", "document_intelligence", "evidence_anchors", "findings", "document_revision_authors",
                  "annotations", "chunks"):
        conn.execute(f"DELETE FROM {table} WHERE version_id = %s", (version_id,))
    conn.execute("DELETE FROM version_diffs WHERE source_version_id = %s OR target_version_id = %s", (version_id, version_id))
    if uris:
        conn.execute("UPDATE documents SET source_uri = NULL WHERE document_id = %s AND source_uri = ANY(%s)",
                     (document_id, uris))
        conn.execute("UPDATE upload_batch_files SET storage_uri = 'purged://' || content_sha256 "
                     "WHERE document_id = %s AND storage_uri = ANY(%s)", (document_id, uris))
    record_event(conn, document_id, member_id, "version.purge", version_id,
                 {"version_number": ver["version_number"], "reason": why[:500]})
    conn.commit()
    removed = 0
    for u in uris:
        if is_referenced(conn, u):
            continue  # the same bytes are another version's or another document's: they stay
        try:
            store.delete(u)
            removed += 1
        except FileNotFoundError:
            pass
        conn.execute("DELETE FROM blobs WHERE storage_uri = %s", (u,))
    if removed:
        from app.documents.pdf_render import _cache_dir

        for d in digests:
            (_cache_dir() / f"{d}.pdf").unlink(missing_ok=True)
    conn.commit()
    for k in [k for k in _BLAME_CACHE if k[0] == document_id]:
        _BLAME_CACHE.pop(k, None)
    audit.record("document.version.purge", member_id=member_id, object_type="document", object_id=document_id,
                 matter_id=doc["matter_id"], detail={"version_id": version_id, "version_number": ver["version_number"],
                                                     "reason": why[:500], "files_removed": removed})
    return {"version_id": version_id, "version_number": ver["version_number"], "deleted": True, "files_removed": removed}


_BLAME_CACHE: dict[tuple[str, str, int], list[dict]] = {}
_BLAME_CACHE_MAX = 32
BLAME_DEPTH = 60


def _body_paragraphs(body: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n+", body or "") if p.strip()]


def blame(conn, document_id: str, member_id: str | None, version_id: str | None = None,
          depth: int = BLAME_DEPTH) -> dict:
    """For each paragraph of a version: the version and person that last changed it (like ``git blame``).

    Works from the stored text of up to ``depth`` versions ending at ``version_id``, oldest first; a paragraph is
    credited to the version where it last appeared or changed. A paragraph older than the window is credited to the
    oldest version in it and flagged ``before_window``.
    """
    doc = _document(conn, document_id)
    _require(conn, member_id, doc, "read")
    target_id = version_id or doc["current_version_id"]
    target = _version(conn, document_id, target_id)
    if target is None:
        raise EditError(404, "Version not found")
    depth = max(2, min(int(depth), 200))
    key = (document_id, target["version_id"], depth)
    if key in _BLAME_CACHE:
        return {"document_id": document_id, "version_id": target["version_id"], "paragraphs": _BLAME_CACHE[key],
                "depth": depth}
    rows = [dict(r) for r in conn.execute(
        """SELECT version_id, version_number, body, author_name, created_at, change_summary FROM document_versions
           WHERE document_id = %s AND version_number <= %s AND deleted_at IS NULL
           ORDER BY version_number DESC LIMIT %s""",
        (document_id, target["version_number"], depth)).fetchall()][::-1]
    first = rows[0]
    reaches_start = first["version_number"] == min(
        (r["version_number"] for r in conn.execute(
            "SELECT version_number FROM document_versions WHERE document_id = %s", (document_id,))), default=1)

    def credit(v: dict) -> dict:
        return {"version_id": v["version_id"], "version_number": v["version_number"], "author": v["author_name"],
                "at": v["created_at"], "message": v["change_summary"]}

    paras = _body_paragraphs(first["body"])
    owner = [credit(first) for _ in paras]
    for v in rows[1:]:
        new = _body_paragraphs(v["body"])
        new_owner: list[dict | None] = [None] * len(new)
        for kind, i, j in _diff_blocks(paras, new):
            if kind == "equal" or (kind == "replace" and paras[i] == new[j]):
                new_owner[j] = owner[i]
            elif kind in ("replace", "insert") and j is not None:
                new_owner[j] = credit(v)
        paras, owner = new, [o or credit(v) for o in new_owner]
    result = [{"pid": i, "text": t, **o, "before_window": (not reaches_start and o["version_id"] == first["version_id"])}
              for i, (t, o) in enumerate(zip(paras, owner))]
    if len(_BLAME_CACHE) >= _BLAME_CACHE_MAX:
        _BLAME_CACHE.pop(next(iter(_BLAME_CACHE)))
    _BLAME_CACHE[key] = result
    return {"document_id": document_id, "version_id": target["version_id"], "paragraphs": result, "depth": depth}
