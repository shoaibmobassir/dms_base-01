"""D3: tracked changes in the original .docx — fidelity checks on every benchmark task.

Uses the GOLD edits (not a model) so only the Word-file writing is under test. For each task:

  accept_ok      accepting all changes gives exactly the gold paragraphs
  reject_ok      rejecting all changes gives exactly the original paragraphs
  untouched_ok   every paragraph the edit does not touch keeps its style and run formatting
  prefix_ok      in replaced paragraphs, formatting before the first change is kept (e.g. bold clause numbers)
  reopen_ok      python-docx reopens the file

Word / LibreOffice rendering is NOT checked here (neither is installed on this machine).

    python -m evals.long_doc.docx_check --sizes 100,400
"""
from __future__ import annotations

import argparse
import difflib
import io
import json
import random
import time
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from app.drafting.docx_tracked import apply_tracked_changes, formatting_signature, view
from evals.long_doc.generate import build_document, tasks_for, to_docx

OUT = Path(__file__).resolve().parents[1]


def gold_ops(original: list[str], gold: list[str]) -> list[dict]:
    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, original, gold, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace" and i2 - i1 == j2 - j1:
            ops += [{"op": "replace", "pid": i1 + k, "text": gold[j1 + k]} for k in range(i2 - i1)]
            continue
        ops += [{"op": "delete", "pid": i} for i in range(i1, i2)]
        for k, text in enumerate(gold[j1:j2]):
            ops.append({"op": "insert_after", "pid": i1 - 1 if i2 == i1 else i2 - 1, "text": text})
    return ops


def _body_paras(docx_bytes: bytes):
    doc = Document(io.BytesIO(docx_bytes))
    return [p for p in doc.element.body.iter(qn("w:p")) if not any(a.tag == qn("w:tbl") for a in p.iterancestors())]


def _is_inserted(p_el) -> bool:
    mark = p_el.find(f"{qn('w:pPr')}/{qn('w:rPr')}")
    return mark is not None and mark.find(qn("w:ins")) is not None


def check(doc, task) -> dict:
    keep = [i for i, p in enumerate(doc.paras) if p.style != "Table"]
    original = [doc.paras[i].text for i in keep]
    tables = {p.text for p in doc.paras if p.style == "Table"}  # tables are not body paragraphs in Word
    gold = [t for t in task["gold"] if t not in tables]
    ops = gold_ops(original, gold)
    buf = io.BytesIO()
    to_docx(doc, buf)
    src = buf.getvalue()
    t0 = time.perf_counter()
    out, stats = apply_tracked_changes(src, ops, date="2026-09-28T00:00:00Z")
    ms = round((time.perf_counter() - t0) * 1000, 1)
    touched = {op["pid"] for op in ops}
    before = _body_paras(src)
    after = [p for p in _body_paras(out) if not _is_inserted(p)]
    untouched_ok = len(before) == len(after) and all(
        formatting_signature(b) == formatting_signature(a) for i, (b, a) in enumerate(zip(before, after)) if i not in touched)
    prefix_ok = True
    for op in ops:
        if op["op"] != "replace":
            continue
        b, a = before[op["pid"]], after[op["pid"]]
        orig_first = formatting_signature(b)[1][:1]
        new_first = [r for r in a.iter(qn("w:r")) if r.find(qn("w:t")) is not None][:1]
        if orig_first and new_first:
            rpr = new_first[0].find(qn("w:rPr"))
            props = tuple(sorted((c.tag.split("}")[1], c.get(qn("w:val")) or "1") for c in rpr)) if rpr is not None else ()
            prefix_ok &= props == orig_first[0][0]
    try:
        Document(io.BytesIO(out))
        reopen_ok = True
    except Exception:
        reopen_ok = False
    return {
        "ops": len(ops), "stats": stats, "ms": ms,
        "accept_ok": [" ".join(t.split()) for t in view(out, accept=True)] == [" ".join(t.split()) for t in gold],
        "reject_ok": [" ".join(t.split()) for t in view(out, accept=False)] == [" ".join(t.split()) for t in original],
        "untouched_ok": untouched_ok, "prefix_ok": prefix_ok, "reopen_ok": reopen_ok,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="100,400")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    rows = []
    for pages in [int(s) for s in args.sizes.split(",")]:
        doc = build_document(pages, args.seed)
        for task in tasks_for(doc, random.Random(args.seed * 100 + pages)):
            r = {"pages": pages, "kind": task["kind"], **check(doc, task)}
            rows.append(r)
            print(json.dumps(r), flush=True)
    ok = all(r[k] for r in rows for k in ("accept_ok", "reject_ok", "untouched_ok", "prefix_ok", "reopen_ok"))
    (OUT / "last_docx_tracked.json").write_text(json.dumps({"all_ok": ok, "rows": rows}, indent=1))
    print("ALL OK" if ok else "FAILURES")


if __name__ == "__main__":
    main()
