# Aggressive legal regression + platform comparison (2026-10-04)

Generator for agent arms: `zai.glm-5`. Judge (where used): `deepseek.v3.2`.  
Artifacts in this folder + `evals/grounding/last_aggressive_2026-10-04.json`.  
Research-agent arms ran from branch/worktree `research-authority-layer` (authority tools). Ask/grounding/km_live hit the live API on `fixes-portals` + shared DB.

---

## 1. What we ran (aggressive suite)

| # | Benchmark | n | Surface | Metric |
|---|---|---|---|---|
| A | Harbour retrieval | 307 | engine in-process | R@10 / MRR / nDCG |
| B | Apex `dataset.jsonl` retrieval | 445 | engine (wrong corpus) | R@10 — **diagnostic only** |
| C | Ask the Firm KM live | 109 | `POST /api/answers` | category pass rate |
| D | Grounding gold | 41×2 | Ask + Assistant | citation precision, fact recall |
| E | LRB-style research (arXiv:2610.00609 method) | 24×3 arms | none / firm-tools / authority-tools | all-pass + source check |
| F | India matters (AMPIN, Vector Green, MSEDCL, Acme + statutes) | 12×2 | none vs tools | fact recall + abstain |
| G | LegalBench subset (HF `nguha/legalbench`) | 290 | parametric, no tools | accuracy |
| H | Vals public.json (5 US Q) | 5×2 | prior run | usable vs abstain (see earlier) |

**Not runnable here (gated / private):** official Vals Legal Research Bench (413 US Q), Harvey Legal Agent Benchmark (LAB), full LegalBench 162-task macro, vendor product APIs (Harvey / CoCounsel / Lexis+AI).

---

## 2. Our scores (this run)

### A. Harbour retrieval (primary retrieval bench)

| Metric | Score |
|---|---|
| R@5 | **0.929** |
| R@10 | **0.944** |
| R@20 | 0.945 |
| Hit@10 | 0.967 |
| MRR | 0.926 |
| nDCG@10 | 0.930 |

By type (R@10): argument 0.977 · document_title 0.958 · exact 0.944 · client_matter 0.710 · semantic 0.656.

### B. Apex `dataset.jsonl` (obsolete for Harbour corpus)

Overall R@10 ≈ **0.07**. Do **not** use as a product score — gold IDs do not match the loaded Harbour corpus. Harbour (A) is the retrieval gate.

### C. Ask the Firm — KM live

| | |
|---|---|
| **Pass rate** | **90.8%** (99/109) |
| p50 latency | 7.5 s |

Weak cell: `negative` 0.33 (n=3). Strong: overview / paraphrase / ethical wall / client matters ≈ 1.0.

### D. Grounding (sentence-level support)

| Surface | Cit. precision | Claim coverage | Unverified shown | Fact recall | Expect OK |
|---|---|---|---|---|---|
| **Ask** | **0.905** (lenient 1.0) | 0.914 | 0.173 | **0.784** | 6/7 |
| **Chat (cite mode)** | **0.947** (lenient 1.0) | 1.0 | 0.053 | **0.103** | 0/7 |

Chat citation hygiene is excellent; fact recall / expect_ok collapse under `cite` mode on this gold set — treat as a **regression flag** (likely over-abstention / grounding strip), not a win.

### E. LRB-style research (PCIJ + UNSC corpus) — architecture ablation

Same all-pass + source-check protocol as Legal Research Bench paper; **not** the same 413 US questions.

| Arm | All-pass (95% CI) | Weighted | Central-wrong | Fabricated cites | Tools/Q |
|---|---|---|---|---|---|
| No resources (1-shot) | **0.17** (0.07–0.36) | 0.51 | 0.67 | **14** | 0 |
| Before (firm tools only, old prompt) | **0.50** (0.31–0.69) | 0.76 | 0.42 | 2 | 5.7 |
| **Now (authority tools + research mode)** | **0.83** (0.64–0.93) | **0.98** | **0.04** | **0** | 6.2 |

Paired McNemar: now vs none 16–0 (p≈0); now vs before 9–1 (p=0.022).

### F. India matters (with vs without resources)

| Bucket | Metric | No resources | With resources |
|---|---|---|---|
| In-corpus filings (8) | Fact recall | 0.25 | **0.88** |
| Out-of-corpus statutes (4) | Correct abstain | 0.25 | **1.00** |
| Out-of-corpus | Invents statute text | 0.50 | **0.00** |

### G. LegalBench subset (parametric `zai.glm-5`)

| Task | n | Accuracy |
|---|---|---|
| hearsay | 50 | 0.62 |
| personal_jurisdiction | 50 | 0.72 |
| diversity_1 | 50 | 0.76 |
| overruling | 50 | 0.96 |
| proa | 50 | 0.98 |
| successor_liability | 40 | 0.05 |
| **Macro (6 tasks)** | 290 | **0.682** |
| **Binary-only macro (ex. successor)** | 250 | **0.808** |

Successor is multi-label theory listing — prompt/scoring mismatch dominates that cell.

---

## 3. Published external scores (for comparison — different harnesses)

### Legal Research Bench (Vals, 413 US Q, web + CourtListener) — all-pass

