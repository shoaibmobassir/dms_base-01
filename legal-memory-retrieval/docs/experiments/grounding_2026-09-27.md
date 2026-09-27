# Grounding experiments — 2026-09-27

Question: does every sentence a lawyer sees rest on source text that supports it?
Harness: `evals/grounding_eval.py` over the live HTTP API (`/api/answers`, `/api/chat/sessions/{id}/ask`
in the UI's default *cite* mode). Gold set: `evals/grounding/gold.jsonl` (41 questions: facts, compound
claims, cross-document, summaries, false premise, negatives, public-law questions the corpus cannot answer).
Raw results: `evals/grounding/*.json`.

## How it is measured

Each answer is split into sentences. Each sentence is paired with **the evidence the lawyer is shown for it**
(Assistant: the quotes behind its `[n]`; Ask the Firm before this work: the chunk each `(DOC-…)` chip opens;
after: the verified spans behind `[n]`, plus matter-record text for `(MTR-…)`). An independent judge model
(`deepseek.v3.2`, never the generator or the in-product verifier) labels each sentence
claim / non-claim and supported / partial / unsupported.

| Metric | Meaning |
|---|---|
| strict precision | cited claims whose evidence entails every element / cited claims |
| **shown-as-supported precision** | of the sentences the product presents with a normal (unflagged) citation, the share the judge agrees are supported. This is the number a lawyer relies on. |
| flagged partial | sentences shown with a dashed "partly supported" citation |
| unverified shown | claims shown without supporting evidence (uncited, unsupported or partial) / claims |
| parametric | statements of law with no supporting source |
| fact recall | gold facts present in the answer |

**Judge calibration.** 24 random baseline verdicts were labelled by hand: 23/24 agreement (96%). The one
disagreement was the judge being lenient (it accepted an inferential add-on). Measured precision is therefore
an upper bound by about one to two points. With 100–190 claims per surface per run, run-to-run noise is about
±2–3 points.

## Results

| Run | Surface | strict prec. | shown-as-supported | flagged partial | unverified shown | parametric | fact recall | p50 latency |
|---|---|---|---|---|---|---|---|---|
| baseline | Ask the Firm | 0.629 | — | — | 47.6% | 2 | 0.809 | 4.6 s |
| baseline | Assistant | 0.806 | — | — | 55.4% | 15 | 0.931 | 17.0 s |
| v1 sentence verifier | Ask the Firm | 0.892 | 0.953 | 16 | 11.9% | 1 | 0.779 | 12.9 s |
| v1 sentence verifier | Assistant | 0.926 | 0.965 | 19 | 11.7% | 0 | 0.912 | 31.8 s |
| v2 + element decomposition | Ask the Firm | 0.887 | 0.950 | 33 | 16.1% | 1 | 0.794 | 14.1 s |
| v2 + element decomposition | Assistant | 0.966 | **0.980** | 28 | 9.1% | 0 | 0.975 | 35.7 s |
| v3 + absence check, guards | Ask the Firm | 0.875 | 0.923 | 25 | 17.9% | 1 | 0.809 | 16.6 s |
| v3 + absence check, guards | Assistant | 0.944 | 0.975 | 21 | 10.6% | 0 | 0.975 | 35.8 s |
| v4 + consensus (Kimi AND GLM-5) | Ask the Firm | 0.877 | 0.958 | 49 | 16.0% | 0 | 0.794 | 18.9 s |
| v4 + consensus (Kimi AND GLM-5) | Assistant | 0.933 | 0.975 | 37 | 11.7% | 0 | 0.990 | 48.3 s |
| **v5 deployed** (v3 + pointer lists, no consensus) | Ask the Firm | 0.884 | **0.949** | 27 | 14.9% | 1* | 0.804 | 17.9 s |
| **v5 deployed** (v3 + pointer lists, no consensus) | Assistant | 0.952 | **0.968** | 35 | 13.0% | 0 | 0.990 | 37.7 s |

\* a flagged (partial) paraphrase of Regulation 5.11 as quoted in the CTUIL reply, not a memory-sourced statement.

**Consensus decision (v4):** +3.5 points shown-as-supported on Ask the Firm, none on the Assistant, twice the
flagged sentences and +12 s Assistant latency. The Ask gain is barely above run-to-run noise, so consensus
ships **off** (`GROUNDING_CONSENSUS_MODELS` empty) and is re-tested on the larger gold set.

### What each step changed

- **v1 — sentence-level verifier.** Kimi K2.5 picks, per sentence, the candidate spans that entail it;
  unsupported sentences are removed; `[n]` rebuilt with exact offsets. The Board Resolution case now cites both
  the meeting sentence (date) and the `RESOLVED THAT` paragraph (approval). The Assistant's 15 memory-sourced
  legal statements (CERC "PoC charges") dropped to 0.
- **v2 — element decomposition.** The verifier must map every element (actor+action, date, amount, list item)
  to a candidate; code refuses "supported" when any element is unmapped, and rejects heading-only support.
  Stricter: more sentences are flagged partial instead of passed.
- **v3 — absence check and label guards.** "The records do not contain X" is re-checked against the *full*
  documents (not just retrieved passages): a live answer claimed the Disclosure Schedule had no employee
  disclosure when it has one (Warranty 3.15). Labels that skip verification ("absence", "non_claim") are only
  accepted with a negation / suggestion cue — Kimi once labelled the false PoC claim "absence".

### Residual failure modes (v3)

1. **Semantic mis-mapping** — e.g. "LOA for 199.5 MW" (true: 199 MW) mapped to a sentence about a 199.5 MW
   *margin*; the figure guard passes because the number appears. Tested remedy: v4 consensus.
2. **Record-only claims on Ask the Firm** — sentences resting on the matter record text are weaker than
   document-cited ones; the record header line is sometimes chosen as support.
3. **Absence statements are counted as unsupported by the judge** although they are correct and deliberately
   uncited; this depresses Ask's "unverified shown" (roughly 5–7 points).
4. **Generator failures** (not grounding): GLM-5 occasionally emits a malformed tool call (Bedrock 400
   "Unterminated string") or Bedrock returns 502 twice → empty answer. One retry for the 400 case added.

### Latency

Grounding adds one verifier call per answer (plus one for absence statements): +8–12 s on Ask the Firm and
+15–18 s on the Assistant at p50. The Assistant's final text is now held until verified (narration and step
timeline still stream). Reducing this is on the roadmap (smaller candidate pools, caching per document,
parallel key-finding/body verification on Ask).

## Models available on this Bedrock account (probed 2026-09-27)

| Model | Chat completions | Notes |
|---|---|---|
| zai.glm-5 | yes | generator today |
| moonshotai.kimi-k2.5 | yes | verifier (fastest of the three in tests, same labels as the others on the probe set) |
| deepseek.v3.2 | yes | eval judge |
| openai.gpt-5.6-luna / gpt-6-luna | no | 401 not entitled |
| anthropic.claude-* | no | 403 permission; needs model access in the Bedrock console and the Messages API route |
