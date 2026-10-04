"""Follow-up questions in Ask the Firm.

A follow-up ("What about the appeal?") only makes sense next to the answer it follows.
The earlier question is folded into the retrieval query, and the earlier answer's scope
is inherited, so evidence is gathered for the whole conversation topic. The stored
answer keeps the member's own wording and points back at the earlier answer.
"""
from __future__ import annotations

from typing import Any

from app.km import ask_answers

_PREVIOUS_MAX = 400


def standalone_question(previous: str, follow_up: str) -> str:
    """One self-contained question for retrieval and the model."""
    prev = " ".join((previous or "").split())
    if len(prev) > _PREVIOUS_MAX:
        # Keep how the thread began (its topic) and where it has got to.
        half = _PREVIOUS_MAX // 2
        prev = f"{prev[:half]} ... {prev[-half:]}"
    new = " ".join((follow_up or "").split())
    if not prev:
        return new
    return f"{prev} Follow-up: {new}"


def inherited_scope(previous: dict[str, Any], scope: dict | None) -> dict | None:
    """The member's explicit scope, else the scope the earlier answer was asked in."""
    if scope and scope.get("value"):
        return scope
    value = previous.get("scope")
    if not value:
        return scope
    return {"type": previous.get("scope_type") or "auto", "value": value}


def load_previous(conn, member_id: str | None, answer_id: str) -> dict[str, Any] | None:
    """The earlier saved answer, only when this member owns it and can still see its matters."""
    return ask_answers.load_by_id(conn, member_id, answer_id)
