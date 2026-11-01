"""Accepting the Assistant's suggested edits writes them into the document.

Accepting is a decision to change the document, so it changes it: the accepted edits become one new version whose file
is clean (the new text, no struck-through old text). What each edit changed stays readable in History. An edit is placed
by the paragraph it names (``pid``) when that paragraph still reads as it did, otherwise by finding its original
passage in exactly one paragraph; anything else is reported as not applied, never guessed.
"""
from __future__ import annotations

import re
from typing import Any

from app.chat.verify_citations import locate_quote
from app.documents import editing
from app.documents.canonical import caps_heading, numbered_heading
from app.documents.editing import EditError


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def _place(paragraphs: list[str], edit: dict[str, Any]) -> tuple[int, str | None] | None:
    """(pid, new text) for one edit against the paragraphs as they are now, or None when it cannot be placed."""
    original = str(edit.get("original") or "")
    proposed = str(edit.get("proposed") or "")
    op = edit.get("op", "replace")
    pid = edit.get("pid")

    if op == "insert_after":
        # Anchored by the paragraph it follows: the edit carries that paragraph's text, so an earlier change in the same
        # answer that moved paragraphs cannot put it in the wrong place.
        anchor = str(edit.get("anchor") or "")
        if anchor and not (isinstance(pid, int) and 0 <= pid < len(paragraphs) and _norm(paragraphs[pid]) == _norm(anchor)):
            same = [i for i, p in enumerate(paragraphs) if _norm(p) == _norm(anchor)]
            pid = same[0] if len(same) == 1 else None
        if isinstance(pid, int) and 0 <= pid < len(paragraphs):
            return pid, proposed
        return None
    if isinstance(pid, int) and 0 <= pid < len(paragraphs) and _norm(paragraphs[pid]) == _norm(original):
        return pid, (None if op == "delete" or (not proposed and original) else proposed)

    # Placed by the passage itself: it must sit in exactly one paragraph.
    if not original:
        return None
    placed = _place_passage(paragraphs, original, proposed)
    if placed is None:
        # Text indexed before 2026-10-04 carried a "SECTION " label on Word headings that is not in the file, and cards
        # made from it quote the label ("SECTION 5. Remuneration" → "SECTION 3. Remuneration"). Without the label the
        # passage is the heading itself; the label is dropped from the new text too, so it is never written in.
        label = _STALE_LABEL.match(original)
        if label:
            new_label = _STALE_LABEL.match(proposed)
            placed = _place_passage(paragraphs, original[label.end():],
                                    proposed[new_label.end():] if new_label else proposed)
    return placed


# The heading label the old DOCX extraction wrote into the text (never present in the Word file).
_STALE_LABEL = re.compile(r"^SECTION\s+")


def _place_passage(paragraphs: list[str], original: str, proposed: str) -> tuple[int, str | None] | None:
    hits = [i for i, p in enumerate(paragraphs) if original in p]
    if not hits:
        hits = [i for i, p in enumerate(paragraphs) if locate_quote(p, original) is not None]
    if len(hits) != 1:
        return None
    i = hits[0]
    para = paragraphs[i]
    if original in para:
        new = para.replace(original, proposed, 1)
    else:
        loc = locate_quote(para, original)
        new = para[:loc.start] + proposed + para[loc.end:]
    if _norm(para) == _norm(original) and not proposed:
        return i, None  # the whole paragraph goes
    return i, new


def _headline(instruction: str, limit: int = 100) -> str:
    """The instruction's first sentence (or clause), short enough for a line in History."""
    text = " ".join((instruction or "").split())
    first = re.split(r"(?<=[.;:])\s|,\s(?:so that|so|and then|then)\s", text, maxsplit=1)[0].rstrip(".;:, ")
    return first if len(first) <= limit else first[: limit - 1].rsplit(" ", 1)[0] + "…"


