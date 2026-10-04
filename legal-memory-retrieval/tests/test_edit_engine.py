"""Production edit engine with a scripted model: verified substitutions, editable-only spans, ops."""
from __future__ import annotations

import json

from app.editing.engine import apply_plan, paged, plan_edits

PARAS = [
    "1.1 “Supplier” means Northwind Ltd.",
    "7.3 The Customer shall pay each invoice within thirty (30) days of receipt.",
    "7.4 Either party may terminate on thirty (30) days' notice.",
    "7.5 The Supplier shall act as a leading supplier would.",
    "Schedule 3 — Service Credits",
    "S3.1 A credit of 1% applies.",
]


def scripted(plan: dict, edits: dict[int, list[dict]], confirm=lambda changes: True):
    def call(messages):
        system, user = messages[0]["content"], messages[1]["content"]
        if system.startswith("You plan"):
            return json.dumps(plan)
        if system.startswith("A change was applied"):
            decisions = []
            for block in user.split("\n[")[1:]:
                pid = int(block.split("]")[0])
                changes = block.split("CHANGES: ")[1].split("\n")[0]
                decisions.append({"id": pid, "change": confirm(changes)})
            return json.dumps({"decisions": decisions})
        ops = []
        for pid, pid_ops in edits.items():
            if f"[p{pid}] EDITABLE" in user:
                ops += pid_ops
        return json.dumps({"ops": ops})
    return call


def test_substitution_is_case_sensitive_for_defined_terms_and_verified():
    plan = {"search_terms": [], "substitutions": [{"find": "Supplier", "replace": "Vendor", "whole_word": True}]}
    out = plan_edits(PARAS, "Rename Supplier to Vendor", llm=scripted(plan, {}))
    after = apply_plan(PARAS, out.ops)
    assert after[3] == "7.5 The Vendor shall act as a leading supplier would."
    assert after[0] == "1.1 “Vendor” means Northwind Ltd."


def test_verifier_reverts_changes_it_does_not_confirm():
    plan = {"substitutions": [{"find": "thirty (30) days", "replace": "forty-five (45) days", "whole_word": False}]}
    llm = scripted(plan, {}, confirm=lambda changes: "notice" not in changes)
    after = apply_plan(PARAS, plan_edits(PARAS, "payment periods to 45 days", llm=llm).ops)
    assert "forty-five (45) days of receipt" in after[1] and "thirty (30) days' notice" in after[2]


def test_editors_change_only_editable_paragraphs_and_can_delete_a_section():
    plan = {"search_terms": ["S3.1"], "sections": [], "clause_numbers": []}
    # Only p5 matches, so p4 is shown as CONTEXT: its delete must be dropped.
    edits = {5: [{"op": "delete", "pid": 5}, {"op": "delete", "pid": 4}]}
    out = plan_edits(PARAS, "Delete clause S3.1", llm=scripted(plan, edits))
    assert [o for o in out.ops if o["op"] == "delete"] == [{"op": "delete", "pid": 5, "text": ""}]


def test_span_edit_appends_to_a_clause_and_inserts_are_ordered():
    plan = {"search_terms": [], "clause_numbers": ["7.3"]}
    edits = {1: [{"op": "span", "pid": 1, "old": "of receipt.", "new": "of receipt. Time is of the essence."},
                 {"op": "insert_after", "pid": 1, "text": "7.3A New clause."}]}
    out = plan_edits(PARAS, "In clause 7.3 add a sentence", llm=scripted(plan, edits))
    after = apply_plan(PARAS, out.ops)
    assert after[1].endswith("Time is of the essence.") and after[2] == "7.3A New clause."
    assert len(after) == len(PARAS) + 1


def test_paged_offsets_point_at_each_paragraph():
    text, offsets = paged(PARAS * 200)
    assert all(text[o:o + 10] == p[:10] for o, p in zip(offsets, PARAS * 200))


def test_verifier_sees_exact_changes_including_a_corrupted_number():
    from app.editing.engine import show_changes

    shown = show_changes("99.9 Subject to Clause 9, the Supplier", "910.9 Subject to Clause 10, the Supplier")
    # The number is shown whole and the comma beside it is not part of the change (it used to read "[-9,-]{+10,+}").
    assert "[-99.9-]{+910.9+}" in shown and "[-9-]{+10+}," in shown


def test_lowercase_twin_of_a_defined_term_is_never_substituted():
    plan = {"substitutions": [{"find": "Supplier", "replace": "Vendor"}, {"find": "supplier", "replace": "vendor"}]}
    after = apply_plan(PARAS, plan_edits(PARAS, "Rename Supplier to Vendor", llm=scripted(plan, {})).ops)
    assert after[3] == "7.5 The Vendor shall act as a leading supplier would."


