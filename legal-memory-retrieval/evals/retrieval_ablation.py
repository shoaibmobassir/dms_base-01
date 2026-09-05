#!/usr/bin/env python3
"""P5.5 controlled ablation — same dataset, vary FUSION_POLICY only.

Usage:
  .venv/bin/python evals/retrieval_ablation.py
  .venv/bin/python evals/retrieval_ablation.py --policies p55_repair,p53
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = {
    "recall@5": 0.4021,
    "recall@10": 0.5895,
    "recall@20": 0.6914,
    "hit@10": 0.9238,
    "mrr": 0.6941,
    "ndcg@10": 0.5568,
}


def run_eval(policy: str) -> dict:
    env = os.environ.copy()
    env["FUSION_POLICY"] = policy
    # Isolate last_retrieval_run per policy
    out = ROOT / "evals" / "runs" / f"ablation_{policy}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "evals" / "retrieval_eval.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"eval failed for {policy}: {proc.stderr[-2000:]}")
    # retrieval_eval writes last_retrieval_run.json
    summary = json.loads((ROOT / "evals" / "last_retrieval_run.json").read_text())
    out.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--policies",
        default="p55_repair",
        help="Comma-separated FUSION_POLICY names",
    )
    args = p.parse_args()
    policies = [x.strip() for x in args.policies.split(",") if x.strip()]
    rows = []
    for name in policies:
        print(f"=== ablation: {name} ===", flush=True)
        summary = run_eval(name)
        overall = summary["overall"]
        gate = (
            overall["recall@10"] >= BASELINE["recall@10"]
            and overall["hit@10"] >= BASELINE["hit@10"]
            and overall["mrr"] >= BASELINE["mrr"]
        )
        row = {
            "policy": name,
            **overall,
            "gate_pass": gate,
            "delta_hit@10": round(overall["hit@10"] - BASELINE["hit@10"], 4),
            "delta_mrr": round(overall["mrr"] - BASELINE["mrr"], 4),
            "delta_recall@10": round(overall["recall@10"] - BASELINE["recall@10"], 4),
        }
        rows.append(row)
        print(json.dumps(row, indent=2), flush=True)

    table_path = ROOT / "evals" / "last_retrieval_ablation.json"
    payload = {"baseline": BASELINE, "runs": rows}
    table_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
