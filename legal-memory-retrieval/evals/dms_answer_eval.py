#!/usr/bin/env python3
"""Evaluate DMS portal answer quality against gold dataset.

Metrics:
  - retrieval_recall: Did expected docs appear in hits?
  - tag_presence: Were expected tags attached to response?
  - answer_contains: Does the answer contain expected keywords?
  - grounding: Are all cited DOC-IDs present in hits?
  - abstention_accuracy: Did it correctly abstain on negative questions?
  - matter_match: Does the response reference the expected matter?
  - key_finding_present: Is key_finding populated?
  - structured_citations_present: Are structured_citations populated?
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

EVALS_DIR = Path(__file__).parent
BASE_URL = "http://localhost:8000"


def run_eval(dataset_path: Path | None = None, base_url: str = BASE_URL) -> dict:
    dataset_path = dataset_path or (EVALS_DIR / "dms_portal_dataset.jsonl")
    questions = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    results: list[dict] = []
    errors: list[dict] = []
    total_latency = 0.0

    with httpx.Client(timeout=120.0) as client:
        for q in questions:
            qid = q["question_id"]
            query = q["question"]
            print(f"  [{qid}] {query[:60]}... ", end="", flush=True)

            try:
                t0 = time.perf_counter()
                resp = client.post(f"{base_url}/api/answers", json={"query": query, "k": 20})
                elapsed = (time.perf_counter() - t0) * 1000
                total_latency += elapsed

                if resp.status_code != 200:
                    errors.append({"qid": qid, "error": f"HTTP {resp.status_code}"})
                    print(f"ERROR {resp.status_code}")
                    continue

                data = resp.json()
            except Exception as e:
                errors.append({"qid": qid, "error": str(e)[:200]})
                print(f"ERROR {e}")
                continue

            score: dict = {"question_id": qid, "type": q["type"], "latency_ms": round(elapsed, 1)}

            # Retrieval recall
            expected_docs = q.get("expected_documents_contain") or []
            hit_titles = " ".join(h.get("title", "") for h in data.get("hits", []))
            if expected_docs:
                found = sum(1 for d in expected_docs if d.lower() in hit_titles.lower())
                score["retrieval_recall"] = round(found / len(expected_docs), 4) if expected_docs else 1.0

            # Answer contains
            expected_contains = q.get("expected_answer_contains") or []
            answer = data.get("answer", "").lower()
            if expected_contains:
                found_kw = sum(1 for kw in expected_contains if kw.lower() in answer)
                score["answer_contains"] = round(found_kw / len(expected_contains), 4)

            # Abstention
            should_abstain = q.get("should_abstain", False)
            actually_abstained = data.get("abstained", False)
            score["abstention_correct"] = actually_abstained == should_abstain

            # Matter match
            expected_matter = q.get("expected_matter")
            if expected_matter:
                matched = data.get("matchedMatters") or []
                matter_ids = {m.get("matter_id") for m in matched}
                hit_matters = {h.get("matter_id") for h in data.get("hits", [])}
                score["matter_match"] = expected_matter in (matter_ids | hit_matters)

            # DMS fields presence
            score["has_key_finding"] = bool(data.get("key_finding"))
            score["has_structured_citations"] = bool(data.get("structured_citations"))
            score["has_sources"] = bool(data.get("sources"))
            score["has_matched_matters"] = bool(data.get("matchedMatters"))
            score["has_tags"] = bool(data.get("tags"))

            # Grounding check
            cited = data.get("citations") or []
            hit_doc_ids = {h.get("document_id") for h in data.get("hits", [])}
            if cited and not actually_abstained:
                grounded = sum(1 for c in cited if c in hit_doc_ids)
                score["grounding"] = round(grounded / len(cited), 4) if cited else 1.0

            results.append(score)
            status = "✓" if score.get("abstention_correct", True) else "✗"
            print(f"{status} ({elapsed:.0f}ms)")

    # ── Aggregate ────────────────────────────────────────────────────
    def avg(rows, key):
        vals = [r[key] for r in rows if key in r]
        return round(sum(vals) / len(vals), 4) if vals else None

    def pct_true(rows, key):
        vals = [r[key] for r in rows if key in r]
        return round(sum(1 for v in vals if v) / len(vals), 4) if vals else None

    summary = {
        "total_questions": len(questions),
        "scored": len(results),
        "errors": len(errors),
        "avg_latency_ms": round(total_latency / max(len(results), 1), 1),
        "metrics": {
            "retrieval_recall": avg(results, "retrieval_recall"),
            "answer_contains": avg(results, "answer_contains"),
            "abstention_accuracy": pct_true(results, "abstention_correct"),
            "matter_match": pct_true(results, "matter_match"),
            "grounding": avg(results, "grounding"),
            "has_key_finding": pct_true(results, "has_key_finding"),
            "has_structured_citations": pct_true(results, "has_structured_citations"),
            "has_tags": pct_true(results, "has_tags"),
        },
        "errors_detail": errors[:5],
    }

    out = EVALS_DIR / "last_dms_answer_run.json"
    out.write_text(json.dumps(summary, indent=2) + "\n")

    detail = EVALS_DIR / "last_dms_eval_detail.jsonl"
    with detail.open("w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    print(f"\n{json.dumps(summary, indent=2)}")
    return summary


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else BASE_URL
    run_eval(base_url=url)
