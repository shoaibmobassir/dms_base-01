"""Long-document editing benchmark: generator gold, edit application and scoring (no model)."""
from __future__ import annotations

import random

from evals.long_doc.editors import apply_ops, apply_quote_edits
from evals.long_doc.generate import build_document, paged_text, tasks_for
from evals.long_doc_edit_eval import score


def _doc():
    return build_document(20, 3)


def test_gold_changes_only_the_planted_paragraphs():
    doc = _doc()
    tasks = {t["kind"]: t for t in tasks_for(doc, random.Random(3))}
    texts = doc.texts()
    pay = tasks["semantic_payment"]["gold"]
    changed = {i for i, (a, b) in enumerate(zip(texts, pay)) if a != b}
    assert changed == {i for i, _ in doc.planted["payment"]}
    assert all(texts[i] == pay[i] for i in doc.planted["distractor30"]), "other 30-day periods must not change"
    ref = tasks["crossref_update"]["gold"]
    assert all(texts[i] == ref[i] for i in doc.planted["clause_x9_refs"]), "Clause 19/29 must not change"
    rename = tasks["rename_term"]["gold"]
    assert any("Suppliers' Forum" in t for t in rename) and not any("Supplier " in t for t in rename)


def test_scoring_counts_recall_precision_and_unintended():
    o = ["a", "b", "c", "d"]
    gold = ["a", "B", "c", "d"]
    assert score(o, gold, gold)["exact"] and score(o, gold, gold)["unintended"] == 0
    s = score(o, gold, ["a", "B", "C", "d"])
    assert s["recall"] == 1.0 and s["unintended"] == 1 and s["precision"] == 0.5
    s = score(o, ["a", "b", "x", "c", "d"], ["a", "b", "x", "c", "d"])
    assert s["recall"] == 1.0 and s["exact"]
    assert score(o, gold, o)["recall"] == 0.0


def test_quote_edits_use_first_match_like_today():
    paras = ["The fee is 30 days.", "Notice is 30 days."]
    out, missed = apply_quote_edits(paras, [{"original": "30 days", "proposed": "45 days"}])
    assert out == ["The fee is 45 days.", "Notice is 30 days."] and missed == 0


def test_paragraph_ops_apply_against_original_ids_and_reject_bad_ones():
    out, rejected = apply_ops(["p0", "p1", "p2"], [
        {"op": "replace", "pid": 1, "text": "P1"}, {"op": "insert_after", "pid": 1, "text": "new"},
        {"op": "delete", "pid": 2}, {"op": "replace", "pid": 9, "text": "x"}])
    assert out == ["p0", "P1", "new"] and rejected == 1


def test_paged_text_marks_pages():
    t = paged_text(_doc().texts())
    assert t.startswith("[Page 1]") and "[Page 2]" in t


def test_span_ops_change_only_the_span_and_reject_misses():
    from evals.long_doc.editors import apply_v2_ops

    out, rejected = apply_v2_ops(["7.3 Pay within 30 days.", "7.4 Notice of 30 days."], [
        {"op": "span", "pid": 0, "old": "30 days", "new": "45 days"},
        {"op": "span", "pid": 1, "old": "sixty", "new": "x"},
        {"op": "insert_after", "pid": 1, "text": "7.5 New."}])
    assert out == ["7.3 Pay within 45 days.", "7.4 Notice of 30 days.", "7.5 New."] and rejected == 1


def test_section_paragraphs_cover_a_whole_schedule():
    from app.chat import doc_nav
    from evals.long_doc.editors import _section_paragraphs

    doc = _doc()
    texts = doc.texts()
    sections = doc_nav.outline(paged_text(texts))
    sched = next(s for s in sections if "Schedule 3" in s.title)
    ids = _section_paragraphs(texts, sections, [sched.section_id])
    assert ids == set(range(doc.planted["schedule3_start"], doc.planted["schedule3_end"]))
