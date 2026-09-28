# Long-document editing — experiments and decision (2026-09-28)

Question: how should the Assistant make changes to a document of hundreds of pages without losing context, and
return them to the lawyer as tracked changes in their own Word file? Plan 15 Part D. Decided by experiment,
not by design review.

## Benchmark (D1)

`evals/long_doc/generate.py` builds formatted Master Services Agreements of ~100, ~200 and ~400 pages from a seed
(numbered clauses, bold defined terms, italics, a fee table, four schedules), plus the paged text the Assistant
reads. Six tasks per document, each with an exact gold result (the whole paragraph list after the edit):

| Task | What it tests |
|---|---|
| rename_term | "Supplier" → "Vendor" everywhere (≈760 / 1,500 / 3,000 paragraphs), but not the proper name "Suppliers' Forum" |
| amend_clause | one wording change in one named clause |
| insert_after | a new clause after a named clause |
| delete_schedule | delete Schedule 3 (its body never repeats its title) |
| semantic_payment | payment periods 30 → 45 days, written several ways, next to notice / cure / retention periods and a fee table that must NOT change |
| crossref_update | references to Clause 9 → 10, next to references to Clause 19 and 29 |

Scoring (`evals/long_doc_edit_eval.py`): paragraph-level diff original → gold vs original → result.
Recall, precision, **unintended changes** (must be 0), exact match; plus model calls, largest prompt, wall time.
Model for every architecture: `zai.glm-5` on Bedrock. Unit tests: `tests/test_long_doc_eval.py`.

Gold ambiguity found and removed before scoring: filler text referred to "this clause 9.3", which made
"update references to Clause 9" ambiguous; numbered self-references were dropped from the generator.

## Architectures (D2)

| Architecture | How it works |
|---|---|
| baseline | today's design: read the document (as much as fits, ≤ 360k chars) and return ≤ 20 quote-anchored edits, first match wins |
| navigate | the production Assistant agent with the new outline / section / find tools and `propose_edits` |
| mapreduce | planner sees the OUTLINE only → search terms → candidate paragraphs → parallel section editors return whole-paragraph rewrites |
| hybrid | mapreduce + literal substitutions applied by code |
| v2 | span edits (old → new inside a paragraph, applied by code), planner may name whole sections, every code substitution verified by the model |
| v3 | v2 + editor edits verified too |
| v4 | v3 + case-sensitive substitutions for capitalised terms, verifier in batches of 10 with a decision and reason per paragraph, CONTEXT paragraphs read-only for editors, one retry on provider 5xx |
| v5 | v4 + the verifier sees only the exact word-level CHANGES (`[-old-]{+new+}`) and the paragraph's first words; clause-scoped substitutions; defined-term casing; unique span anchors with one re-ask |
| **v6 = production** | v5, but the verifier again sees BEFORE and AFTER in full (plus the CHANGES); substitutions never alter a paragraph's own clause number; lower-case-only paragraphs are not editor candidates for a capitalised term; "global" words inside quotes ignored; an ambiguous "add at the end" anchors to the occurrence that ends the paragraph — `app/editing/engine.py` |

## Results — 18 tasks per run (6 tasks × 100/200/400 pages)

