#!/usr/bin/env python3
"""Demo: Apex Chambers dummy-firm retrieval + grounded answers on realistic queries."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from psycopg.rows import dict_row

from app.answers.generate import answer_question
from app.db.connection import connect
from app.retrieval.engine import retrieve

MEMBER = "MEM-00001"

DEMO_QUERIES = [
    {
        "label": "M&A indemnity (cross-document)",
        "query": "What indemnity cap and locked-box leakage clauses do we usually negotiate in M&A?",
        "type": "cross_document",
    },
    {
        "label": "Exact matter lookup",
        "query": "What is matter MTR-2017-00006 about?",
        "type": "exact",
    },
    {
        "label": "SIAC arbitration experience",
        "query": "Have we obtained SIAC emergency interim relief in cross-border JV disputes?",
        "type": "semantic",
    },
    {
        "label": "Shareholder oppression (NCLT)",
        "query": "Section 241 oppression petition promoter siphoning board exclusion",
        "type": "matter_retrieval",
    },
    {
        "label": "Restricted matter (ACL — should abstain for outside counsel)",
        "query": "What is the claim amount in matter MTR-2018-00412?",
        "type": "permission",
        "member": "RESTRICTED_DEMO",
    },
]


def _print_hits(hits: list[dict], limit: int = 5) -> None:
    for i, h in enumerate(hits[:limit], 1):
        score = h.get("rerank_score", h.get("fused_score", 0))
        snippet = (h.get("text") or "")[:120].replace("\n", " ")
        print(f"    {i}. [{h['document_id']}] {h.get('title', '')[:50]} — score={score:.3f}")
        print(f"       {snippet}…")


def main() -> None:
    print("=" * 72)
    print("APEX CHAMBERS — Dummy firm retrieval + AI demo")
    print("Corpus: 1,000 matters · 38,232 documents · 20,456 arguments · 80 restricted")
    print("=" * 72)

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT COUNT(*) AS n FROM documents")
            n_docs = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM chunks WHERE embedding IS NOT NULL")
            n_emb = cur.fetchone()["n"]
        print(f"\nDatabase loaded: {n_docs:,} documents, {n_emb:,} embedded chunks\n")

        passed = 0
        for item in DEMO_QUERIES:
            member = item.get("member", MEMBER)
            q = item["query"]
            print(f"── {item['label']} ({item['type']})")
            print(f"   Query: {q!r}")
            print(f"   Member: {member}")

            t0 = time.perf_counter()
            hits, latency = retrieve(conn, q, member_id=member, k=10)
            ret_ms = round((time.perf_counter() - t0) * 1000)
            print(f"   Retrieval: {len(hits)} hits in {ret_ms}ms (channels: {latency})")
            _print_hits(hits)

            t1 = time.perf_counter()
            ans = answer_question(conn, q, member_id=member, k=10)
            ans_ms = round((time.perf_counter() - t1) * 1000)
            print(f"   Answer ({ans.get('provider', '?')}): abstained={ans.get('abstained')} ({ans_ms}ms)")
            if ans.get("abstained"):
                print(f"   Reason: {ans.get('reason', 'n/a')}")
            else:
                preview = (ans.get("answer") or "")[:280].replace("\n", " ")
                print(f"   Text: {preview}…")
                print(f"   Citations: {ans.get('citations', [])}")
                cited = set(ans.get("citations") or [])
                retrieved = {h["document_id"] for h in ans.get("hits", [])}
                grounded = cited <= retrieved if cited else True
                print(f"   Grounded: {grounded}")
                if grounded:
                    passed += 1
            print()

        print("=" * 72)
        print(f"Demo complete. {passed}/{len(DEMO_QUERIES)} answerable queries returned grounded citations.")
        print("Run full benchmarks: python evals/retrieval_eval.py && python evals/answer_eval.py")


if __name__ == "__main__":
    main()
