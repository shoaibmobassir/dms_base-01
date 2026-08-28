# Changelog

Metrics come from `python evals/retrieval_eval.py` on frozen `evals/dataset.jsonl` (n=445).

## 2026-08-23 — Sprint 2: lexical baseline

- **Channels:** keyword (Postgres FTS) + metadata
- **Recall@10:** 0.4073
- **MRR:** 0.3593
- **nDCG@10:** 0.3492
- semantic / similar_matter / graph_reasoning / person_expertise / matter_retrieval: ~0
- negative, permission: ~1.0
- Files: schema, ingest, FTS, eval harness, `POST /retrieve`

## 2026-08-23 — Sprint 3: MiniLM + pgvector (infra shipped; overall gate not met)

Embedder: local `sentence-transformers/all-MiniLM-L6-v2` (384-d, L2-normalized). 41,788 chunks embedded. HNSW cosine index on `chunks.embedding`. ACL identical to FTS. `RETRIEVAL_CHANNELS` selects `keyword`, `metadata`, `vector`, `graph`. Default remains `keyword,metadata` so vector ANN does not pollute negatives.

### Vector-only

- **Recall@10:** 0.2638 (below lexical 0.4073 — **gate fail** on overall)
- **MRR:** 0.3096
- **nDCG@10:** 0.2272
- matter_retrieval Recall@10: 0.20 (was 0)
- person_expertise Recall@10: 0.11 (was 0)
- similar_matter Recall@10: 0.008 (was 0)
- semantic Recall@10: 0.0 (gold sets are entire theme clusters; Recall@10 is capped at 10/|gold|)
- negative Recall@10: 0.0 (ANN always returns neighbors — expected)
- permission Recall@10: 0.5 (DENIED half still holds; AUTHORIZED exact-id questions are weak for MiniLM)

### Hybrid preview (not default)

`keyword,metadata,vector` RRF: Recall@10 **0.3973** (slightly under lexical), MRR **0.4184** (above lexical 0.359). exact Recall@10 0.42 vs lexical 0.37. Negatives still collapse if vector is on.

### Files

- `app/embeddings/minilm.py`, `scripts/embed.py`, `app/retrieval/semantic.py`, `app/retrieval/engine.py`
- Durable memory: `.cursor/skills/legal-memory/`, `docs/NORTH_STAR.md`, `.cursor/rules/legal-memory.mdc`

## 2026-08-23 — Sprint 4: hybrid RRF + routing (gate passed)

Default channels: `keyword,metadata,vector`. Weighted RRF (metadata 1.5, keyword 1.2, vector 0.75). Skip vector on exact matter-id/code lookups. Drop ANN hits with cosine < 0.42; if FTS+metadata are empty, require cosine ≥ 0.50 so negatives abstain.

### Hybrid (now default)

- **Recall@10:** 0.4343 (**beats lexical 0.4073 and vector-only 0.2638**)
- **Hit@10:** 0.7076
- **MRR:** 0.3853
- **nDCG@10:** 0.3666
- exact Recall@10: 0.3879
- negative: 1.0 (restored)
- permission: 1.0
- matter_retrieval: 0.20 (Hit@10 0.60)
- semantic / similar_matter Recall@10: still 0
- Files: `app/retrieval/route.py`, weighted fusion, engine routing, eval `hit@10`

## 2026-08-23 — Sprint 5: cross-encoder rerank (gate passed)

Local `cross-encoder/ms-marco-MiniLM-L-6-v2` on fused top 100. Blend CE (0.55) with min-max RRF (0.45). Skip rerank when the query contains an explicit `MTR-` id (preserves permission 1.0). Eval still requests k=20 so Recall@20 is comparable.

### Hybrid + rerank (now default)

- **Recall@10:** 0.4723 (**beats hybrid 0.4343**)
- **Recall@20:** 0.6140 (**beats hybrid 0.5898** — gold not dropped)
- **Hit@10:** 0.8059 (was 0.7076)
- **MRR:** 0.4882 (was 0.3853)
- **nDCG@10:** 0.4105 (was 0.3666)
- exact Recall@10: 0.4652 (was 0.3879)
- negative: 1.0
- permission: 1.0
- semantic / similar_matter / graph_reasoning Recall@10: still 0
- Files: `app/retrieval/reranker.py`, engine fuse→rerank, `tests/test_reranker.py`

