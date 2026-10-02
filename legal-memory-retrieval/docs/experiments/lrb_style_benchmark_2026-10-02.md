# Legal Research Bench-style benchmark of the Assistant (2026-10-02)

Source: *Legal Research Bench: Measuring End-to-End Reliability in Long-Horizon Legal Research Agents*
(Drozdov, Chen, Nashold, Krishnan; Vals AI; COLM 2026 workshop; arXiv:2610.00609). The paper benchmarks
13 frontier models on 413 U.S. questions. Its best model is fully correct on 42.9% under **all-pass** grading.
Harness: `evals/research/lrb_bench.py`. Questions: `evals/research/bench_questions.py`.
Results: `results_bench_summary.json`, `results_bench_r1_local.json` (no-tools arm),
`results_bench_r1_local_tools.json` (before and now arms).

## What was taken from the paper

| Paper | Here |
|---|---|
| All-pass: correct only if every rubric item passes | same |
| Source check: an invalid cited URL fails the response | every PCIJ/UNSC citation must resolve and its page or paragraph must exist (`verify_citations`) |
| Rubric items weighted +1/+2/+3, a +3 carries the central conclusion | same; "central-wrong" = a +3 item missed |
| Reconciliation and temporal-validity difficulty marks | same marks on 3 and 5 questions |
| Ablation: tools vs single-shot (22.5 points) | three arms: no tools, the assistant before this branch, the assistant now |
| Judge validated against attorneys before scoring | judge validated against gold and reversed answers (see limits) |
| Statistical care (clustered CIs, McNemar) | Wilson 95% CIs and exact McNemar on paired questions |

## Setup

