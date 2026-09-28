# Plan 14 — External benchmarks and answer latency

Started 2026-09-27. Status keys: `[ ]` open · `[~]` in progress · `[x]` done (with date + eval evidence)

## Why

1. **Our own benchmarks are saturated.** Harbour retrieval R@10 0.97 (several types 1.000); the 445-question
   gate sits at R@10 0.76. Near-ceiling scores cannot show whether a change helps.
2. **Answer latency is far from the north star (~2 s).** Retrieval p50 is 20–55 ms, but Ask the Firm p50 is
   17.9 s and the Assistant 37.7 s (`docs/experiments/grounding_2026-09-27.md`). Grounding alone adds 8–18 s.

## Baseline (2026-09-27)

| Area | Now | Target |
|---|---|---|
| Retrieval gate (445 Q) | R@10 0.76, MRR 0.86 | no regression; improve on external sets |
| Shown-as-supported precision | Ask 0.949, Assistant 0.968 | ≥ 0.97 both |
| Fact recall | Ask 0.80, Assistant 0.99 | Ask ≥ 0.90 |
| Answer p50 | Ask 17.9 s, Assistant 37.7 s | Ask ≤ 6 s (first verified sentence < 2 s), Assistant ≤ 15 s |
| Grounding gold set | 41 Q | 150+ Q |
| External benchmarks | none | 3 running nightly |

## Phase A — benchmark ladder

Each benchmark answers a different question; no blended "legal AI score". Every dataset licence goes in
`docs/legal/DEPENDENCY_AUDIT.md` before download. Benchmark corpora load as a separate ACL-scoped collection,
never into the firm corpus. Tune on dev splits only.

- [ ] A1 Harbour-LAB: grounding gold 41 → 150+ (multi-matter, long PDFs, tables), then ~50 agent tasks with
      atomic rubrics (found doc X, cited §Y, correct conclusion). Metrics: criteria pass, all-pass, coverage.
- [~] A2 LegalBench-RAG (CUAD, MAUD, ContractNLI, PrivacyQA; 6,858 Q): span precision/recall @k per sub-corpus.
      Harness built: `evals/legalbench_rag_prepare.py` (converts to our corpus format, loads a *separate*
      `legalbench_rag` DB + Redis db 9; refuses the firm DB because `scripts/ingest.py` drops tables) and
      `evals/legalbench_rag_eval.py`. **Blocked on licence approval** (`docs/legal/DEPENDENCY_AUDIT.md`).
- [ ] A3 CUAD / ContractNLI through `app/review/tabular_service.py`: per-clause F1, entailment accuracy.
- [ ] A4 Harvey LAB (MIT): adapter exposing `search_firm_records`, `read_document`, `find_in_document` to its
      harness; ~50 tasks first. All-pass, criteria pass, cost and time per task.
- [ ] A5 LegalBench / LEXam: model selection only (they mostly measure the base model).

## Phase B — quality

- [ ] B1 Embedding ablation (MiniLM-384 vs 1–2 stronger models) gated on A2 + `evals/gate.py`;
      re-chunk legacy 36k fixed-window chunks with section/page metadata.
- [ ] B2 Coverage-driven agent loop: planner emits an expected-evidence checklist; search until covered or
      budget spent; log coverage per run. Map-reduce over document sets via tabular extraction → synthesis.
      Version-aware clause resolution (plan 13).
- [ ] B3 Validate → revise: send failed/partial claims back for one targeted revision with fresh retrieval,
      instead of only deleting them (Ask fact recall 0.80).
- [ ] B4 Long-form: outline → per-section evidence → parallel section drafts → per-section verify → consistency.

## Phase C — latency

- [x] C0 Per-stage timings on both answer paths (retrieval, TTFT, generation, verifier calls, absence check,
      tools) reported by `evals/grounding_eval.py` as p50/p95.
- [ ] C1 Stream-verify: verify sentences/paragraphs as they are generated; show verified text progressively.
- [ ] C2 Local entailment pre-filter (cross-encoder / NLI) auto-passes high-confidence units; only uncertain
      units go to the LLM verifier. Calibrate against the judge first.
- [ ] C3 Smaller candidate pools per unit + verdict cache keyed on (unit hash, span hash).
- [x] C4 Parallel verification: key finding ‖ body on Ask; verifier batch sharded (`GROUNDING_VERIFY_BATCH`, default 6).
      2026-09-27 A/B (41 Q, live HTTP): Ask p50 17.9 → 8.4 s (batch 0) / 8.9 s (batch 6), precision 0.884 → 0.894 / 0.914
      (noise ±2–3); sharding negligible at p50 (median 4 units), trims Assistant verify p95 15.7 → 11.9 s.
- [ ] C5 Parallel tool calls in the Assistant when a round requests several (measure rounds with >1 call first).
- [ ] C6 Retrieval tails: BM25 p95 ~1.6 s, rerank p95 up to 10 s → query plans, candidate caps, warm-up.
- [ ] C7 Adaptive compute: fast path for exact / single-document questions; deep mode as a background job.
- [ ] C8 Model routing experiments (faster Ask generator; Claude on Bedrock once access is granted).

## Phase D — make it permanent

- [ ] CI: retrieval gate, grounding smoke subset (~20 Q), latency budgets as failing gates.
- [ ] Nightly: A2, A3, A4 subset; results per model / retriever / prompt version.
- [ ] Every agent run traced to JSON (tool calls, docs read, coverage, verdicts) → `evals/exact_failure_taxonomy.py`.

## Not doing (until a measurement justifies it)

Temporal, Kafka, OpenSearch, Neo4j, microservices, training a legal model (see `docs/NORTH_STAR.md`).

## Log

- 2026-09-27 — plan written; C0 + C4 done (see C4). Assistant p50 24.8–25.5 s: agent LLM ~9–11 s + tools ~9–10 s +
  grounding ~4 s; multi-tool rounds rare (C5 low value). One Assistant request hung ~68 min in the batch-0 arm —
  investigate (no timeout on the sync chat path?). Next: A1 gold set growth; A2 awaiting licence approval.
