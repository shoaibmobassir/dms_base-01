---
name: legal-memory
description: >-
  Apex Chambers legal-memory retrieval: frozen dummy-firm corpus, pgvector,
  hybrid RAG, ACL-before-retrieve, retrieval eval gates, Ask the Firm.
  Use when working on retrieval, RAG, embeddings, pgvector, evals, permissions,
  matter graph, citations, sprints 3–12, or legal-memory-retrieval.
---

# Legal memory

## Current gate

**Sprint 8 answers are on.** Cross-document Recall@10 **0.48** (was 0.02). Overall Recall@10 **0.59**. `POST /ask` cites retrieved `DOC-` ids only and abstains with no evidence. Next: Sprint 9 Redis latency — do not add Kafka/Neo4j/agents.

## Thesis

Optimize for: given tens of thousands of documents across hundreds of matters, retrieve the **correct institutional knowledge**, honor relationships and permissions, later produce **evidence-backed answers in ~2s**.

Do **not** optimize for “can an LLM talk about these PDFs?”

## Hard rules

- Corpus is **frozen** at `dummy-firm/data/` (v2: 38232 docs, 1000 matters). Do not regenerate documents to chase scores.
- Measure **retrieval** separately from **answers**. Missing gold docs is not an LLM bug.
- ACL **before** ranking (`permissions.restricted` / `allowed_members`). Never retrieve-all then prompt to hide secrets.
- A sprint ships only if `python evals/retrieval_eval.py` beats the previous `evals/last_retrieval_run.json` on the relevant types.
- No Kafka, Neo4j, or agents until later gates. Answer LLM is Sprint 8 (`POST /ask`).
- Embeddings: local `all-MiniLM-L6-v2` (384-d) behind `app/embeddings`. Do not change dimension without a schema + re-embed.

## Sprint order

0 corpus frozen → 2 Postgres+FTS+eval → **3 vector** → 4 hybrid RRF → 5 rerank → 6 query understanding → 7 SQL graph (only if it wins) → 8 answers+citations+abstention → 9 Redis → 10 traces → 11 eval CI → 12 hardening.

## After each sprint

1. Write metrics into `legal-memory-retrieval/docs/CHANGELOG.md`.
2. Update **Current gate** in this file.
3. Do not start the next sprint in the same change unless the gate passed.

See `reference.md` for ports, commands, and schema.