- 24 questions, 6 scenarios: doctrinal (8, PCIJ), statutory (4, UN Security Council), temporal (5, "answer as of
  2 October 2026" and one past date), reconciliation (1; 3 incl. attribute overlaps), abstention (2: Indian law, ICJ),
  false premise (3: a wrong holding, a non-existent resolution, a wrong year) and cite-check (1 draft with 5 planted
  issues). 81 rubric items. Gold answers checked against the corpus text.
- Same generator in every arm (`zai.glm-5`); judge `deepseek.v3.2` (not the generator, not the in-product verifier).
- Arms: **none** one model call with no tools; **before** the assistant at `bf4eb59` (firm tools only, old prompt,
  kept in `evals/research/baseline_system_prompt_bf4eb59.py`); **now** authority tools, research method, dated prompt.
  Arms `before` and `now` run the real `run_chat_agent` in research mode, with grounding.
- **Judge validation:** on all 24 questions the judge accepted 24/24 gold answers and rejected 24/24 answers the
  generator wrote to reach the opposite conclusion (`results_bench_calibration.json`). One validation run first
  rejected 3 gold answers; the judge was right, my gold text omitted a rubric point, and the gold was fixed.

## Results

| Arm | All-pass (95% CI) | Weighted pass | Central-wrong | Source-check failures | Invalid citations | s / question | Tool calls |
|---|---|---|---|---|---|---|---|
| none | 0.21 (0.09–0.41) | 0.56 | 0.62 | 4 | 10 | 16 | 0 |
| before | 0.38 (0.21–0.57) | 0.75 | 0.46 | 1 | 1 | 42 | 7.3 |
| **now** | **0.71 (0.51–0.85)** | **0.94** | **0.08** | **0** | **0** | 58 | 7.2 |

Paired, per question (exact McNemar): now vs before **9 vs 1, p = 0.022**; now vs none 12 vs 0, p = 0.0005;
before vs none 7 vs 3, p = 0.34 (not significant: firm tools alone did not help).

By scenario, all-pass (none / before / now):

| Scenario | n | none | before | now |
|---|---|---|---|---|
| doctrinal | 8 | 0.00 | 0.00 | **0.62** |
| statutory | 4 | 0.50 | 0.75 | 0.75 |
| temporal | 5 | 0.00 | 0.80 | 0.60 |
| reconciliation (mark, n=3) | 3 | 0.00 | 0.67 | 0.33 |
| abstention | 2 | 0.00 | 1.00 | 1.00 |
| false premise | 3 | 0.67 | 0.00 | 1.00 |
| cite-check | 1 | 1.00 | 0.00 | 1.00 |

Compared with the paper: the paper's best model is 42.9% on U.S. questions with web and case-law search. These
numbers are not comparable in difficulty (24 questions on a corpus we hold, written by us, against 413 attorney
questions on open U.S. law). They show direction and size of effect, not a leaderboard position.

### What this says

1. **Authority tools are what moved it.** Without tools the model fabricated 10 citations in 4 answers and missed
   every doctrinal and temporal question; the old firm-tools assistant did not beat it significantly. Doctrinal
   went 0/8 → 5/8.
2. **No fabricated or invalid citation in any of the 24 answers** from the new assistant (the paper's source check),
   against 1 for the old assistant and 10 for no tools.
3. **Central errors fell from 46% to 8%.** The paper's central-wrong share for its best models is 22%.
4. **Temporal got slightly worse (0.80 → 0.60)** on a small n=5: T01 omitted the earlier extension (+1) and T03 gave
   both dates correctly but printed the resolution numbers only as citation chips (below).
5. **More tools or turns are not the point** (tool calls are flat at 7.2 vs 7.3); the paper's finding that effort
   does not predict accuracy holds here too. The new assistant is 38% slower (58 s vs 42 s).

### What still fails in `now` (7 of 24)

| Q | Miss | Weight | Kind |
|---|---|---|---|
| D02, D05 | does not say the PCIJ decision is non-binding precedent | +1 | lower-tier |
| D04 | does not state the consequence (must refrain from contesting) | +1 | lower-tier |
| S02 | omits the 15 January 1991 deadline condition | +2 | lower-tier |
| T01 | omits the earlier extension in resolution 2786 | +1 | lower-tier |
| T03 | correct dates, but resolution numbers appear only in citation chips, not prose | +3 (cite) | scorer limit |
| R01 | cites *Customs Regime* instead of *Wimbledon* for "treaties are an attribute of sovereignty" | +3 | **real miss** (retrieval) |

Five of seven are lower-tier omissions. R01 is the one substantive failure and it is a reconciliation question,
which is also where the paper finds agents weakest.

## Limits (read before quoting any number)

- **24 questions.** The "now" interval is 0.51–0.85. Per-scenario cells have n = 1 to 8 and are indicative only.
- **Questions and rubrics were written by the engineers, not by practising attorneys**, and gold answers rest on
  the corpus text plus established holdings. The paper's judge was validated against attorneys (kappa 0.71); this
  judge was validated against gold and deliberately reversed answers, which tests that it separates right from
  wrong, not that it agrees with lawyers on hard calls.
- **Citation-form strictness.** "Cites X" requires a parseable citation key in the answer prose. The old assistant
  often named the right case without a parseable citation (Lotus as "Judgment — Lotus (1927)"). Counting failures
  that are *only* missing citation form as passes gives lenient all-pass of none 0.33, before 0.58, now 0.75; the
  ranking and the size of the lift do not change.
- **The scorer reads prose only.** Citation chips (`[1]`) are not parsed, which cost `now` one question (T03).
- One run per question per arm; the paper also reports single runs. Two provider errors (malformed tool-call JSON
  from the generator, HTTP 400) occurred and were retried; no question ended in an error.
- Scope is PCIJ and UN Security Council only. The Indian-law scenarios test abstention, not Indian research.
- The `none` arm has no tools, so its "citations" are checked only where they match a held collection.

## Next

1. R01-type misses: retrieval for a principle stated in a case the question does not name (*Wimbledon*).
2. Parse citation chips in the scorer; add 20+ questions across scenarios, ideally reviewed by a lawyer.
3. The 38% latency increase: authority search p50 is 2.9 s and research-mode answers take 30–110 s.
4. Provider robustness: the generator sometimes emits invalid tool-call JSON and the provider then returns 400
   (3 occurrences in this session). The agent should repair or drop the malformed call instead of failing the turn.
