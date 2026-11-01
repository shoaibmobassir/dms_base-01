"""An answer may only say a document was changed or undone when a tool in it did so (plan 21, G-B)."""
from __future__ import annotations

from app.chat.action_claims import NOTE, check_action_claims

APPLIED = [{"type": "edits_applied"}]
UNDONE = [{"type": "edits_undone"}]


def test_the_reported_false_undo_is_removed():
    text = ("Let me first undo the proposed edits.\n\nThe proposed edits have been undone. Now let me suggest "
            "improvements to the Employment Agreement.")
    out, removed = check_action_claims(text, [])
    assert "have been undone" not in out and removed == ["The proposed edits have been undone."]
    assert "Now let me suggest improvements" in out and out.endswith(NOTE)


def test_a_real_undo_may_be_reported():
    out, removed = check_action_claims("I've undone the changes; the agreement is back to version 3.", UNDONE)
    assert removed == [] and NOTE not in out


def test_change_claims_need_a_change():
    text = "I've renumbered the sections and added a Definitions clause. Review it in History."
    out, removed = check_action_claims(text, [])
    assert removed and "renumbered" not in out
    kept, none = check_action_claims(text, APPLIED)
    assert none == [] and kept == text


def test_an_undo_claim_needs_an_undo_even_when_something_changed():
    out, removed = check_action_claims("I changed clause 5. The earlier edits have been reverted.", APPLIED)
    assert removed == ["The earlier edits have been reverted."] and "I changed clause 5." in out


def test_offers_and_plans_are_not_claims():
    text = ("Would you like me to implement any of these suggestions? I can make the changes directly. "
            "I will renumber the sections if you want.")
    out, removed = check_action_claims(text, [])
    assert removed == [] and out == text


def test_done_alone_is_a_claim():
    out, removed = check_action_claims("Done. The cards are above.", [])
    assert removed == ["Done."]
