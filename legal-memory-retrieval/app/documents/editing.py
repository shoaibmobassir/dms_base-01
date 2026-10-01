"""In-browser editing, file-based versions, locks and compare (plan 16, E1–E2).

The browser edits *paragraphs* of the current version; the server writes those edits
into the version's own file, so everything the editor did not touch keeps its exact
Word formatting:

    edit model   Document(accept_all(file)).paragraphs → [{pid, style, text, runs}]
    save         accept_all(file) + ops → Word tracked changes by the signed-in member
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
    if not version_id:
        return None
    return _one(conn, "SELECT version_id, version_number, storage_uri, mime_type, body, author_name, "
                      "created_by_member_id, created_at, change_summary FROM document_versions "
                      "WHERE document_id = %s AND version_id = %s", (document_id, version_id))


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
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml")
    except Exception:
        return False
    from app.documents.docx_format import has_format_revisions

    return b"<w:ins " in xml or b"<w:del " in xml or has_format_revisions(xml)


def _accepted(data: bytes) -> bytes:
    """The file with every revision accepted: text (docx_tracked) and formatting (docx_format)."""
    from app.documents.docx_format import accept_formatting
    from app.drafting.docx_tracked import accept_all

    return accept_formatting(accept_all(data)) if _zip_has_revisions(data) else data


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
    if kind == "docx":
        from docx import Document

        from app.documents.docx_format import paragraph_styles

        accepted = _accepted(data)
        paragraphs = _docx_paragraphs(accepted)
        defined = paragraph_styles(Document(io.BytesIO(accepted)))
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


def _next_number(conn, document_id: str) -> int:
    row = _one(conn, "SELECT coalesce(max(version_number), 0) + 1 AS n FROM document_versions WHERE document_id = %s", (document_id,))
    return int(row["n"]) if row else 1


def _create(conn, doc: dict, member_id: str | None, *, text: str, note: str, origin: str, label: str | None,
            storage_uri: str | None, mime: str | None, size: int | None, page_spans=None) -> dict:
    from app.documents import create_version, sync_page_count

    author = _member_name(conn, member_id)
    # Replacing the document's chunks must not interleave with the background embedder
    # writing vectors to them (row locks taken in opposite orders deadlock).
    conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (_INDEX_LOCK + doc["document_id"],))
    try:
        _snapshot_vectors(conn, doc["document_id"])
        version = create_version(
            document_id=doc["document_id"], body=text[:500_000], author_name=author,
            source="edit" if origin == "editor" else "upload", version_status="developing", version_label=label,
            change_summary=note or None, storage_uri=storage_uri, page_spans=page_spans,
        )
    finally:
        conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (_INDEX_LOCK + doc["document_id"],))
    conn.execute(
        "UPDATE document_versions SET created_by_member_id = %s, origin = %s, mime_type = coalesce(%s, mime_type), "
        "file_size_bytes = coalesce(%s, file_size_bytes) WHERE version_id = %s",
        (member_id, origin, mime, size, version["version_id"]),
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


def save_edits(conn, document_id: str, member_id: str | None, base_version_id: str, ops: list[dict],
               note: str = "", mode: str = "tracked", token: str | None = None) -> dict:
    """Write the editor's paragraph edits as the next version (see module docstring)."""
    from app.drafting.docx_tracked import accept_all, apply_tracked_changes
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
    number = _next_number(conn, document_id)
    if kind == "docx":
        base = _accepted(data)
        from docx import Document

        from app.documents.docx_format import accept_formatting, apply_formatting, paragraph_styles, wants_formatting

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
        out = tracked if mode == "tracked" else accept_formatting(accept_all(tracked))
        name = Path(doc["title"]).stem + ".docx"
        uri = _store_version_file(doc, number, name, out, DOCX_MIME)
        extracted = extract_from_bytes(name, accept_all(out))
        version = _create(conn, doc, member_id, text=extracted.text, note=note, origin="editor", label=None,
                          storage_uri=uri, mime=DOCX_MIME, size=len(out), page_spans=extracted.pages)
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
        version = _create(conn, doc, member_id, text=new_text, note=note, origin="editor", label=None,
                          storage_uri=None, mime=None, size=None)
    conn.execute("DELETE FROM document_drafts WHERE document_id = %s AND member_id = %s", (document_id, member_id))
    record_event(conn, document_id, member_id, "edit.save", version["version_id"], {"mode": mode, **stats, "note": note})
    conn.commit()
    audit.record("document.edit", member_id=member_id, object_type="document", object_id=document_id,
                 matter_id=doc["matter_id"], detail={"version_id": version["version_id"], "mode": mode, **stats})
    return {"version_id": version["version_id"], "version_number": version["version_number"], "stats": stats, "mode": mode}


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
    extracted = extract_from_bytes(filename, _accepted(data) if suffix == ".docx" else data)
    number = _next_number(conn, document_id)
    mime = guess_mime(filename)
    uri = _store_version_file(doc, number, filename, data, mime)
    version = _create(conn, doc, member_id, text=extracted.text, note=note, origin="upload", label=label,
                      storage_uri=uri, mime=mime, size=len(data), page_spans=extracted.pages)
    record_event(conn, document_id, member_id, "version.upload", version["version_id"], {"filename": filename, "note": note})
    conn.commit()
    audit.record("document.version.upload", member_id=member_id, object_type="document", object_id=document_id,
                 matter_id=doc["matter_id"], detail={"version_id": version["version_id"], "filename": filename})
    return {"version_id": version["version_id"], "version_number": version["version_number"]}


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
    import re

    ta, tb = re.findall(r"\s+|[^\s]+", a), re.findall(r"\s+|[^\s]+", b)
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
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
