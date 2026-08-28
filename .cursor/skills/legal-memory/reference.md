# Legal memory — reference

## Layout

- Frozen corpus: `dummy-firm/data/`
- App: `legal-memory-retrieval/`
- Gold questions: `legal-memory-retrieval/evals/dataset.jsonl` (~445)
- North star: `legal-memory-retrieval/docs/NORTH_STAR.md`
- Changelog: `legal-memory-retrieval/docs/CHANGELOG.md`

## Ports

- Postgres+pgvector: `localhost:55432` user/pass/db `legal` / `legal` / `legal_memory`
- Redis: `localhost:6380` (unused until Sprint 9)
- API: `uvicorn app.api.main:app --reload --port 8000`

## Commands (from `legal-memory-retrieval/`)

```bash
docker compose up -d
python scripts/ingest.py          # full reload; drops tables
python scripts/embed.py           # MiniLM backfill; idempotent
python evals/build_eval.py
RETRIEVAL_CHANNELS=keyword,metadata python evals/retrieval_eval.py
RETRIEVAL_CHANNELS=vector python evals/retrieval_eval.py
RETRIEVAL_CHANNELS=keyword,metadata,vector python evals/retrieval_eval.py
```

## Schema (high level)

`members`, `clients`, `matters`, `matter_members`, `permissions`, `documents`, `chunks` (tsv + `embedding vector(384)`), `relationships`, `arguments`.

ACL: join `permissions`; allow if not restricted or `member_id = ANY(allowed_members)`.

## Eval types

`exact`, `matter_retrieval`, `similar_matter`, `semantic`, `person_expertise`, `multi_hop`, `cross_document`, `versioning`, `graph_reasoning`, `argument_retrieval`, `negative`, `permission`.

Retrieval metrics: Recall@5/10/20, MRR, nDCG@10. Permission DENIED = leak if restricted matter appears. Negative = fail if any doc returned (lexical/vector noise).

## Lexical baseline (Sprint 2)

n=445, channels keyword+metadata: Recall@10 **0.4073**, MRR **0.3593**.

## Vector-only (Sprint 3)

n=445, MiniLM 384-d, 41788 chunks: Recall@10 **0.2638**, MRR **0.3096**. Did not beat lexical.

## Hybrid (Sprint 4, default channels)

n=445, keyword+metadata+vector with routing/thresholds: Recall@10 **0.4343**, Hit@10 **0.7076**, MRR **0.3853**. Negatives 1.0.

## Rerank (Sprint 5, default)

n=445, fused 100 + `ms-marco-MiniLM-L-6-v2`, skip CE on `MTR-` ids: Recall@10 **0.4723**, Recall@20 **0.6140**, Hit@10 **0.8059**, MRR **0.4882**, nDCG@10 **0.4105**. Permission and negatives 1.0.

## Query understanding (Sprint 6, default)

n=445, intent/entity parse + title/client rewrite: Recall@10 **0.5391**, Recall@20 **0.6245**, MRR **0.6082**, nDCG@10 **0.4972**. exact **0.6682**, matter_retrieval **0.3008**, person_expertise **0.1714**. Permission and negatives 1.0. cross_document Recall@10 0.02 (known regression).

## SQL graph (Sprint 7, default)

n=445, channels keyword+metadata+vector+graph: Recall@10 **0.5539**, Hit@10 **0.8329**, MRR **0.6263**. graph_reasoning Recall@10 **0.4223**.

## Cross-document restore + answers (Sprint 8)

n=445: Recall@10 **0.5889**, Hit@10 **0.9189**, MRR **0.6930**. cross_document Recall@10 **0.4826**. `POST /ask` + `python evals/answer_eval.py`.