## 2026-08-23 — Sprint 6: query understanding (gate passed)

Rule-based intent + entity parse (no LLM). Strip boilerplate so metadata ILIKE hits titles/clients. Route experience questions onto practice area. Skip vector on ids/codes. `/health` exposes `sprint` + feature flags. `POST /retrieve` returns `understanding`.

### Hybrid + rerank + understanding (now default)

- **Recall@10:** 0.5391 (**beats rerank 0.4723**)
- **Recall@20:** 0.6245 (**beats rerank 0.6140**)
- **Hit@10:** 0.7985 (was 0.8059)
- **MRR:** 0.6082 (was 0.4882)
- **nDCG@10:** 0.4972 (was 0.4105)
- exact Recall@10: 0.6682 (was 0.4652)
- matter_retrieval: 0.3008 (was 0.2545)
- person_expertise: 0.1714 (was 0.0095)
- negative: 1.0
- permission: 1.0
- cross_document Recall@10: 0.0187 (was 0.4732 — **regression**; matter-code queries skip vector. Sprint 7 candidate.)
- semantic / similar_matter / graph_reasoning Recall@10: still ~0
- Files: `app/query/understand.py`, `app/sprint.py`, engine routing, `tests/test_understand.py`, `tests/test_retrieval_edges.py`, `tests/test_health.py`

## 2026-08-24 — Sprint 7: SQL matter graph (gate passed on who/which-matter)

Postgres `relationships` + same-lead/different-client via `matter_members`. Default channels add `graph`. Long queries that only contain a matter *code* keep vector. `graph_reasoning` skips metadata so the seed matter does not bury related matters. API keys in `.env` only; answer LLM still off.

### Hybrid + rerank + understanding + graph (now default)

- **Recall@10:** 0.5539 (**beats Sprint 6 0.5391**)
- **Recall@20:** 0.6570 (**beats 0.6245**)
- **Hit@10:** 0.8329 (was 0.7985)
- **MRR:** 0.6263 (was 0.6082)
- **nDCG@10:** 0.5141 (was 0.4972)
- graph_reasoning Recall@10: 0.4223 (was 0.0); Hit@10 0.9333
- person_expertise: 0.1905 (was 0.1714)
- exact: 0.6682 (held)
- negative / permission: 1.0
- cross_document Recall@10: 0.0219 (**not restored** vs Sprint 5 0.47)
- Files: `app/retrieval/graph.py`, engine graph channel, `app/sprint.py`

## 2026-08-24 — Cross-document restore (pre–Sprint 8)

Long “position … MATTER-CODE” questions are `cross_document`. Keyword/vector stay on the raw question; metadata ranks chunks inside the matter by `ts_rank_cd` instead of dumping the first 50. Rerank is not skipped.

### Hybrid + rerank + understanding + graph (still default)

- **Recall@10:** 0.5889 (**beats Sprint 7 0.5539**)
- **Recall@20:** 0.6922 (**beats 0.6570**)
- **Hit@10:** 0.9189 (was 0.8329)
- **MRR:** 0.6930 (was 0.6263)
- **nDCG@10:** 0.5561 (was 0.5141)
- cross_document Recall@10: 0.4826 (was 0.0219; Sprint 5 was 0.47)
- exact: 0.6561 (was 0.6682)
- graph_reasoning: 0.4223 (held)
- negative / permission: 1.0

## 2026-08-24 — Sprint 8: answers + citations + abstention

`POST /ask` retrieves first, then answers. Citations must be retrieved `DOC-` ids; hallucinated ids are dropped and the call abstains. Empty retrieval abstains (`no_evidence`) without calling an LLM. Named `MTR-`/`DOC-` lookups abstain if that entity is not in the ACL-filtered hits. Groq (then Gemini) when keys exist; extractive snippets otherwise. Retrieval eval is unchanged.

- Answer eval (extractive): abstention accuracy **1.0** on negatives + DENIED (n=38); citation grounding **1.0** on 40 exact questions (cited ⊆ retrieved).
- Files: `app/answers/*`, `POST /ask`, `evals/answer_eval.py`, `tests/test_answers.py`

### Next gate (Sprint 9)

Redis cache + latency. Do not add Kafka/Neo4j/agents.