| Run | Architecture | Exact | Recall | Precision | Unintended | Errors | Median s | Largest prompt |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| seed 1 | baseline (today) | 2/18 | 0.262 | 0.661 | 4 | 0 | 12.3 | 360,843 |
| seed 1 | navigate (today's agent + B1 tools) | 3/18 | 0.222 | 0.431 | 2 | 0 | 25.4 | 193,823 |
| seed 1 | mapreduce | 9/18 | 0.736 | 0.884 | 46 | 2 | 6.0 | 35,884 |
| seed 1 | hybrid | 9/18 | 0.803 | 0.896 | 50 | 1 | 7.8 | 30,860 |
| seed 1 | mapreduce v2 | 11/18 | 0.817 | 0.885 | 136 | 1 | 9.3 | 31,483 |
| seed 1 | hybrid v2 | 12–13/18 | 0.93 | 0.94 | 4–9 | 0 | 8.8 | 37,662 |
| seed 1 | hybrid v3 | 12/18 | 0.875 | 0.885 | 6 | 1 | 14.1 | 38,418 |
| seed 1 | hybrid v4 | **18/18** | **1.0** | **1.0** | **0** | 0 | 13.1 | 27,183 |
| seed 2 | hybrid v2 | 11/18 | 0.875 | 0.883 | 525 | 1 | 11.3 | 42,309 |
| seed 2 | hybrid v3 | 16/18 | 0.889 | 0.889 | 0 | 2 | 15.1 | 39,920 |
| seed 2 | hybrid v4 | 16/18 | 0.996 | 0.965 | 21 | 0 | 13.1 | 42,313 |
| seed 3 (holdout for v4) | hybrid v2 | 11/18 | 0.944 | 0.883 | 248 | 0 | 9.6 | 40,780 |
| seed 3 (holdout for v4) | **hybrid v4** | **18/18** | **1.0** | **1.0** | **0** | 0 | 11.9 | 40,636 |
| seed 4 (holdout for v5) | v5 (first production) | 12/18 | 0.889 | 0.887 | **172** | 0 | 14.9 | 43,646 |
| seeds 1–5 | v5 (after fixes a–d) | 66/90 | 0.962 | 0.978 | 15 | 0 | 10–18 | 42,247 |
| seed 4 | hybrid v4 | 17/18 | 0.944 | 0.944 | 0 | 1 | 10.9 | 41,814 |
| seed 5 | hybrid v4 | 17/18 | 0.998 | 1.0 | 0 | 0 | 10.8 | 27,824 |
| seed 6 (holdout for v6) | hybrid v4 | 16/18 | 0.944 | 0.917 | 1 | 0 | 12.8 | 38,551 |
| seed 1 | **v6** | 16/18 | 0.971 | 1.0 | 0 | 0 | 16.1 | 31,508 |
| seed 2 | **v6** | 15/18 | 0.880 | 0.889 | 0 | 0 | 12.3 | 42,247 |
| seed 3 | **v6** | 18/18 | 1.0 | 1.0 | 0 | 0 | 14.6 | 40,570 |
| seed 4 | **v6** | 18/18 | 1.0 | 1.0 | 0 | 0 | 12.8 | 41,748 |
| seed 5 | **v6** | 17/18 | 0.997 | 1.0 | 0 | 0 | 10.4 | 27,758 |
| seed 6 (holdout for v6) | **v6** | 16/18 | 0.995 | 0.972 | 1 | 0 | 14.6 | 38,485 |
| **all 6 seeds** | **v6** | **100/108** | **0.974** | **0.977** | **1** | **0** | 10–16 | 42,247 |

Seeds 1 and 2 were inspected while designing (v4 from seed-1 failures, the production verifier change from a
seed-2 failure); seed 3 was held out for v4 and seed 4 for production.

### What failed, and what fixed it

| Failure (with the evidence row) | Fix |
|---|---|
| baseline / navigate: global changes stop at the 20-edit cap; quote edits cannot insert or delete paragraphs; a 400-page document does not fit (truncated at 360k chars); navigate turns run out of time | outline-only planning; paragraph-id operations; no cap |
| mapreduce: editors rewrite whole paragraphs and drift (45 unintended on a rename) | span edits applied by code (v2) |
| delete_schedule recall 0.33: body paragraphs do not contain "Schedule 3" | planner may name whole outline sections (v2) |
| hybrid: "30 days → 45 days" applied mechanically also changed notice / cure periods (44 unintended) | every code substitution verified (v2) |
| v2 seed 2: "reasonable → all reasonable" applied to 967 paragraphs, 520 left wrong by a verifier judging 40 before/after pairs | verifier: 10 per call, decision + reason per paragraph (v4) |
| v2/v3: "Supplier → Vendor" also changed "a leading supplier" | case-sensitive substitution for capitalised find text (v4) |
| v3: "add a sentence to 193.1" became a new paragraph after 193.2 | CONTEXT paragraphs read-only; appending is a span edit (v4) |
| provider HTTP 500 counted as a failed task | one retry (v4) |
| v4 seed 2: "9. → 10." fixed references but also turned clause numbers "99.9" into "910.9"; the verifier, shown two long near-identical paragraphs, approved | v5 tried a changes-only verifier view — **it regressed** (next rows); v6 protects a paragraph's own clause number in code |
| v5 seed 4: a one-clause amendment turned into a global substitution; the changes-only view hid which clause each change was in, so the verifier approved 164 wrong paragraphs | substitutions limited to the named clauses when the instruction is not global; full BEFORE/AFTER view restored (v6) |
| v5: the verifier rejected genuine payment clauses it could not judge from a few words of context (payment recall 0.59–0.97) | full BEFORE/AFTER view restored (v6) |
| v5: every rename also changed "a leading supplier" via an editor | paragraphs with only the lower-case word are not candidates for a capitalised term (v6) |
| v5: "within all reasonable" — the word "all" in the quoted replacement made a one-clause instruction look global | global words inside quotes ignored (v6) |
| v5: "add at the end" anchored to a sentence that occurs twice, inserting mid-clause | unique anchors; an ambiguous append goes to the occurrence ending the paragraph (v6) |

## Tracked changes in the original .docx (D3)

`app/drafting/docx_tracked.py`, checked by `evals/long_doc/docx_check.py` on every task at 100 and 400 pages with
the GOLD edits (so only the Word writing is under test): accept-all = gold, reject-all = original, every untouched
paragraph's style and run formatting unchanged, bold clause numbers kept in edited paragraphs, file reopens.
**All 12 size × task combinations pass**, including 2,966 tracked renames in a 400-page document in 2.5 s.
Unit tests: `tests/test_docx_tracked.py` (edit across a formatting boundary, paragraph with a tab replaced
whole, insert/delete paragraph marks, accept-all clean copy). Not checked: rendering in Word or LibreOffice
(neither is installed here) — open one exported file in Word before a pilot.

## Decision (D4)

Gates: edit recall ≥ 0.95, unintended = 0, formatting preserved 100 %, largest prompt within budget at 400 pages.

- **Ship v6 as `edit_document`** (`app/editing/engine.py`). Across 108 tasks on six document sets it scores 100/108
  exact, recall 0.974, precision 0.977, **1 unintended paragraph in total**, 0 errors, largest prompt 42k chars at
  400 pages (today's design: 361k chars and still could not see a 400-page document). On the held-out seed it
  beats v4 (recall 0.995 vs 0.944). Gate status: recall ≥ 0.95 **met**; unintended = 0 **met on 5 of 6 seeds**
  (one wrong paragraph in a 100-page amendment on seed 6); formatting 100 % **met** (D3); prompt budget **met**.
  The residual risk is carried by the product, not hidden: nothing is applied until the lawyer accepts it, and
  export is tracked changes they can reject in Word.
- **Weakest task: payment periods (recall 0.953 over 447 gold changes).** Misses are omissions, not wrong edits.
  Part of this gold is arguably wrong — "Payment of the Service Credits reconciliation" may be the Supplier's
  payment, and the instruction said periods "within which the Customer must pay" — but some misses are clear
  Customer payments. Next step: a second editor pass over candidates the first pass left unchanged.
- **The loop mattered:** v5, my first "production" change, looked better in design and regressed badly on a
  held-out seed (172 unintended). Only the held-out seeds caught it.
- **Keep `propose_edits`** for a few targeted wording changes in a document the Assistant has read; the prompt
  now routes document-wide changes to `edit_document`.
- **Accepted edits are written into the original Word file as tracked changes** (D3) and saved as a new
  "developing" version whose stored original is the clean accepted file, so the next edit reads matching
  paragraphs. Edits proposed on an older version are refused on export.

Cost: 30–50 model calls per task (planner + editors + verifier batches), median 12–13 s; the rename of 3,000
paragraphs costs ~300 verifier calls. Acceptable for document-wide edits; the verifier is the part to make cheaper.

## Limits

- Seeds 1, 2 and 4 were inspected while designing; seeds 3, 5 and 6 were each unseen by the version they tested.
- Synthetic contracts: real documents have messier numbering, tables with prose, footnotes, fields. The live
  check on the Acme Share Purchase Agreement (below) is one real document.
- The model is GLM-5 only; results may differ on other models.
- Multi-turn follow-ups ("now also clause 9") are carried by the working set (B1) but not yet in the benchmark.
