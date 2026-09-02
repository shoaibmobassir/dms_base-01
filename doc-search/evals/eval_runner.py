#!/usr/bin/env python3
"""Run the eval dataset against the live /ask endpoint and score results.

Reasoning:
  We need automated evaluation to:
  1. Catch wrong/hallucinated answers
  2. Verify matter_id and tags are present in responses
  3. Measure retrieval quality (right documents found?)
  4. Confirm abstention works for out-of-scope queries
  5. Provide actionable metrics to guide improvements

Metrics:
  - document_hit_rate: Did the expected document appear in hits?
  - tag_match_rate: Were expected tags present in hits?
  - abstention_accuracy: Did it correctly abstain on negative questions?
  - answer_contains_rate: Does the answer contain expected keywords?
  - primary_doc_accuracy: Is the primary_document the expected one?
  - matter_id_present: Is matter_id populated in the response?
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
    dataset_path = dataset_path or (EVALS_DIR / "dataset.jsonl")
    questions = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    results: list[dict] = []
    total_latency = 0.0
    errors: list[dict] = []

    with httpx.Client(timeout=60.0) as client:
        for q in questions:
            qid = q["question_id"]
            qtype = q["type"]
            query = q["question"]

            try:
                t0 = time.perf_counter()
                resp = client.post(f"{base_url}/ask", json={"query": query, "k": 8})
                elapsed = (time.perf_counter() - t0) * 1000
                total_latency += elapsed

                if resp.status_code != 200:
                    errors.append({"qid": qid, "error": f"HTTP {resp.status_code}", "body": resp.text[:200]})
                    continue

                data = resp.json()
            except Exception as e:
                errors.append({"qid": qid, "error": str(e)[:200]})
                continue

            # ── Score this response ──────────────────────────────────────
            score: dict = {"question_id": qid, "type": qtype, "latency_ms": round(elapsed, 1)}

            # Document hit rate
            expected_docs = set(q.get("expected_documents") or [])
            hit_filenames = {h.get("filename", "") for h in data.get("hits", [])}
            if expected_docs:
                found = expected_docs & hit_filenames
                score["doc_hit_rate"] = len(found) / len(expected_docs)
                score["docs_found"] = sorted(found)
                score["docs_missing"] = sorted(expected_docs - found)
            elif qtype == "negative":
                # For negative, no hits = good
                score["doc_hit_rate"] = 1.0 if not data.get("hits") else 0.0

            # Tag match
            expected_tags = set(q.get("expected_tags") or [])
            if expected_tags:
                all_tags = set()
                for h in data.get("hits", []):
                    for t in (h.get("tags") or []):
                        all_tags.add(t)
                if data.get("primary_document"):
                    for t in (data["primary_document"].get("tags") or []):
                        all_tags.add(t)
                matched_tags = expected_tags & all_tags
                score["tag_match_rate"] = len(matched_tags) / len(expected_tags) if expected_tags else 1.0
                score["tags_found"] = sorted(matched_tags)
                score["tags_missing"] = sorted(expected_tags - matched_tags)

            # Abstention
            should_abstain = q.get("should_abstain", False)
            actually_abstained = data.get("abstained", False)
            if qtype == "negative" or should_abstain:
                score["abstention_correct"] = actually_abstained == should_abstain

            # Answer contains expected keywords
            expected_contains = q.get("expected_answer_contains") or []
            if expected_contains and not actually_abstained:
                answer = data.get("answer", "").lower()
                found_kw = [kw for kw in expected_contains if kw.lower() in answer]
                score["answer_contains_rate"] = len(found_kw) / len(expected_contains)
                score["answer_kw_missing"] = [kw for kw in expected_contains if kw.lower() not in answer]

            # Matter ID present
            primary = data.get("primary_document") or {}
            score["has_matter_id"] = bool(primary.get("matter_id"))
            score["has_document_type"] = bool(primary.get("document_type"))
            score["has_tags"] = bool(primary.get("tags"))
            score["has_key_finding"] = bool(data.get("key_finding"))

            # Primary document accuracy
            if expected_docs and primary.get("filename"):
                score["primary_doc_correct"] = primary["filename"] in expected_docs

            results.append(score)

    # ── Aggregate metrics ────────────────────────────────────────────────
    def avg(rows: list[dict], key: str) -> float:
        vals = [r[key] for r in rows if key in r]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    def count_true(rows: list[dict], key: str) -> tuple[int, int]:
        vals = [r[key] for r in rows if key in r]
        return sum(1 for v in vals if v), len(vals)

    from collections import defaultdict
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_type[r["type"]].append(r)

    abstention_ok, abstention_n = count_true(results, "abstention_correct")

    summary = {
        "total_questions": len(questions),
        "scored": len(results),
        "errors": len(errors),
        "avg_latency_ms": round(total_latency / max(len(results), 1), 1),
        "overall": {
            "doc_hit_rate": avg(results, "doc_hit_rate"),
            "tag_match_rate": avg(results, "tag_match_rate"),
            "answer_contains_rate": avg(results, "answer_contains_rate"),
            "abstention_accuracy": round(abstention_ok / abstention_n, 4) if abstention_n else None,
            "matter_id_present": avg(results, "has_matter_id"),
            "document_type_present": avg(results, "has_document_type"),
            "tags_present": avg(results, "has_tags"),
            "key_finding_present": avg(results, "has_key_finding"),
        },
        "by_type": {
            t: {
                "n": len(rows),
                "doc_hit_rate": avg(rows, "doc_hit_rate"),
                "tag_match_rate": avg(rows, "tag_match_rate"),
            }
            for t, rows in sorted(by_type.items())
        },
        "errors_detail": errors[:10],
    }

    # Save results
    out_path = EVALS_DIR / "last_eval_run.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")

    detail_path = EVALS_DIR / "last_eval_detail.jsonl"
    with detail_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, default=str) + "\n")

    print(json.dumps(summary, indent=2, default=str))
    return summary


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else BASE_URL
    run_eval(base_url=url)
