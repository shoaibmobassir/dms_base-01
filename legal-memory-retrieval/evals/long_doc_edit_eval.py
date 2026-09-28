"""Long-document editing benchmark: architectures × tasks × document sizes (plan 15, Part D).

Scoring compares paragraph lists. The gold change set is the paragraph-level diff original → gold;
the result change set is original → result (difflib opcodes, whitespace-normalised):

  edit recall     gold changes the result also made / gold changes
  edit precision  gold changes made / all changes the result made
  unintended      changes the result made that gold does not (must be 0)
  exact           result == gold

plus model calls, largest prompt (chars) and wall time per task. Results go to
evals/last_long_doc_edit.json and .md; the decision record cites them.

    python evals/long_doc_edit_eval.py --sizes 100,400 --archs baseline,navigate,mapreduce,hybrid
"""
from __future__ import annotations

import argparse
import difflib
import json
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from evals.long_doc.editors import ARCHITECTURES, bedrock_llm  # noqa: E402
from evals.long_doc.generate import build_document, tasks_for  # noqa: E402

OUT = ROOT / "evals"


def _n(t: str) -> str:
    return " ".join(t.split())


def changes(original: list[str], edited: list[str]) -> set[tuple]:
    a, b = [_n(t) for t in original], [_n(t) for t in edited]
    out: set[tuple] = set()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace" and i2 - i1 == j2 - j1:
            out |= {("rep", i1 + k, b[j1 + k]) for k in range(i2 - i1)}
            continue
        out |= {("del", i) for i in range(i1, i2)}
        if j2 > j1:
            out.add(("ins", i1, tuple(b[j1:j2])))
    return out


def score(original: list[str], gold: list[str], result: list[str]) -> dict:
    g, r = changes(original, gold), changes(original, result)
    hit = len(g & r)

    def show(items):
        out = []
        for c in sorted(items, key=str)[:3]:
            i = c[1]
            before = original[i] if isinstance(i, int) and i < len(original) else ""
            out.append({"change": c[0], "at": i, "before": before[:200], "after": str(c[2] if len(c) > 2 else "")[:200]})
        return out

    return {
        "sample_unintended": show(r - g), "sample_missed": show(g - r),
        "gold_changes": len(g), "result_changes": len(r),
        "recall": round(hit / len(g), 4) if g else 1.0,
        "precision": round(hit / len(r), 4) if r else (1.0 if not g else 0.0),
        "unintended": len(r - g),
        "exact": [_n(t) for t in result] == [_n(t) for t in gold],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="100,400")
    ap.add_argument("--archs", default="baseline,navigate,mapreduce,hybrid")
    ap.add_argument("--kinds", default="")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--tag", default="long_doc_edit")
    args = ap.parse_args()

    from app.config import settings

    settings.grounding_enabled = False  # editing is scored on the document, not on the chat prose
    llm = bedrock_llm()
    jobs = []
    for pages in [int(s) for s in args.sizes.split(",")]:
        doc = build_document(pages, args.seed)
        for task in tasks_for(doc, random.Random(args.seed * 100 + pages)):
            if args.kinds and task["kind"] not in args.kinds.split(","):
                continue
            for arch in args.archs.split(","):
                jobs.append((pages, doc, task, arch))

    def run(job):
        pages, doc, task, arch = job
        original = doc.texts()
        t0 = time.perf_counter()
        try:
            res = ARCHITECTURES[arch](original, task["instruction"], llm)
            out = {**score(original, task["gold"], res.paragraphs), "calls": res.calls,
                   "peak_prompt_chars": res.peak_prompt_chars, "seconds": round(res.seconds, 1), "notes": res.notes}
        except Exception as exc:
            out = {"error": repr(exc)[:300], "recall": 0.0, "precision": 0.0, "unintended": 0, "exact": False,
                   "seconds": round(time.perf_counter() - t0, 1)}
        row = {"pages": pages, "kind": task["kind"], "arch": arch, **out}
        print(json.dumps({k: v for k, v in row.items() if k != "notes"}), flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(run, jobs))

    summary: dict = {}
    for arch in args.archs.split(","):
        rs = [r for r in rows if r["arch"] == arch]
        summary[arch] = {
            "tasks": len(rs),
            "exact": sum(r["exact"] for r in rs),
            "recall": round(statistics.fmean(r["recall"] for r in rs), 3),
            "precision": round(statistics.fmean(r["precision"] for r in rs), 3),
            "unintended_total": sum(r["unintended"] for r in rs),
            "errors": sum(1 for r in rs if r.get("error")),
            "median_s": round(statistics.median(r["seconds"] for r in rs), 1),
            "max_prompt_chars": max((r.get("peak_prompt_chars") or 0) for r in rs),
            "calls_total": sum(r.get("calls") or 0 for r in rs),
        }
    report = {"at": time.strftime("%Y-%m-%d %H:%M"), "model": settings.bedrock_model, "summary": summary, "rows": rows}
    (OUT / f"last_{args.tag}.json").write_text(json.dumps(report, indent=1))

    kinds = sorted({r["kind"] for r in rows})
    lines = [f"# Long-document editing ({report['at']}, model {settings.bedrock_model})", "",
             "| Architecture | exact | recall | precision | unintended | errors | median s | max prompt chars | calls |",
             "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for arch, s in summary.items():
        lines.append(f"| {arch} | {s['exact']}/{s['tasks']} | {s['recall']} | {s['precision']} | {s['unintended_total']} | "
                     f"{s['errors']} | {s['median_s']} | {s['max_prompt_chars']:,} | {s['calls_total']} |")
    lines += ["", "Recall by task (pages):", "", "| Architecture | " + " | ".join(kinds) + " |", "|---|" + "--:|" * len(kinds)]
    for arch in summary:
        cells = []
        for k in kinds:
            rs = [r for r in rows if r["arch"] == arch and r["kind"] == k]
            cells.append(" / ".join(f"{r['recall']:.2f}{'' if not r['unintended'] else '⚠' + str(r['unintended'])}" for r in sorted(rs, key=lambda r: r["pages"])))
        lines.append(f"| {arch} | " + " | ".join(cells) + " |")
    (OUT / f"last_{args.tag}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
