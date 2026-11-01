"""The Assistant's edits land in the document when it makes them, and can be undone (plan 21, G).

Like an editor that changes the file you asked it to change: an edit the Assistant makes to a Word or text document
is written at once as a new clean version (no tracked changes, no accept step). The answer then shows what changed
(old → new) with Undo, which restores the version from before the answer's first change. A PDF is never changed; its
suggestions stay as comments or recommendation cards, and so do edits the member may not write.

Every apply in one answer is reported as an ``edits_applied`` event; the events of one answer and document share the
``from_version_id`` of the version before that answer's first change, which is what Undo restores.
"""
from __future__ import annotations

import logging
from typing import Any

from app.db.connection import connect

logger = logging.getLogger(__name__)


def _segments(before: str, after: str) -> list[dict]:
    from app.documents.editing import _word_diff

    return _word_diff(before or "", after or "")


def _closest_paragraphs(document_id: str, member_id: str | None, failed: list[dict[str, Any]]) -> None:
    """For an edit whose passage was not found, the current paragraph most like it, so one retry can quote it exactly."""
    import difflib

    from app.documents.editing import edit_model

    try:
        with connect() as conn:
            paragraphs = [p["text"] for p in edit_model(conn, document_id, member_id)["paragraphs"] if p["text"].strip()]
    except Exception:  # noqa: BLE001 — a hint only
        return
    for f in failed:
        if f.get("before"):
            near = difflib.get_close_matches(f["before"], paragraphs, n=1, cutoff=0.4)
            if near:
                f["closest_paragraph_now"] = near[0][:400]


def apply_proposals(event: dict[str, Any], member_id: str | None, turn_from: dict[str, str]) -> tuple[dict | None, dict]:
    """Write one ``edit_proposals`` event's edits into its document now.

    ``turn_from`` maps document id → the version before this answer's first change (filled on the first apply).
    Returns ``(edits_applied event or None, summary for the model)``. ``None`` means nothing was written; the summary
    then says why (no permission, someone else editing, nothing could be placed) and the caller keeps the cards.
    """
    from app.documents.assistant_apply import apply_accepted
    from app.documents.editing import EditError

    doc_id = event["document_id"]
    edits = [dict(e) for e in event.get("edits", [])]
    try:
        with connect() as conn:
            out = apply_accepted(conn, doc_id, member_id, edits, event.get("instruction") or "")
    except EditError as exc:
        return None, {"applied": False, "reason": exc.detail}
    by_id = {e["id"]: e for e in edits}
    failed = [{"before": by_id[i].get("original", ""), "after": by_id[i].get("proposed", ""), "reason": r}
              for i, r in out["failed"].items()]
    if failed:
        _closest_paragraphs(doc_id, member_id, failed)
    if not out["version_id"]:
        return None, {"applied": False, "reason": "none of the edits could be placed in the current document",
                      "failed": failed}
    from_version = turn_from.setdefault(doc_id, out["from_version_id"])
    changes = []
    for i in out["applied"]:
        e = by_id[i]
        op = e.get("op") or ("delete" if not e.get("proposed") else "replace")
        before = "" if op == "insert_after" else e.get("original", "")
        after = "" if op == "delete" else e.get("proposed", "")
        changes.append({"op": op, "before": before, "after": after, "page": e.get("page"),
                        "segments": _segments(before, after) if op == "replace" else None})
    applied = {
        "type": "edits_applied",
        "document_id": doc_id,
        "filename": event.get("filename"),
        "instruction": event.get("instruction"),
        "from_version_id": from_version,
        "to_version_id": out["version_id"],
        "version_number": out["version_number"],
        "changes": changes,
        "failed": failed,
    }
    summary = {
        "applied": True,
        "version_number": out["version_number"],
        "changed": len(changes),
        "failed": failed,
        "note": (f"These {len(changes)} change(s) are now in the document as version {out['version_number']} (clean, "
                 "no tracked changes); the lawyer can Undo. Do not propose them again. The document now reads as "
                 "changed: read it again before any further edit." + (
                     f" {len(failed)} edit(s) could not be placed; say which and why." if failed else "")),
    }
    return applied, summary


def applied_groups(events: list[dict[str, Any]], document_id: str) -> list[dict[str, Any]]:
    return [e for e in events or [] if e.get("type") == "edits_applied" and e.get("document_id") == document_id]


def undo_message_changes(conn, events: list[dict[str, Any]], document_id: str, member_id: str | None) -> dict:
    """Restore ``document_id`` to the version before this answer's changes (raises ``EditError``).

    Marks the answer's ``edits_applied`` events with ``undone_version_id`` (the caller saves the events).
    """
    from app.documents.editing import EditError, restore_version

    groups = [g for g in applied_groups(events, document_id) if not g.get("undone_version_id")]
    if not groups:
        raise EditError(404, "There are no changes from this answer to undo")
    current = conn.execute("SELECT current_version_id FROM documents WHERE document_id = %s", (document_id,)).fetchone()
    last = groups[-1]["to_version_id"]
    if not current or current["current_version_id"] != last:
        raise EditError(409, "The document has changed since these edits (a newer version exists). "
                             "Restore an earlier version from History instead.")
    out = restore_version(conn, document_id, member_id, groups[0]["from_version_id"], last,
                          note="Undo the Assistant's changes")
    for g in groups:
        g["undone_version_id"] = out["version_id"]
        g["undone_version_number"] = out["version_number"]
    return out


def undo_latest_in_conversation(session_id: str, document_id: str, member_id: str | None) -> dict:
    """The undo tool: undo the latest answer in this conversation that changed ``document_id`` and is not undone."""
    from app.chat.store import get_messages, set_message_events
    from app.documents.editing import EditError

    with connect() as conn:
        for msg in reversed(get_messages(conn, session_id)):
            events = list(msg.events or [])
            if [g for g in applied_groups(events, document_id) if not g.get("undone_version_id")]:
                try:
                    out = undo_message_changes(conn, events, document_id, member_id)
                except EditError as exc:
                    return {"undone": False, "reason": exc.detail}
                set_message_events(conn, msg.id, events)
                conn.commit()
                return {"undone": True, "restored_version_number": out["restored_version_number"],
                        "version_number": out["version_number"],
                        "note": (f"Undone: the document is back to how version {out['restored_version_number']} read, "
                                 f"saved as version {out['version_number']}. Say so in one sentence.")}
    return {"undone": False, "reason": "This conversation has made no changes to that document that are not undone. "
                                       "Say so; do not claim anything was undone."}


def history_note(events: list[dict[str, Any]] | None) -> str:
    """One line per document action in an earlier answer, for the model's view of the conversation."""
    lines = []
    for e in events or []:
        if e.get("type") == "edits_applied":
            state = f"undone as v{e['undone_version_number']}" if e.get("undone_version_id") else "in the document"
            lines.append(f"[Changed {e.get('filename') or e['document_id']} → v{e.get('version_number')}: "
                         f"{len(e.get('changes') or [])} change(s), {state}]")
        elif e.get("type") == "edit_proposals":
            statuses = [x.get("status") for x in e.get("edits") or []]
            lines.append(f"[Suggested {len(statuses)} edit(s) to {e.get('filename')}: "
                         f"{statuses.count('accepted')} accepted, {statuses.count('pending')} pending, not applied]")
        elif e.get("type") == "comments_added":
            lines.append(f"[Added {len(e.get('comments') or [])} comment(s) to {e.get('filename')}]")
    return "\n".join(lines)