| System / model | All-pass | Source |
|---|---|---|
| Claude Opus 5 / Muse Spark 1.3 Max / Claude Fable 5.1 | **~55.3%** | [Vals LRB](https://www.vals.ai/benchmarks/legal_research) / BenchLM |
| Gemini 4 Argon | ~54.8% | same |
| GPT-5.6 Sol / Claude Sonnet 5.5 | ~48.1% | same |
| Claude Opus 4.8 (paper snapshot) | 42.9% | arXiv:2610.00609 |
| GPT-5.5 (paper) | 40.0% | same |
| Claude Sonnet 4.6 (paper) | 38.5% | same |
| **Our LRB-style “now” (24 Q, firm corpus)** | **83%** | this run — **not comparable difficulty** |
| **Our LRB-style “none”** | **17%** | this run |

Paper finding we reproduce: tools vs 1-shot is a large lift; effort (tool count) alone does not explain accuracy.

### Harvey Legal Agent Benchmark (LAB) — all-pass (private)

| Model (Vals / vendor posts) | All-pass |
|---|---|
| Muse Spark 1.1 | ~20% |
| Grok 4.7 / Gemini 4 Argon | ~19.6% |
| Claude Fable 5 | ~11–11.3% |
| Claude Opus 4.8 | ~9.6–10.4% |
| Claude Opus 5 (Vals) | ~6.7% (Harvey internal held-out: 11.7%) |
| GPT-5.5 | ~3.8% |

We have **no LAB score** — different product shape (Word/Excel/shell agent tasks).

### LegalBench (classification) — published macros

| Model | Approx. macro |
|---|---|
| Claude Fable 5 (Vals LB) | ~88.6% |
| Claude Opus 5 | ~87% |
| GPT-4o (2024-11) | ~82% |
| GPT-4 (original paper) | 77.0% |
| **Our generator subset (binary)** | **~80.8%** |
| **Our generator subset (incl. successor)** | **~68.2%** |

Subset ≠ full 162-task suite.

### Third-party “platform” board (HAQQ 2026, /50) — proprietary harness

| Platform | Score /50 |
|---|---|
| HAQQ | 47.5 |
| Claude Fable 5 (raw) | 44.0 |
| Harvey | 38.2 |
| CoCounsel | 36.2 |
| Legora | 34.5 |
| LexisNexis +AI | 33.2 |
| ChatGPT 5.5 | 34.4 |

Treat as directional marketing benchmark, not a shared open harness.

---

## 4. Architecture comparison (honest)

| Capability | Generic frontier chat (no tools) | Firm RAG only (“before”) | **Our research assistant (“now”)** | Vals LRB harness (Opus-class) | Harvey / CoCounsel product |
|---|---|---|---|---|---|
| Matter-scoped firm facts | Weak / invents | Strong if retrieved | Strong + authority pin | N/A (open web law) | Strong on uploaded docs |
| Citation fabrication (our LRB-style) | High (14/24) | Low (2) | **Zero** | Source-URL checked | Product-dependent |
| All-pass on *our* corpus research | 17% | 50% | **83%** | — | — |
| All-pass on *US open-web* LRB | ~same as model 1-shot ≪ tools | N/A | **Not evaluated** (no web/CL) | **~43–55%** SOTA | Not public on LRB |
| Abstain when statute absent | Poor | Better | **Best** | Searches web instead | Mixed |
| LegalBench-style classification | Competitive mid-tier | N/A | Same model | N/A | N/A |
| Multi-app agent LAB | N/A | N/A | N/A | N/A | Hard (SOTA ~20%) |

**Where we win today:** grounded firm research + India filings in the DMS — large, statistically significant lift from authority tools; Ask KM live ~91%; Harbour R@10 ~94%; Ask grounding cit. precision ~0.91.

**Where we are not on the board yet:** official US Legal Research Bench (needs web + CourtListener + 413 attorney rubrics); Harvey LAB (document-assembly agent); full LegalBench 162; head-to-head API runs against Harvey/CoCounsel/Lexis.

**Chat grounding fact_recall 0.10** is the loudest internal regression vs Ask (0.78) — fix before claiming Assistant parity with Ask on gold facts.

---

## 5. How to quote these numbers

Safe:

- “On a 24-question Legal Research Bench–*style* all-pass eval over our PCIJ/UNSC corpus, authority tools raised all-pass from 17% (no tools) to 83%, with zero fabricated citations (McNemar p&lt;0.001 vs none).”
- “Ask the Firm passes 90.8% of 109 live KM gold checks; Harbour retrieval R@10 = 0.94.”
- “On India in-corpus filings, fact recall 0.25 → 0.88 with tools; on missing statutes, invent rate 0.50 → 0.00.”

Unsafe without caveats:

- “We beat Claude Opus 5 on Legal Research Bench” — **false**; different test set.
- “We beat Harvey” — **no shared LAB/LRB score**.

---

## 6. Next aggressive steps

1. Fix Assistant `cite` mode fact_recall / expect_ok on grounding gold.  
2. Wire CourtListener + web (or India primary sources) and re-run Vals `public.json` + a licensed LRB slice.  
3. Expand LRB-style set to ≥50 attorney-reviewed questions.  
4. Re-run interrupted 38-Q India aggressive suite after API stability.  
5. LegalBench: full IRAC slice with official prompts; drop/fix successor multi-label scorer.  
6. Optional: apply for Vals LRB access for true leaderboard numbers.
