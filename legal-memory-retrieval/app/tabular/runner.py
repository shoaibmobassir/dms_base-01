"""Filling a tabular review's cells (plan 22, W4.2).

Workers claim one row at a time with a lease (FOR UPDATE SKIP LOCKED), answer all of that row's pending columns in
one model call over the row's own passages (``app.review.batch``: screen → map, every quote located in the passages),
write the cells and release the row. Two workers never hold the same row; a row whose worker died is claimed again
once its lease lapses, so a restarted server resumes a run where it stopped.

A run is done as the person who started it (``tab_reviews.run_by``): a document they cannot read is never sent to the
model, and each cell records the documents its answer was drawn from.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from app.api.acl import doc_read
from app.chat.verify_citations import locate_quote
from app.db.connection import connect
from app.observability.metrics import TABULAR_CELLS, TABULAR_ROW_SECONDS
from app.review import batch

log = logging.getLogger(__name__)

LEASE = "3 minutes"
MAX_FOLDER_DOCUMENTS = 40
MAX_FOLDER_PASSAGES = 24

FORMAT_HINT = {
    "text": "Answer in one or two sentences.",
    "date": "Answer with the date only, as YYYY-MM-DD.",
    "yes_no": "Answer Yes or No, then a few words of reason. If the passages contain no such provision, answer No and say that no such provision was found.",
    "number": "Answer with the number only.",
    "money": "Answer with the amount and currency, e.g. INR 1,50,00,000 or USD 2 million.",
    "list": "Answer as a short list separated by semicolons; give names in full as the document states them, not defined terms.",
    "choice": "Answer with exactly one of: {choices}.",
}

# Tests replace this with a fake model; it receives the review's model name.
llm_factory: Callable[[str | None], batch.LLMCall] = batch.default_llm

_pool = ThreadPoolExecutor(max_workers=int(os.environ.get("TABULAR_WORKERS", "4")), thread_name_prefix="tabular")
_active: dict[str, int] = {}
_active_lock = threading.Lock()


def question_text(col: dict) -> str:
    hint = FORMAT_HINT[col["answer_format"]].format(choices=", ".join(col["choices"] or []))
    return f"{col['label']}: {col['question']} {hint}"


def normalise(answer: str, col: dict) -> str:
    a = (answer or "").strip()
    fmt = col["answer_format"]
    if fmt == "yes_no":
        low = a.lower()
        if low.startswith("yes"):
            return "Yes" + a[3:]
        if low.startswith("no"):
            return "No" + a[2:]
    if fmt == "choice":
        for c in col["choices"] or []:
            if a.lower().startswith(c.lower()):
                return c
    return a


def _claim(conn, review_id: str, owner: str) -> dict | None:
    row = conn.execute(
        f"""UPDATE tab_rows SET lease_owner = %(o)s, lease_until = now() + interval '{LEASE}'
            WHERE row_id = (
                SELECT r.row_id FROM tab_rows r
                WHERE r.review_id = %(rev)s AND (r.lease_until IS NULL OR r.lease_until < now())
                  AND EXISTS (SELECT 1 FROM tab_cells c WHERE c.row_id = r.row_id AND c.status IN ('pending', 'running'))
                ORDER BY r.position FOR UPDATE SKIP LOCKED LIMIT 1)
            RETURNING *""", {"o": owner, "rev": review_id}).fetchone()
    if row is None:
        conn.commit()
        return None
    # Cells a dead worker left "running" are taken over with the row.
    conn.execute("UPDATE tab_cells SET status = 'running' WHERE row_id = %s AND status IN ('pending', 'running')",
                 (row["row_id"],))
    conn.commit()
    return dict(row)


def _readable(conn, member_id: str | None, ids: list[str]) -> list[str]:
    if not ids:
        return []
    ok = {r["document_id"] for r in conn.execute(
        f"""SELECT d.document_id FROM documents d LEFT JOIN permissions p ON p.matter_id = d.matter_id
            WHERE d.document_id = ANY(%(ids)s) AND d.archived_at IS NULL AND {doc_read('d')}""",
        {"ids": ids, "member_id": member_id})}
    return [i for i in ids if i in ok]


def _folder_documents(conn, review: dict, folder: str) -> list[str]:
    kind, cid = review["container_kind"], review["container_id"]
    home = ("d.home_kind = 'matter' AND d.matter_id = %(cid)s" if kind == "matter"
            else "d.home_kind = %(kind)s AND d.home_id = %(cid)s")
    params = {"kind": kind, "cid": cid, "f": folder, "like": folder + "/%", "n": MAX_FOLDER_DOCUMENTS}
    return [r["document_id"] for r in conn.execute(
        f"""SELECT document_id FROM (
                SELECT d.document_id, d.title FROM documents d
                WHERE {home} AND d.archived_at IS NULL AND (d.folder_path = %(f)s OR d.folder_path LIKE %(like)s)
                UNION
                SELECT l.document_id, d.title FROM document_links l JOIN documents d USING (document_id)
                WHERE l.container_kind = %(kind)s AND l.container_id = %(cid)s
                  AND (l.folder_path = %(f)s OR l.folder_path LIKE %(like)s)) x
            ORDER BY lower(title) LIMIT %(n)s""", params)]


def _passages(conn, row: dict, review: dict, docs: list[str], questions: list[str]) -> tuple[list[dict], dict]:
    screened = batch.screen(conn, docs, questions)
    titles = {r["document_id"]: r["title"] for r in conn.execute(
        "SELECT document_id, title FROM documents WHERE document_id = ANY(%s)", (docs,))}
    if row["document_id"]:
        d = row["document_id"]
        return ([{**p, "document_id": d} for p in screened[d]["passages"]], {"document_id": d, "title": titles.get(d, d)})
    ranked = sorted(docs, key=lambda d: -max(screened[d]["score"] or [0]))
    passages: list[dict] = []
    for d in ranked:
        for p in screened[d]["passages"]:
            if len(passages) >= MAX_FOLDER_PASSAGES:
                break
            passages.append({**p, "document_id": d, "text": f"({titles.get(d, d)}) {p['text']}"})
    return passages, {"document_id": None, "title": f"Folder {row['folder_path']} ({len(docs)} documents)"}


def _cite(cell: dict, passages: list[dict]) -> list[dict]:
    if not cell["quote"]:
        return []
    for p in passages:
        if locate_quote(p["text"], cell["quote"]):
            return [{"document_id": p["document_id"], "chunk_id": p["chunk_id"], "page": p.get("page"),
                     "quote": cell["quote"], "verified": True}]
    return [{"document_id": passages[0]["document_id"] if passages else None, "chunk_id": None, "page": cell.get("page"),
             "quote": cell["quote"], "verified": False}]


def _process(conn, review: dict, row: dict) -> None:
    cols = [dict(r) for r in conn.execute(
        """SELECT c.* FROM tab_columns c JOIN tab_cells x ON x.column_id = c.column_id
           WHERE x.row_id = %s AND x.status = 'running' ORDER BY c.position""", (row["row_id"],))]
    if not cols:
        return
    runner = review["run_by"]
    if row["document_id"]:
        docs = _readable(conn, runner, [row["document_id"]])
        if not docs:
            _fail(conn, row, cols, "The person who ran this review cannot read this document")
            return
    else:
        docs = _readable(conn, runner, _folder_documents(conn, review, row["folder_path"]))
        if not docs:
            _fail(conn, row, cols, "No readable documents in this folder")
            return
    questions = [question_text(c) for c in cols]
    passages, meta = _passages(conn, row, review, docs, questions)
    if not passages:
        _write(conn, row, cols, [{"answer": "", "quote": "", "page": None, "not_found": True, "error": None}] * len(cols),
               passages, docs)
        return
    cells = batch.map_document(meta, questions, passages, llm_factory(review.get("model")))
    _write(conn, row, cols, cells, passages, docs)


def _write(conn, row: dict, cols: list[dict], cells: list[dict], passages: list[dict], docs: list[str]) -> None:
    used = sorted({p["document_id"] for p in passages} or set(docs))
    for col, cell in zip(cols, cells):
        if col["answer_format"] == "yes_no" and cell["not_found"] and not cell.get("error") and passages:
            # A yes/no question about a provision the document's best passages do not contain: the answer is No,
            # said as such (no citation: there is nothing to quote).
            cell = {**cell, "not_found": False, "answer": "No — no such provision was found in the document", "quote": ""}
        status = "failed" if cell.get("error") else ("not_found" if cell["not_found"] else "done")
        TABULAR_CELLS.labels(status=status).inc()
        # Written only if the column still asks what was answered (its revision did not move during the call).
        conn.execute(
            """UPDATE tab_cells c SET status = %(st)s, answer = %(a)s, citations = %(cit)s::jsonb, source_documents = %(src)s,
                      error = %(err)s, column_revision = col.revision, updated_at = now()
               FROM tab_columns col
               WHERE col.column_id = c.column_id AND col.revision = %(rev)s AND c.row_id = %(row)s
                 AND c.column_id = %(colid)s AND c.status = 'running' AND c.edited_by IS NULL""",
            {"st": status, "a": normalise(cell["answer"], col) if status == "done" else None,
             "cit": json.dumps(_cite(cell, passages)), "src": used, "err": cell.get("error"),
             "rev": col["revision"], "row": row["row_id"], "colid": col["column_id"]})
    # A question changed while the model answered: ask again.
    conn.execute("UPDATE tab_cells SET status = 'pending' WHERE row_id = %s AND status = 'running'", (row["row_id"],))
    conn.commit()


def _fail(conn, row: dict, cols: list[dict], why: str) -> None:
    conn.execute("UPDATE tab_cells SET status = 'failed', error = %s, updated_at = now() "
                 "WHERE row_id = %s AND column_id = ANY(%s) AND status = 'running'",
                 (why, row["row_id"], [c["column_id"] for c in cols]))
    conn.commit()


def _release(conn, row_id: str, owner: str) -> None:
    conn.execute("UPDATE tab_rows SET lease_owner = NULL, lease_until = NULL WHERE row_id = %s AND lease_owner = %s",
                 (row_id, owner))
    conn.commit()


def run_now(review_id: str, max_rows: int | None = None) -> int:
    """Work through the review's open rows in this thread; returns rows done. (The server runs this on its pool.)"""
    owner = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
    done = 0
    while max_rows is None or done < max_rows:
        with connect() as conn:
            review = conn.execute("SELECT * FROM tab_reviews WHERE review_id = %s", (review_id,)).fetchone()
            if review is None or review["archived_at"] is not None:
                return done
            row = _claim(conn, review_id, owner)
            if row is None:
                return done
            started = time.perf_counter()
            try:
                _process(conn, dict(review), row)
            except Exception as exc:  # noqa: BLE001 — one row failing must not stop the run
                conn.rollback()
                log.exception("tabular row %s failed", row["row_id"])
                conn.execute("UPDATE tab_cells SET status = 'failed', error = %s WHERE row_id = %s AND status = 'running'",
                             (str(exc)[:300], row["row_id"]))
                conn.commit()
            finally:
                _release(conn, row["row_id"], owner)
                TABULAR_ROW_SECONDS.observe(time.perf_counter() - started)
            done += 1
    return done


