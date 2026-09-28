"""review_documents: the Assistant's way to answer the same questions across many documents.

Runs ``app.review.batch`` (screen → one model call per document) and gives the model a
compact table instead of raw text, so a turn can cover hundreds of documents. Each answer
carries the verified quote it rests on; the table is also a grounding source, so statements
the Assistant makes from it are checked like any other.
"""
from __future__ import annotations

from typing import Any

from app.chat.tools.document_tools import DocEntry, DocIndex

MAX_TABLE_CHARS = 60000


def _matter_documents(conn, matter: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT d.document_id FROM documents d JOIN matters m ON m.matter_id = d.matter_id
        WHERE m.matter_id = %(m)s OR upper(m.matter_code) = upper(%(m)s)
        ORDER BY d.doc_date NULLS LAST, d.document_id
        """,
        {"m": matter},
    ).fetchall()
    return [r["document_id"] for r in rows]


def review_documents_tool(
    arguments: dict[str, Any],
    doc_index: DocIndex,
    conn: Any,
    member_id: str | None,
    matter: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from app.review.batch import review_documents

    questions = [str(q) for q in arguments.get("questions") or [] if str(q).strip()]
    if not questions:
        return {"error": "Give at least one question to answer for each document."}, []
    slugs = [str(s) for s in arguments.get("doc_ids") or []]
    ids = [doc_index[s].document_id for s in slugs if s in doc_index]
    scope = arguments.get("matter") or (matter["matter_id"] if matter and not slugs else None)
    if not ids and scope:
        ids = _matter_documents(conn, str(scope))
    if not ids:
        ids = [e.document_id for e in doc_index.values()]
    mode = "screen" if arguments.get("mode") == "screen" else "full"
    out = review_documents(conn, ids, questions, member_id, mode=mode)

    slug_of = {e.document_id: slug for slug, e in doc_index.items()}
    for row in out["rows"]:
        if row["document_id"] not in slug_of:
            slug = f"doc-{len(doc_index)}"
            doc_index[slug] = DocEntry(slug, row["document_id"], row.get("title") or row["document_id"])
            slug_of[row["document_id"]] = slug

    table: list[dict[str, Any]] = []
    used = 0
    for row in out["rows"]:
        if mode == "screen":
            item = {"doc_id": slug_of[row["document_id"]], "title": row.get("title"), "relevance": row["relevance"]}
        else:
            item = {"doc_id": slug_of[row["document_id"]], "title": row.get("title"), "answers": [
                ("not found" if c["not_found"] else
                 f"{c['answer']}" + (f" — “{c['quote']}”" if c["verified"] else " (quote not verified)")
                 + (f" (p. {c['page']})" if c.get("page") else ""))
                for c in row["cells"]
            ]}
        used += len(str(item))
        if used > MAX_TABLE_CHARS:
            break
        table.append(item)
    result: dict[str, Any] = {
        "questions": out["questions"], "documents_reviewed": out["documents"], "mode": mode,
        "rows": table, "stats": out.get("stats"),
        "note": ("Answers come from each document's best passages; each quote was checked against the document. "
                 "Cite a document by its doc_id; read_document a part when an answer needs detail."),
    }
    if len(table) < len(out["rows"]):
        result["truncated"] = f"{len(out['rows']) - len(table)} more rows not shown; narrow the question or the set."
    event = {
        "type": "review_table", "questions": out["questions"], "mode": mode, "stats": out.get("stats"),
        "timings": out.get("timings"),
        "rows": [
            {"document_id": r["document_id"], "doc_id": slug_of[r["document_id"]], "title": r.get("title"),
             "matter_code": r.get("matter_code"),
             **({"relevance": r["relevance"]} if mode == "screen" else {"cells": r["cells"]})}
            for r in out["rows"]
        ],
    }
    return result, [event]
