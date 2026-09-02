# Legal memory retrieval

Ask the firm: retrieve the right institutional knowledge, cite it, respect permissions, and measure every change against a frozen corpus.

**Ingestion of new documents is frozen.** The corpus lives in `../dummy-firm/data/` (v2: 38,232 documents, 1,000 matters, 500 clients, 100 members). Do not regenerate it to “improve” retrieval. Improve the retrieval stack and prove it on `evals/dataset.jsonl`.

## Build order (do not skip)

| Sprint | What | Gate |
|---|---|---|
| 0 | Dummy firm + gold questions | Done (corpus frozen) |
| **2 (this layer)** | Postgres schema + load + ACL + eval harness | Load completes; eval runs |
| 3 | Vector baseline (pgvector MiniLM) | Infra done; vector-only Recall@10 0.26 did not beat 0.41 |
| 4 | Hybrid RRF + routing | Done. Recall@10 0.43 |
| 5 | Rerank fused top 100 | Done. Recall@10 0.47, MRR 0.49 |
| 6 | Query understanding | Done. Recall@10 0.54, MRR 0.61 |
| 7 | Matter graph (SQL relationships first) | Done. graph_reasoning Recall@10 0.42 |
| 8 | Answer engine + citations + abstention | Done. `POST /api/answers`; citations ⊆ retrieved |
| 9 | Redis cache + latency budget (~2s) | p95 instrumented |
| 10 | OTel + Langfuse + Prometheus | Traces per stage |
| 11 | Eval in CI | Regression on 500 questions |
| 12 | Auth, tenant, rate limits, ACL-before-LLM | Never retrieve then hope |

`POST /api/answers` answers only from retrieved chunks. If gold is missing, that is still a retrieval problem.

## API services (one route per sidebar section)

| Section | Prefix | Endpoints |
|---------|--------|-----------|
| Home | `/api/home` | `GET /stats` |
| Ask Firm AI | `/api/answers` | `POST /` |
| Retrieval | `/api/retrieval` | `POST /` |
| Matters | `/api/matters` | `GET /`, `GET /{id}`, `GET /{id}/arguments`, … |
| Projects | `/api/projects` | `GET /`, `GET /{id}`, `POST /`, `PATCH /{id}/milestones` |
| Documents | `/api/documents` | `GET /`, `GET /{id}`, `GET /{id}/versions`, `POST /ingest` |
| Clients | `/api/clients` | `GET /`, `GET /{id}`, `GET /{id}/matters` |
| People | `/api/people` | `GET /`, `GET /{member_id}` |
| Teams | `/api/teams` | `GET /` |
| Knowledge Vault | `/api/knowledge` | `GET /arguments`, `/precedents`, `/clauses` |
| Live Activity | `/api/activity` | `GET /` |
| Court Deadlines | `/api/tasks` | `GET /` |
| Command search | `/api/search` | `GET /?q=` |
| System | `/api/system` | `GET /health`, `/metrics`, `/info` |

Service discovery: `GET /` returns all prefixes and health URLs. UI: `/ui`.

## Quick start

```bash
cd legal-memory-retrieval
cp .env.example .env
docker compose up -d   # Postgres :55432, Redis :6380
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/ingest.py
python scripts/embed.py
python evals/build_eval.py
python evals/retrieval_eval.py
python evals/answer_eval.py       # abstention + citation grounding (extractive)
uvicorn app.api.main:app --reload --port 8000
```

`POST /api/retrieval` with `{"query": "...", "k": 20}` and header `X-Member-Id: MEM-00001` runs ACL-filtered retrieval. Restricted chunks never enter the candidate set.

`POST /api/answers` with the same body returns an answer, citations, and `abstained`. Citations are retrieved `DOC-` ids only.

## What we measure (retrieval vs answers)

Retrieval: Recall@5 / @10 / @20, MRR, nDCG.  
Answers: citation grounding (cited ⊆ retrieved), abstention on empty/negative/denied. Prose correctness is scored separately from retrieval.

If the gold document is not retrieved, the answer metric is not a model problem.
