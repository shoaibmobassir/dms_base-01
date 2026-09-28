"""edit_document: document-wide edits to one (possibly very long) document.

The Assistant gives an instruction; ``app.editing.engine`` plans paragraph-id operations without
reading the whole document into one prompt. The operations are shown to the lawyer as the
usual edit cards (accept / reject, in bulk or one by one). Export writes the accepted ones into
the ORIGINAL Word file as tracked changes and records a new "developing" version.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.chat.tools.document_tools import DocIndex

MODEL_SAMPLE = 15


def _page_of(paragraphs: list[str], pid: int) -> int:
    from app.editing.engine import PAGE_CHARS

    return 1 + sum(len(t) for t in paragraphs[:pid]) // PAGE_CHARS


def edit_document_tool(
    arguments: dict[str, Any],
    doc_index: DocIndex,
    conn: Any,
    member_id: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from app.editing.document import load_editable
    from app.editing.engine import plan_edits

    entry = doc_index.get(str(arguments.get("doc_id") or ""))
    instruction = str(arguments.get("instruction") or "").strip()
    if not entry:
        return {"error": f"Document '{arguments.get('doc_id')}' not found."}, []
    if not instruction:
        return {"error": "Give the change to make, as an instruction."}, []
    doc = load_editable(conn, entry.document_id, member_id)
    if doc is None or not doc.paragraphs:
        return {"error": "The document could not be opened for editing."}, []

    plan = plan_edits(doc.paragraphs, instruction)
    edits = []
    for op in plan.ops:
        pid = op["pid"]
        original = doc.paragraphs[pid] if op["op"] != "insert_after" else ""
        edits.append({
            "id": uuid.uuid4().hex[:10],
            "op": op["op"], "pid": pid,
            "original": original,
            "proposed": op["text"] if op["op"] != "delete" else "",
            "reason": "New paragraph after: " + doc.paragraphs[pid][:80] if op["op"] == "insert_after" else "",
            "page": _page_of(doc.paragraphs, pid),
            "located": True,
            "status": "pending",
        })
    if not edits:
        return {"doc_id": entry.doc_id, "filename": entry.filename, "proposed": 0, "notes": plan.notes,
                "note": "No paragraph needed this change. Tell the lawyer, and say what was searched."}, []
    event = {
        "type": "edit_proposals", "document_id": entry.document_id, "version_id": doc.version_id,
        "filename": entry.filename, "anchoring": "paragraph", "source": doc.source,
        "instruction": instruction, "edits": edits,
    }
    sample = [{"page": e["page"], "op": e["op"], "before": e["original"][:160], "after": e["proposed"][:160]}
              for e in edits[:MODEL_SAMPLE]]
    return {
        "doc_id": entry.doc_id, "filename": entry.filename, "proposed": len(edits),
        "paragraphs_in_document": len(doc.paragraphs), "sample": sample, "notes": plan.notes,
        "note": ("The edits are shown to the lawyer as cards to accept or reject (also in bulk). Summarise what "
                 "changed and anything that needs their judgement; do not list every edit."),
    }, [event]
