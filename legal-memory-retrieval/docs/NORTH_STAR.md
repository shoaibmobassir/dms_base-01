# North star — Ask the Firm

Given tens of thousands of documents belonging to hundreds of matters, the system must **reliably identify the correct institutional knowledge**, understand relationships, **respect permissions**, provide evidence-backed answers, and do so in about **two seconds**.

This is not “can the LLM answer questions about these PDFs?”

## Frozen world

Apex Chambers lives in `dummy-firm/data/` (v2): 100 members, 500 clients, 1,000 matters, 38,232 documents. Relationships, versions, permissions, and gold questions are part of that world. Ingestion of **new** dummy documents is frozen. Load into Postgres; do not regenerate to chase scores.

## How we know we improved

Every change is scored on `evals/dataset.jsonl`:

- Retrieval: Recall@5/10/20, MRR, nDCG
- Answers (Sprint 8+): correctness, faithfulness, citation precision/recall, abstention

If the gold document is not retrieved, the answer metric is not a model problem.

ACL is applied **before** ranking. Restricted chunks must never enter the candidate set.

## Sprint gates

| Sprint | What | Ship only if |
|---|---|---|
| 2 | Postgres, FTS, metadata, eval, ACL | Done. Lexical Recall@10 0.41 |
| 3 | MiniLM + pgvector | Infra done. Vector-only Recall@10 0.26 **did not** beat 0.41. See CHANGELOG. |
| 4 | Hybrid RRF + routing | Done. Recall@10 0.43 > vector 0.26 and lexical 0.41. See CHANGELOG. |
| 5 | Cross-encoder rerank 100→k | Done. Recall@10 0.47, MRR 0.49, nDCG 0.41. See CHANGELOG. |
| 6 | Query understanding | Done. Recall@10 0.54, exact 0.67. See CHANGELOG. |
| 7 | SQL graph | Done. graph_reasoning 0.42 |
| 7b | Restore cross_document | Done. Rec@10 0.59, cross_document 0.48 |
| 8 | Answers + citations + abstain | Done. `POST /ask`; citations ⊆ retrieved |
| 9–12 | Cache, traces, CI eval, hardening | After 8’s inputs are stable |

## Not yet

Kafka, Kubernetes, Neo4j, OpenSearch, agents, 15 microservices. Add them when measurements justify them.

Embeddings stay behind `app/embeddings` (locked: `all-MiniLM-L6-v2`, 384-d) so a later swap does not rewrite retrieval.
