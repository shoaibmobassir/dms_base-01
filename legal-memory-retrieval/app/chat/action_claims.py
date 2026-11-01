"""The answer may only say a document was changed or undone when a tool in this answer did it (plan 21, G-B).

A model asked to "undo these changes" with no way to undo once answered "The proposed edits have been undone." Here
a sentence that claims an action on a document stays only if the turn's events show that action: changes need an
``edits_applied`` (or comments / a generated file), an undo needs ``edits_undone``. Otherwise the sentence goes and
one plain line says nothing was changed.
"""
from __future__ import annotations

import re
from typing import Any

_UNDO = re.compile(
    r"\b(?:(?:I(?:['’]ve| have)?|we(?:['’]ve| have)?)\s+(?:now\s+)?(?:undone|undid|reverted|rolled\s+back|restored)\b"
    r"|(?:have|has|had|were|was|are|is)\s+(?:now\s+|been\s+|now\s+been\s+)*(?:undone|reverted|rolled\s+back|restored)\b)",
    re.IGNORECASE,
)
_CHANGE = re.compile(
    r"\b(?:(?:I(?:['’]ve| have)?|we(?:['’]ve| have)?)\s+(?:now\s+|also\s+)?(?:applied|changed|updated|edited|amended|"
    r"inserted|added|renumbered|deleted|removed|rewritten|rewrote|implemented|made\s+(?:the|these|all|those)\s+(?:changes|edits))\b"
    r"|(?:changes|edits|amendments)\s+(?:have|has)\s+(?:now\s+)?been\s+(?:applied|made|implemented|written|saved)\b"
    r"|(?:changes|edits)\s+(?:are|were)\s+now\s+(?:in|applied|made)\b"
    r"|^\W*done\b)",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(*])")
NOTE = "_No change was made to the document in this answer._"
_CHANGE_EVENTS = ("edits_applied", "comments_added", "doc_created")


def check_action_claims(text: str, events: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Remove sentences claiming document actions this answer did not take. Returns (text, removed sentences)."""
    if not text:
        return text, []
    types = {e.get("type") for e in events or []}
    changed = any(t in types for t in _CHANGE_EVENTS)
    undone = "edits_undone" in types
    removed: list[str] = []
    out_lines = []
    for line in text.split("\n"):
        kept = []
        for sentence in _SENTENCE.split(line):
            claims_undo = bool(_UNDO.search(sentence))
            claims_change = bool(_CHANGE.search(sentence))
            if (claims_undo and not undone) or (claims_change and not claims_undo and not changed):
                removed.append(sentence.strip())
                continue
            kept.append(sentence)
        joined = " ".join(kept).rstrip()
        if line.strip() and not joined.strip():
            continue  # the whole line was a false claim
        out_lines.append(joined if kept else line)
    out = "\n".join(out_lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    if removed and NOTE not in out:
        out = (out + "\n\n" + NOTE).strip()
    return out, removed