def _worker(review_id: str) -> None:
    try:
        run_now(review_id)
    finally:
        with _active_lock:
            _active[review_id] = max(0, _active.get(review_id, 1) - 1)


def start(review_id: str, workers: int | None = None) -> int:
    """Start (or top up) background workers for a review; returns how many were added."""
    from app.config import settings

    want = max(1, workers or getattr(settings, "review_concurrency", 3) or 3)
    with connect() as conn:
        open_rows = conn.execute(
            """SELECT count(*) AS n FROM tab_rows r WHERE r.review_id = %s
               AND EXISTS (SELECT 1 FROM tab_cells c WHERE c.row_id = r.row_id AND c.status IN ('pending', 'running'))""",
            (review_id,)).fetchone()["n"]
    with _active_lock:
        have = _active.get(review_id, 0)
        add = max(0, min(want, open_rows) - have)
        _active[review_id] = have + add
    for _ in range(add):
        _pool.submit(_worker, review_id)
    return add


def needs_workers(conn, review_id: str) -> bool:
    """Open cells and no live lease: a run stopped (server restart) and should be picked up again."""
    row = conn.execute(
        """SELECT EXISTS (SELECT 1 FROM tab_cells c JOIN tab_rows r USING (row_id)
                          WHERE r.review_id = %(r)s AND c.status IN ('pending', 'running'))
                  AND NOT EXISTS (SELECT 1 FROM tab_rows r WHERE r.review_id = %(r)s AND r.lease_until > now()) AS stuck""",
        {"r": review_id}).fetchone()
    with _active_lock:
        idle = _active.get(review_id, 0) == 0
    return bool(row["stuck"]) and idle