def _styles(model: dict) -> tuple[str | None, str | None]:
    """The style the document gives its numbered headings, and its body text (only styles the editor may set)."""
    from collections import Counter

    allowed = set(model.get("styles") or [])
    heads = Counter(p.get("style") for p in model["paragraphs"] if numbered_heading(p["text"]))
    body = Counter(p.get("style") for p in model["paragraphs"]
                   if p["text"].strip() and not numbered_heading(p["text"]) and len(p["text"]) > 60)
    heading = next((s for s, _ in heads.most_common() if s in allowed), None)
    plain = next((s for s, _ in body.most_common() if s in allowed), None)
    return heading, plain


def apply_accepted(conn, document_id: str, member_id: str | None, edits: list[dict[str, Any]], instruction: str = "") -> dict:
    """Write ``edits`` into the document as one clean version.

    Returns ``{version_id, version_number, applied: [edit ids], failed: {edit id: reason}}``. Raises
    ``EditError`` when the document cannot be written (read-only PDF, locked by someone else, no permission).
    """
    model = editing.edit_model(conn, document_id, member_id)
    if model["mode"] == "pdf":
        raise EditError(422, "This document is a PDF, which is read-only; apply the suggestions in the Word original")
    if not model["editable"]:
        raise EditError(403, "You do not have permission to edit this document")
    texts = [p["text"] for p in model["paragraphs"]]
    locked = {p["pid"] for p in model["paragraphs"] if p.get("locked")}
    heading_style, body_style = _styles(model)
    styles_of = [p.get("style") for p in model["paragraphs"]]

    def is_heading(i: int) -> bool:
        return bool(numbered_heading(texts[i]) or caps_heading(texts[i]) or (heading_style and styles_of[i] == heading_style))

    def styled(line: str) -> dict:
        style = heading_style if numbered_heading(line) else body_style
        return {"style": style} if style else {}

    working = list(texts)
    ops: dict[int, dict] = {}
    applied: list[str] = []
    failed: dict[str, str] = {}
    inserted: set[str] = set()
    for edit in edits:
        if edit.get("op") == "insert_after":
            # A paragraph the document already has (or this answer already added) is not added twice.
            text = _norm(str(edit.get("proposed") or ""))
            if text and (text in inserted or any(_norm(p) == text for p in working)):
                failed[edit["id"]] = "that paragraph is already in the document"
                continue
            inserted.add(text)
        placed = _place(working, edit)
        if placed is None:
            failed[edit["id"]] = "its passage was not found in exactly one paragraph of the current document"
            continue
        pid, new = placed
        if pid in locked:
            failed[edit["id"]] = "that paragraph has someone else's pending changes; resolve them first"
            continue
        # Text with line breaks is several paragraphs (a heading and its clause), each styled like its kind.
        lines = [ln.strip() for ln in (new or "").split("\n") if ln.strip()] if new is not None else []
        if edit.get("op") == "insert_after":
            if lines and numbered_heading(lines[0]) and pid < len(texts) and is_heading(pid):
                # A new section never goes between a heading and its clause: it follows the whole section.
                while pid + 1 < len(texts) and not is_heading(pid + 1):
                    pid += 1
            for line in lines:
                ops[100000 + len(ops)] = {"op": "insert_after", "pid": pid, "text": line, **styled(line)}
        elif new is None:
            ops[pid] = {"op": "delete", "pid": pid}
        else:
            ops[pid] = {"op": "replace", "pid": pid, "text": lines[0] if lines else new}
            working[pid] = lines[0] if lines else new
            for line in lines[1:]:
                ops[100000 + len(ops)] = {"op": "insert_after", "pid": pid, "text": line, **styled(line)}
        applied.append(edit["id"])
    if not ops:
        return {"version_id": None, "version_number": None, "applied": [], "failed": failed, "from_version_id": None}

    note = "Assistant: " + (_headline(instruction) or f"{len(applied)} suggested edit{'s' if len(applied) != 1 else ''} accepted")
    out = editing.save_edits(conn, document_id, member_id, model["base_version_id"], list(ops.values()),
                             note=note, mode="clean")
    return {"version_id": out["version_id"], "version_number": out["version_number"], "applied": applied, "failed": failed,
            "from_version_id": model["base_version_id"]}
