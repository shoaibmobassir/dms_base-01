"""Durable tabular reviews (plan 22, W4): many questions over many documents as a table.

Rows are documents (or folders); columns are named questions with an answer format; each cell holds an answer, the
quoted passage it rests on (citations) and a status. A review belongs to a workspace and follows its access:
reading needs read on the workspace, changing it needs edit (a library: its owner). A cell drawn from a document the
viewer cannot read is shown as restricted, whoever ran it.

Filling cells is ``app.tabular.runner`` (leased rows, one model call per row for all its pending columns).
"""
from __future__ import annotations

import uuid
from typing import Any

from app import access
from app.api.acl import doc_read
from app.audit import events as audit
from app.firm import FirmError, check_version, guard, one
from app.workspaces import clean_path, require_container, rows

FORMATS = ("text", "date", "yes_no", "number", "money", "list", "choice")
MAX_COLUMNS = 30
MAX_ROWS = 1000

# Ready-made columns a review can start from (and the column-set playbooks of W5 extend).
PRESETS: dict[str, dict[str, Any]] = {
    "parties": {"label": "Parties", "question": "Who are the parties to this document?", "answer_format": "list"},
    "date": {"label": "Date", "question": "What is the date of this document (signature or effective date)?", "answer_format": "date"},
    "governing_law": {"label": "Governing law", "question": "Which law governs this document?", "answer_format": "text"},
    "term": {"label": "Term", "question": "What is the term or duration, and how does it end?", "answer_format": "text"},
    "termination": {"label": "Termination", "question": "On what grounds and with what notice can it be terminated?", "answer_format": "text"},
    "notice_period": {"label": "Notice period", "question": "What notice period applies?", "answer_format": "text"},
    "liability_cap": {"label": "Liability cap", "question": "Is liability capped, and at what amount?", "answer_format": "money"},
    "indemnity": {"label": "Indemnity", "question": "Who indemnifies whom, and for what?", "answer_format": "text"},
    "assignment": {"label": "Assignment", "question": "Can the document be assigned or transferred, and on what conditions?", "answer_format": "text"},
    "change_of_control": {"label": "Change of control", "question": "Is there a change of control clause?", "answer_format": "yes_no"},
    "confidentiality": {"label": "Confidentiality", "question": "Is there a confidentiality obligation, and for how long?", "answer_format": "text"},
    "dispute_resolution": {"label": "Dispute resolution", "question": "How are disputes resolved (courts, arbitration, seat)?", "answer_format": "text"},
    # Disputes and regulatory filings (the firm's own practice)
    "forum": {"label": "Forum and case no.", "question": "Before which court, commission or tribunal, and under which case number?", "answer_format": "text"},
    "filed_by": {"label": "Filed by", "question": "Which party files or issued this document?", "answer_format": "text"},
    "relief": {"label": "Relief sought", "question": "What relief or prayer is asked for?", "answer_format": "text"},
    "grounds": {"label": "Main grounds", "question": "What are the main grounds relied on?", "answer_format": "list"},
    "provisions": {"label": "Provisions relied on", "question": "Which statutory sections, regulations and orders are relied on?", "answer_format": "list"},
    "outcome": {"label": "Outcome", "question": "If this is an order or judgment, what was decided?", "answer_format": "text"},
    "next_date": {"label": "Next date", "question": "Is a next hearing date or deadline mentioned?", "answer_format": "date"},
}