def cells_for_assistant(conn, member_id: str | None, review_id: str, row_ids: list[str] | None = None,
                        column_ids: list[str] | None = None, limit: int = 400) -> dict[str, Any]:
    """The filled table in a compact form for the Assistant (``read_review_cells``), redacted like the page."""
    from app.tabular import get_review

    view = get_review(conn, member_id, review_id)
    cols = {c["column_id"]: c for c in view["columns"] if not column_ids or c["column_id"] in column_ids}
    rows = {r["row_id"]: r for r in view["rows"] if not row_ids or r["row_id"] in row_ids}
    out = []
    for c in view["cells"]:
        if c["row_id"] not in rows or c["column_id"] not in cols:
            continue
        r = rows[c["row_id"]]
        if c.get("restricted") or r["restricted"]:
            continue
        cit = (c.get("citations") or [{}])[0] if c.get("citations") else {}
        out.append({"row": r["title"], "document_id": r["document_id"], "column": cols[c["column_id"]]["label"],
                    "answer": c.get("answer") or ("(not found)" if c["status"] == "not_found" else f"({c['status']})"),
                    "quote": cit.get("quote"), "page": cit.get("page"), "edited_by_lawyer": c.get("edited")})
        if len(out) >= limit:
            break
    return {"review_id": review_id, "title": view["title"], "columns": [c["label"] for c in cols.values()],
            "rows": len(rows), "cells": out}
