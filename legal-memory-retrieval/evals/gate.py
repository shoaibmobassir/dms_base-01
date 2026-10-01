#!/usr/bin/env python3
"""Retrieval non-regression gate for CI.

Compares the latest ``evals/retrieval_eval.py`` summary with ``evals/gate_baseline.json``:

* overall metrics may not drop more than ``tolerance`` below the baseline;
* ``exact`` categories must hit their value exactly — ``permission`` recall@10 = 1.0
  means no restricted document ever reached a member outside its ethical wall.

Run the eval on the corpus *before* ``seed_demo.py`` (which adds restrictions the
baseline did not have). Update the baseline deliberately, in a reviewed commit, when
a change is meant to move the numbers (see docs/CHANGELOG.md discipline).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    baseline = json.loads((ROOT / "evals" / "gate_baseline.json").read_text())
    run = json.loads((ROOT / "evals" / "last_retrieval_run.json").read_text())
    tol = baseline["tolerance"]
    failures, lines = [], []
    for metric, base in baseline["overall"].items():
        got = run["overall"][metric]
        ok = got >= base - tol
        lines.append(f"{'ok  ' if ok else 'FAIL'} overall {metric}: {got:.4f} (baseline {base:.4f}, floor {base - tol:.4f})")
        if not ok:
            failures.append(metric)
    for category, metrics in baseline["exact"].items():
        for metric, want in metrics.items():
            got = run["by_type"].get(category, {}).get(metric)
            ok = got == want
            lines.append(f"{'ok  ' if ok else 'FAIL'} {category} {metric}: {got} (must be {want})")
            if not ok:
                failures.append(f"{category}.{metric}")
    print("\n".join(lines))
    if failures:
        print(f"retrieval gate FAILED: {', '.join(failures)}")
        return 1
    print("retrieval gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