def test_named_clause_instruction_limits_substitutions_to_that_clause():
    plan = {"clause_numbers": ["7.3"], "substitutions": [{"find": "thirty (30) days", "replace": "sixty (60) days", "whole_word": False}]}
    after = apply_plan(PARAS, plan_edits(PARAS, "In clause 7.3 change thirty (30) days to sixty (60) days", llm=scripted(plan, {})).ops)
    assert "sixty (60) days of receipt" in after[1] and "thirty (30) days' notice" in after[2]
    # the same substitution with a global instruction applies everywhere
    after = apply_plan(PARAS, plan_edits(PARAS, "Change every thirty (30) days to sixty (60) days", llm=scripted(plan, {})).ops)
    assert "sixty (60) days' notice" in after[2]


def test_ambiguous_span_is_re_asked_not_applied_at_the_first_match():
    paras = ["9.1 Meet quarterly. Agree improvements. Meet quarterly. Agree improvements."]
    calls = {"n": 0}

    def llm(messages):
        system, user = messages[0]["content"], messages[1]["content"]
        if system.startswith("You plan"):
            return json.dumps({"clause_numbers": ["9.1"]})
        if system.startswith("A change was applied"):
            return json.dumps({"decisions": [{"id": 0, "change": True}]})
        calls["n"] += 1
        if "could not be applied" in user:
            old = "Meet quarterly. Agree improvements. Meet quarterly. Agree improvements."
            return json.dumps({"ops": [{"op": "span", "pid": 0, "old": old, "new": old + " Time is of the essence."}]})
        return json.dumps({"ops": [{"op": "span", "pid": 0, "old": "Agree improvements.",
                                    "new": "Agree improvements. Time is of the essence."}]})

    after = apply_plan(paras, plan_edits(paras, "In clause 9.1 add at the end: Time is of the essence.", llm=llm).ops)
    assert calls["n"] == 2 and after[0].endswith("Agree improvements. Time is of the essence.")
    assert after[0].count("Time is of the essence.") == 1


def test_substitution_never_changes_a_paragraphs_own_clause_number():
    paras = ["99.9 Subject to Clause 9, the Supplier acts.", "9.2 Clause 9 applies."]
    plan = {"substitutions": [{"find": "9.", "replace": "10.", "whole_word": False},
                              {"find": "Clause 9", "replace": "Clause 10"}]}
    after = apply_plan(paras, plan_edits(paras, "Update every reference to Clause 9", llm=scripted(plan, {})).ops)
    assert after == ["99.9 Subject to Clause 10, the Supplier acts.", "9.2 Clause 10 applies."]


def test_quoted_all_does_not_make_a_clause_instruction_global():
    plan = {"clause_numbers": ["7.3"], "substitutions": [{"find": "within", "replace": "within all", "whole_word": True}]}
    instruction = "In clause 7.3, replace “within” with “within all”."
    after = apply_plan(PARAS, plan_edits(PARAS, instruction, llm=scripted(plan, {})).ops)
    assert "within all thirty" in after[1] and after[2] == PARAS[2]


def test_lowercase_only_paragraphs_are_not_editor_candidates_for_a_defined_term():
    plan = {"search_terms": ["supplier"], "substitutions": [{"find": "Supplier", "replace": "Vendor"}]}
    seen = []

    def llm(messages):
        system, user = messages[0]["content"], messages[1]["content"]
        if system.startswith("You plan"):
            return json.dumps(plan)
        if system.startswith("A change was applied"):
            return json.dumps({"decisions": [{"id": int(b.split("]")[0]), "change": True} for b in user.split("\n[")[1:]]})
        seen.append(user)
        return json.dumps({"ops": []})

    paras = ["1.1 A leading supplier would.", "1.2 The Supplier shall."]
    plan_edits(paras, "Rename Supplier to Vendor everywhere", llm=llm)
    assert not any("[p0] EDITABLE" in u for u in seen)


def test_ambiguous_append_lands_at_the_end_of_the_clause():
    from app.editing.engine import _apply_spans

    text = "9.1 Agree improvements. Meet. Agree improvements."
    out, rejected = _apply_spans([text], [{"op": "span", "pid": 0, "old": "Agree improvements.",
                                          "new": "Agree improvements. Time is of the essence."}])
    assert rejected == 0 and out[0] == "9.1 Agree improvements. Meet. Agree improvements. Time is of the essence."
