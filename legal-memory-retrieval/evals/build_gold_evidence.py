#!/usr/bin/env python3
"""Bootstrap refined gold evidence spans from gold documents (C7).

Per gold document, keep the single densest term-matching chunk and a
quoted span window (offsets). Prefer ICA over EL when densities tie
(more fact language). Does not invent non-gold documents.

Writes evals/gold_evidence.jsonl

Usage:
  .venv/bin/python evals/build_gold_evidence.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.db.pool import acquire, close_pool, init_pool
from app.retrieval.evidence import (
    best_evidence_span_offsets,
    evidence_id_for,
    term_density,
)
from app.retrieval.proposition import query_propositions_from_dict
from psycopg.rows import dict_row

# Prefer denser evidence types on density ties (not a hard type filter at retrieve).
_TYPE_TIEBREAK = {
    "Initial Case Assessment": 3,
    "Term Sheet": 2,
    "Engagement Letter": 1,
    "Research Memo": 0,
}


def _pick_best_per_doc(chunks: list[dict], terms: list[str]) -> list[dict]:
    """One gold evidence chunk per document — densest term match."""
    by_doc: dict[str, list[dict]] = {}
    for c in chunks:
        by_doc.setdefault(c["document_id"], []).append(c)

    picked: list[dict] = []
    for _doc_id, items in by_doc.items():
        scored = []
        for c in items:
            dens = term_density(c.get("text") or "", terms)
            tie = _TYPE_TIEBREAK.get(c.get("document_type") or "", 0)
            scored.append((dens, tie, c))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        best_c = scored[0][2]
        if scored[0][0] <= 0:
            # fallback: still include gold-doc chunk (weak)
            best_c = items[0]
        picked.append(best_c)
    return picked


async def main() -> None:
    props_path = ROOT / "evals" / "propositions.jsonl"
    dataset = {
        json.loads(line)["question_id"]: json.loads(line)
        for line in (ROOT / "evals" / "dataset.jsonl").read_text().splitlines()
        if line.strip() and json.loads(line).get("type") == "semantic"
    }
    prop_rows = [
        query_propositions_from_dict(json.loads(line))
        for line in props_path.read_text().splitlines()
        if line.strip()
    ]

    await init_pool()
    out_rows = []
    try:
        for qp in prop_rows:
            q = dataset.get(qp.query_id)
            if not q:
                continue
            gold_docs = list(q.get("expected_documents") or [])
            async with acquire() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        SELECT c.chunk_id, c.document_id, c.matter_id, c.text,
                               d.title, d.document_type
                        FROM chunks c
                        JOIN documents d ON d.document_id = c.document_id
                        WHERE c.document_id = ANY(%(ids)s)
                        ORDER BY c.document_id, c.chunk_index
                        """,
                        {"ids": gold_docs},
                    )
                    chunks = list(await cur.fetchall())

            for prop in qp.propositions:
                terms = list(prop.lexical_terms or [])
                use = _pick_best_per_doc(chunks, terms)
                # Drop zero-density fallbacks — they dilute Evidence Recall.
                use = [c for c in use if term_density(c.get("text") or "", terms) > 0]
                if not use:
                    # last resort: densest gold-doc chunks even if weak
                    use = _pick_best_per_doc(chunks, terms)[: max(1, min(5, len(chunks)))]
                gold = []
                for c in use:
                    text = c.get("text") or ""
                    dens = term_density(text, terms)
                    start, end, quoted = best_evidence_span_offsets(text, terms)
                    gold.append({
                        "evidence_id": evidence_id_for(c["chunk_id"], prop.id),
                        "document_id": c["document_id"],
                        "chunk_id": c["chunk_id"],
                        "matter_id": c.get("matter_id"),
                        "relationship": "SUPPORTS",
                        "start_offset": start,
                        "end_offset": end,
                        "quoted_text": quoted[:400],
                        "document_type": c.get("document_type"),
                        "title": c.get("title"),
                        "term_density": round(dens, 4),
                        "annotation_source": (
                            "bootstrap_dense_span" if dens > 0 else "bootstrap_gold_doc_chunk"
                        ),
                        "term_matched": dens > 0,
                    })
                out_rows.append({
                    "query_id": qp.query_id,
                    "proposition_id": prop.id,
                    "claim": prop.claim,
                    "n_gold_evidence": len(gold),
                    "n_gold_docs": len({g["document_id"] for g in gold}),
                    "gold_evidence": gold,
                })
                print(
                    f"{qp.query_id} {prop.id}: evidence={len(gold)} "
                    f"docs={len({g['document_id'] for g in gold})} "
                    f"mean_density={sum(g['term_density'] for g in gold)/max(len(gold),1):.2f}",
                    flush=True,
                )
    finally:
        await close_pool()

    out = ROOT / "evals" / "gold_evidence.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for row in out_rows:
            f.write(json.dumps(row) + "\n")
    print(f"wrote {out} ({len(out_rows)} proposition rows)")


if __name__ == "__main__":
    asyncio.run(main())