def _new(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _review(conn, review_id: str) -> dict:
    row = one(conn, "SELECT * FROM tab_reviews WHERE review_id = %s", (review_id,))
    if row is None:
        raise FirmError(404, "Review not found or access denied")
    return row


def require_review(conn, actor: str | None, review_id: str, needed: str) -> dict:
    """The review, if the actor has ``needed`` on its workspace (unknown and invisible are both 404)."""
    review = _review(conn, review_id)
    try:
        require_container(conn, actor, review["container_kind"], review["container_id"], needed)
    except FirmError as exc:
        if exc.status == 404:
            raise FirmError(404, "Review not found or access denied") from exc
        raise
    if needed != "read" and review["archived_at"] is not None:
        raise FirmError(409, "This review is archived")
    return review


def _column_input(c: dict) -> dict:
    preset = PRESETS.get(str(c.get("preset") or ""))
    data = {**(preset or {}), **{k: v for k, v in c.items() if v not in (None, "") and k != "preset"}}
    label = str(data.get("label") or "").strip()
    question = str(data.get("question") or "").strip()
    fmt = str(data.get("answer_format") or "text")
    if not label or len(label) > 120:
        raise FirmError(422, "Each column needs a label of at most 120 characters")
    if not question or len(question) > 2000:
        raise FirmError(422, f"Column {label}: write the question to answer (at most 2,000 characters)")
    if fmt not in FORMATS:
        raise FirmError(422, f"answer_format must be one of {', '.join(FORMATS)}")
    choices = [str(x).strip() for x in (data.get("choices") or []) if str(x).strip()][:20]
    if fmt == "choice" and len(choices) < 2:
        raise FirmError(422, f"Column {label}: a choice column needs at least two choices")
    return {"label": label, "question": question, "answer_format": fmt, "choices": choices}


def _readable_documents(conn, actor: str | None, document_ids: list[str]) -> list[str]:
    ids = list(dict.fromkeys(i.upper() for i in document_ids if i))
    if not ids:
        return []
    ok = {r["document_id"] for r in rows(conn, f"""
        SELECT d.document_id FROM documents d LEFT JOIN permissions p ON p.matter_id = d.matter_id
        WHERE d.document_id = ANY(%(ids)s) AND d.archived_at IS NULL AND {doc_read('d')}""",
        {"ids": ids, "member_id": actor})}
    return [i for i in ids if i in ok]


def _add_rows(conn, actor: str | None, review: dict, document_ids: list[str], folders: list[str]) -> int:
    start = one(conn, "SELECT coalesce(max(position), -1) + 1 AS n FROM tab_rows WHERE review_id = %s",
                (review["review_id"],))["n"]
    added = 0
    for doc in _readable_documents(conn, actor, document_ids):
        made = one(conn, """INSERT INTO tab_rows (row_id, review_id, position, document_id) VALUES (%s, %s, %s, %s)
                            ON CONFLICT DO NOTHING RETURNING row_id""", (_new("TRW"), review["review_id"], start + added, doc))
        added += bool(made)
    for f in folders:
        path = clean_path(f)
        if not path:
            continue
        made = one(conn, """INSERT INTO tab_rows (row_id, review_id, position, folder_path) VALUES (%s, %s, %s, %s)
                            ON CONFLICT DO NOTHING RETURNING row_id""", (_new("TRW"), review["review_id"], start + added, path))
        added += bool(made)
    total = one(conn, "SELECT count(*) AS n FROM tab_rows WHERE review_id = %s", (review["review_id"],))["n"]
    if total > MAX_ROWS:
        raise FirmError(422, f"A review holds at most {MAX_ROWS} rows")
    _seed_cells(conn, review["review_id"])
    return added


def _seed_cells(conn, review_id: str) -> None:
    """Every (row, column) has a cell; new ones are pending."""
    conn.execute("""INSERT INTO tab_cells (row_id, column_id, column_revision)
                    SELECT r.row_id, c.column_id, c.revision FROM tab_rows r JOIN tab_columns c USING (review_id)
                    WHERE r.review_id = %s ON CONFLICT DO NOTHING""", (review_id,))


def _touch(conn, review_id: str) -> None:
    conn.execute("UPDATE tab_reviews SET updated_at = now(), row_version = row_version + 1 WHERE review_id = %s",
                 (review_id,))


# ── create / read ────────────────────────────────────────────────────────────

@guard
def create_review(conn, actor: str | None, data: dict) -> dict:
    kind, cid = str(data.get("kind") or ""), str(data.get("id") or "")
    require_container(conn, actor, kind, cid, "edit")
    title = str(data.get("title") or "").strip()
    if not title or len(title) > 200:
        raise FirmError(422, "Give the review a title (at most 200 characters)")
    columns = [_column_input(c) for c in (data.get("columns") or [])]
    if data.get("playbook_id"):
        from app.playbooks import get_playbook

        pb = get_playbook(conn, actor, data["playbook_id"])
        if pb["kind"] == "columns":
            columns = [_column_input(c) for c in pb["columns"]] + columns
    if not columns:
        raise FirmError(422, "Add at least one column (a question to answer)")
    if len(columns) > MAX_COLUMNS:
        raise FirmError(422, f"At most {MAX_COLUMNS} columns")
    group_by = "folder" if data.get("group_by") == "folder" else "document"
    review_id = _new("TRV")
    conn.execute("""INSERT INTO tab_reviews (review_id, title, container_kind, container_id, owner_member_id, group_by,
                                             model, playbook_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                 (review_id, title, kind, cid, actor, group_by, data.get("model"), data.get("playbook_id")))
    for i, c in enumerate(columns):
        conn.execute("""INSERT INTO tab_columns (column_id, review_id, position, label, question, answer_format, choices)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                     (_new("TCL"), review_id, i, c["label"], c["question"], c["answer_format"], c["choices"]))
    review = _review(conn, review_id)
    _add_rows(conn, actor, review, data.get("document_ids") or [], data.get("folders") or [])
    conn.commit()
    audit.record("tabular.create", member_id=actor, object_type="tab_review", object_id=review_id,
                 matter_id=cid if kind == "matter" else None, detail={"kind": kind, "id": cid, "columns": len(columns)})
    return get_review(conn, actor, review_id)


@guard
def list_reviews(conn, actor: str | None, kind: str, cid: str) -> list[dict]:
    require_container(conn, actor, kind, cid, "read")
    return rows(conn, """
        SELECT r.review_id, r.title, r.group_by, r.created_at, r.updated_at, r.owner_member_id, m.name AS owner_name,
               (SELECT count(*) FROM tab_rows x WHERE x.review_id = r.review_id) AS row_count,
               (SELECT count(*) FROM tab_columns x WHERE x.review_id = r.review_id) AS column_count,
               (SELECT count(*) FROM tab_cells c JOIN tab_rows x USING (row_id)
                WHERE x.review_id = r.review_id AND c.status IN ('pending', 'running', 'stale')) AS open_cells
        FROM tab_reviews r LEFT JOIN members m ON m.member_id = r.owner_member_id
        WHERE r.container_kind = %s AND r.container_id = %s AND r.archived_at IS NULL
        ORDER BY r.updated_at DESC""", (kind, cid))


@guard
def get_review(conn, actor: str | None, review_id: str) -> dict:
    """The table as the actor may see it: rows on documents they cannot read, and cells drawn from such documents,
    are redacted (no title, no answer, no quote)."""
    review = require_review(conn, actor, review_id, "read")
    level = access.container_level(conn, actor, review["container_kind"], review["container_id"])
    cols = rows(conn, "SELECT column_id, position, label, question, answer_format, choices, revision FROM tab_columns "
                      "WHERE review_id = %s ORDER BY position", (review_id,))
    row_list = rows(conn, """SELECT r.row_id, r.position, r.document_id, r.folder_path, d.title, d.mime_type,
                                    r.lease_until > now() AS running
                             FROM tab_rows r LEFT JOIN documents d ON d.document_id = r.document_id
                             WHERE r.review_id = %s ORDER BY r.position""", (review_id,))
    cells = rows(conn, """SELECT c.* FROM tab_cells c JOIN tab_rows r USING (row_id) WHERE r.review_id = %s""",
                 (review_id,))
    involved = {r["document_id"] for r in row_list if r["document_id"]}
    for c in cells:
        involved.update(c["source_documents"] or [])
    readable = set(_readable_documents(conn, actor, list(involved)))
    out_rows = []
    for r in row_list:
        hidden = bool(r["document_id"]) and r["document_id"] not in readable
        out_rows.append({"row_id": r["row_id"], "position": r["position"], "kind": "folder" if r["folder_path"] else "document",
                         "document_id": None if hidden else r["document_id"], "folder_path": r["folder_path"],
                         "title": None if hidden else (r["title"] or r["folder_path"]), "mime_type": None if hidden else r["mime_type"],
                         "restricted": hidden, "running": bool(r["running"])})
    hidden_rows = {r["row_id"] for r in out_rows if r["restricted"]}
    out_cells = []
    for c in cells:
        restricted = c["row_id"] in hidden_rows or any(d not in readable for d in (c["source_documents"] or []))
        base = {"row_id": c["row_id"], "column_id": c["column_id"], "status": c["status"], "updated_at": c["updated_at"],
                "stale": c["status"] == "stale"}
        if restricted:
            out_cells.append({**base, "restricted": True})
            continue
        out_cells.append({**base, "answer": c["answer"], "citations": c["citations"], "error": c["error"],
                          "edited": c["edited_by"] is not None, "edited_by": c["edited_by"], "edited_at": c["edited_at"],
                          "model_answer": c["model_answer"] if c["edited_by"] else None, "restricted": False})
    counts: dict[str, int] = {}
    for c in cells:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    return {**{k: review[k] for k in ("review_id", "title", "container_kind", "container_id", "group_by", "owner_member_id",
                                      "playbook_id", "created_at", "updated_at", "row_version", "run_started_at", "archived_at")},
            "my_level": level, "columns": cols, "rows": out_rows, "cells": out_cells, "counts": counts,
            "running": any(r["running"] for r in out_rows) or counts.get("running", 0) > 0}


# ── change the table ─────────────────────────────────────────────────────────

@guard
def update_review(conn, actor: str | None, review_id: str, title: str | None, row_version: int | None) -> dict:
    review = require_review(conn, actor, review_id, "edit")
    check_version(review["row_version"], row_version, "review")
    if title is not None:
        t = title.strip()
        if not t or len(t) > 200:
            raise FirmError(422, "Give the review a title (at most 200 characters)")
        conn.execute("UPDATE tab_reviews SET title = %s WHERE review_id = %s", (t, review_id))
    _touch(conn, review_id)
    conn.commit()
    return get_review(conn, actor, review_id)


@guard
def archive_review(conn, actor: str | None, review_id: str) -> dict:
    require_review(conn, actor, review_id, "edit")
    conn.execute("UPDATE tab_reviews SET archived_at = now() WHERE review_id = %s", (review_id,))
    conn.commit()
    audit.record("tabular.archive", member_id=actor, object_type="tab_review", object_id=review_id)
    return {"review_id": review_id, "archived": True}


@guard
def add_columns(conn, actor: str | None, review_id: str, columns: list[dict]) -> dict:
    require_review(conn, actor, review_id, "edit")
    clean = [_column_input(c) for c in columns]
    have = one(conn, "SELECT count(*) AS n, coalesce(max(position), -1) + 1 AS next FROM tab_columns WHERE review_id = %s",
               (review_id,))
    if have["n"] + len(clean) > MAX_COLUMNS:
        raise FirmError(422, f"At most {MAX_COLUMNS} columns")
    for i, c in enumerate(clean):
        conn.execute("""INSERT INTO tab_columns (column_id, review_id, position, label, question, answer_format, choices)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                     (_new("TCL"), review_id, have["next"] + i, c["label"], c["question"], c["answer_format"], c["choices"]))
    _seed_cells(conn, review_id)
    _touch(conn, review_id)
    conn.commit()
    return get_review(conn, actor, review_id)


@guard
def update_column(conn, actor: str | None, review_id: str, column_id: str, changes: dict) -> dict:
    """Renaming keeps the answers; changing the question, format or choices makes the column's answers stale."""
    require_review(conn, actor, review_id, "edit")
    col = one(conn, "SELECT * FROM tab_columns WHERE review_id = %s AND column_id = %s FOR UPDATE", (review_id, column_id))
    if col is None:
        raise FirmError(404, "Column not found")
    merged = _column_input({**{k: col[k] for k in ("label", "question", "answer_format", "choices")}, **changes})
    meaning = any(merged[k] != col[k] for k in ("question", "answer_format", "choices"))
    conn.execute("""UPDATE tab_columns SET label = %s, question = %s, answer_format = %s, choices = %s,
                           revision = revision + %s WHERE column_id = %s""",
                 (merged["label"], merged["question"], merged["answer_format"], merged["choices"], int(meaning), column_id))
    if meaning:
        conn.execute("""UPDATE tab_cells SET status = 'stale'
                        WHERE column_id = %s AND status IN ('done', 'not_found', 'failed') AND edited_by IS NULL""",
                     (column_id,))
    if "position" in changes:
        cols = [r["column_id"] for r in rows(conn, "SELECT column_id FROM tab_columns WHERE review_id = %s AND column_id <> %s "
                                                   "ORDER BY position", (review_id, column_id))]
        cols.insert(max(0, min(int(changes["position"]), len(cols))), column_id)
        for i, cid in enumerate(cols):
            conn.execute("UPDATE tab_columns SET position = %s WHERE column_id = %s", (i, cid))
    _touch(conn, review_id)
    conn.commit()
    return get_review(conn, actor, review_id)


@guard
def delete_column(conn, actor: str | None, review_id: str, column_id: str) -> dict:
    require_review(conn, actor, review_id, "edit")
    if one(conn, "SELECT count(*) AS n FROM tab_columns WHERE review_id = %s", (review_id,))["n"] <= 1:
        raise FirmError(409, "A review keeps at least one column")
    gone = one(conn, "DELETE FROM tab_columns WHERE review_id = %s AND column_id = %s RETURNING column_id", (review_id, column_id))
    if gone is None:
        raise FirmError(404, "Column not found")
    _touch(conn, review_id)
    conn.commit()
    return get_review(conn, actor, review_id)


@guard
def add_rows(conn, actor: str | None, review_id: str, document_ids: list[str], folders: list[str]) -> dict:
    review = require_review(conn, actor, review_id, "edit")
    added = _add_rows(conn, actor, review, document_ids, folders)
    _touch(conn, review_id)
    conn.commit()
    return {**get_review(conn, actor, review_id), "added": added}


@guard
def delete_row(conn, actor: str | None, review_id: str, row_id: str) -> dict:
    require_review(conn, actor, review_id, "edit")
    gone = one(conn, "DELETE FROM tab_rows WHERE review_id = %s AND row_id = %s RETURNING row_id", (review_id, row_id))
    if gone is None:
        raise FirmError(404, "Row not found")
    _touch(conn, review_id)
    conn.commit()
    return get_review(conn, actor, review_id)


@guard
def override_cell(conn, actor: str | None, review_id: str, row_id: str, column_id: str, answer: str | None) -> dict:
    """A lawyer's own answer replaces the model's (kept for the record); ``None`` puts the model's answer back."""
    require_review(conn, actor, review_id, "edit")
    cell = one(conn, """SELECT c.* FROM tab_cells c JOIN tab_rows r USING (row_id)
                        WHERE r.review_id = %s AND c.row_id = %s AND c.column_id = %s FOR UPDATE""",
               (review_id, row_id, column_id))
    if cell is None:
        raise FirmError(404, "Cell not found")
    readable = set(_readable_documents(conn, actor, list(cell["source_documents"] or [])))
    if any(d not in readable for d in (cell["source_documents"] or [])):
        raise FirmError(404, "Cell not found")
    if answer is None:
        if cell["edited_by"] is None:
            return get_review(conn, actor, review_id)
        conn.execute("""UPDATE tab_cells SET answer = model_answer, model_answer = NULL, edited_by = NULL, edited_at = NULL,
                               updated_at = now() WHERE row_id = %s AND column_id = %s""", (row_id, column_id))
    else:
        text = answer.strip()
        if len(text) > 4000:
            raise FirmError(422, "An answer is at most 4,000 characters")
        conn.execute("""UPDATE tab_cells SET model_answer = CASE WHEN edited_by IS NULL THEN answer ELSE model_answer END,
                               answer = %s, edited_by = %s, edited_at = now(), status = 'done', updated_at = now()
                        WHERE row_id = %s AND column_id = %s""", (text, actor, row_id, column_id))
    _touch(conn, review_id)
    conn.commit()
    audit.record("tabular.cell.override", member_id=actor, object_type="tab_review", object_id=review_id,
                 detail={"row_id": row_id, "column_id": column_id, "cleared": answer is None})
    return get_review(conn, actor, review_id)


@guard
def mark_for_run(conn, actor: str | None, review_id: str, scope: str, column_id: str | None = None,
                 row_id: str | None = None) -> dict:
    """Choose what the next run fills: open cells (pending, stale, failed), everything, a column, a row or a cell.
    Cells a lawyer answered themselves are left alone."""
    review = require_review(conn, actor, review_id, "edit")
    if actor is None:
        raise FirmError(400, "Sign in to run a review")
    where = {"open": "c.status IN ('pending', 'stale', 'failed')",
             "all": "TRUE",
             "column": "c.column_id = %(col)s",
             "row": "c.row_id = %(row)s",
             "cell": "c.column_id = %(col)s AND c.row_id = %(row)s"}.get(scope)
    if where is None:
        raise FirmError(422, "scope must be open, all, column, row or cell")
    _seed_cells(conn, review_id)
    conn.execute(f"""UPDATE tab_cells c SET status = 'pending', error = NULL
                     FROM tab_rows r WHERE r.row_id = c.row_id AND r.review_id = %(rev)s AND c.edited_by IS NULL
                       AND c.status <> 'running' AND {where}""", {"rev": review_id, "col": column_id, "row": row_id})
    conn.execute("UPDATE tab_reviews SET run_by = %s, run_started_at = now() WHERE review_id = %s", (actor, review_id))
    conn.commit()
    audit.record("tabular.run", member_id=actor, object_type="tab_review", object_id=review_id,
                 matter_id=review["container_id"] if review["container_kind"] == "matter" else None,
                 detail={"scope": scope, "column_id": column_id, "row_id": row_id})
    return {"review_id": review_id}


@guard
def stop_run(conn, actor: str | None, review_id: str) -> dict:
    """Stop filling: cells not started yet go back to open (stale) and are filled by the next "Run"; rows already
    being read finish, so no answer is left half-written."""
    review = require_review(conn, actor, review_id, "edit")
    stopped = conn.execute("""UPDATE tab_cells c SET status = 'stale'
                              FROM tab_rows r WHERE r.row_id = c.row_id AND r.review_id = %s AND c.status = 'pending'""",
                           (review_id,)).rowcount
    conn.commit()
    audit.record("tabular.stop", member_id=actor, object_type="tab_review", object_id=review_id,
                 matter_id=review["container_id"] if review["container_kind"] == "matter" else None,
                 detail={"stopped": stopped})
    return {"review_id": review_id, "stopped": stopped}


@guard
def save_as_playbook(conn, actor: str | None, review_id: str, title: str | None) -> dict:
    """The review's questions as a personal column-set playbook, to start the next review with."""
    from app.playbooks import create_playbook

    review = require_review(conn, actor, review_id, "read")
    cols = rows(conn, "SELECT label, question, answer_format, choices FROM tab_columns WHERE review_id = %s ORDER BY position",
                (review_id,))
    return create_playbook(conn, actor, {"kind": "columns", "title": (title or "").strip() or f"{review['title']} questions",
                                         "columns": [dict(c) for c in cols]})
