# Legal research R1-local: decision record (2026-10-02)

Design: `docs/plan/assistant-design.md` §22 (Rev 2.3). Tracking: `docs/plan/20_legal_research.md`.

## Question

Can the assistant do trustworthy legal research over the authorities the firm already holds
(2,815 UN Security Council resolutions; 208 PCIJ judgments, orders and advisory opinions) without a
licensed provider, and how much does that raise the research scorecard (§22.1)?

## What was compared

| System | What it is |
|---|---|
| **baseline** | What the assistant had: `search_firm_records` → firm-wide `retrieve()`, authorities treated as ordinary documents |
| **authority** | `search_authority`: the same hybrid search (BM25, vector, cross-encoder) restricted to authority types, one hit per authority, role-aware ordering, representative operative paragraph |
| **authority+graph** (shipped) | plus citation-graph candidates: an authority cited by ≥ 2 of the top passages is added and scored by the cross-encoder on its own best operative paragraph, +0.3 per citing passage |

A first version of the graph boost (fixed +0.5 per citation) put the most-cited resolution first
regardless of relevance: S/RES/678 fell from 1st to 4th for "all necessary means against Iraq" behind
660/661. Relevance-gating fixed that; the numbers below are for the gated version.

## Data

`evals/research/gold.jsonl`. Expected answers come from legal knowledge, not from the code:

- 58 issue questions phrased without case names (26 PCIJ, 32 UNSC), each with its controlling
  authority. 7 were used while building (`dev`: 1373, 678, 1718, Chorzów ×2, Oscar Chinn, Wimbledon);
  51 are held out (`test`).
- 23 binding-force items labeled by legal category; the paragraph is located by its text. One is a known
  hard case (S/RES/276: not Chapter VII, "calls upon", held binding in the *Namibia* opinion).
- Planted errors generated from the gold set: wrong years, non-existent numbers, non-existent PCIJ
  numbers, unheld collections (ICJ, India, US), wrong pinpoints, a CourtListener outage.

Two gold locator phrases were corrected after the first run because they were ambiguous in the source
text (598: the text says "cease-fire"; 1973: "to protect civilians" occurs in two paragraphs). The
expected labels did not change.

## Results (`evals/research/results_r1_local.json`)

| | R@1 | R@5 | R@10 | MRR | held-out R@5 | p50 |
|---|---|---|---|---|---|---|
| baseline | 0.43 | 0.64 | 0.66 | 0.52 | 0.65 | 1.0 s |
| authority | 0.72 | 0.91 | 0.97 | 0.80 | 0.90 | 2.9 s |
| **authority+graph** | **0.84** | **0.97** | **0.97** | **0.89** | **0.96** | 2.9 s |

| Gate | Result |
|---|---|
| False-verified citations (73) | 0 |
| Provider outage verified | no |
| Parser recall (30 forms) | 1.00 |
| Binding-label accuracy (23) | 1.00 (22 by rule, 1 by cited override) |
| Wrong pinpoints flagged / valid pinpoints clean | 100% / 100% |

### Bugs the eval found (all fixed, with tests)

1. **Wrong authority on lookup.** `resolve()` matched "resolution 186 (" anywhere in a title, and later
   resolutions' titles cite earlier ones, so a wrong-year citation resolved to a *different* resolution and
   verified (2 of 73 fakes). Anchored to the title start.
2. **Chapter VII missed.** "Acting *therefore* under Chapter VII" (16 resolutions) and "Acting under
   Article*s* 39 and 40" were not detected.
3. **Paragraphs lost at page breaks.** A paragraph number right after a form feed ended the operative part:
   50 resolutions had lost 285 operative paragraphs (S/RES/687 showed 5 of 34).
4. **`S/RES/N` without a year** was not recognized.

## Live check (HTTP, research mode, `evals/research/results_live_r1_local.json`)

Six held-out questions through `POST /api/chat`, generator `zai.glm-5`. The first run found two product
defects, fixed before the second run:

- The model answered "is the Hodeidah mission still mandated?" as of its training date (it wrote "today
  (11 January 2025)"). The system prompt now states today's date.
- Grounding removed binding labels and status lines, because they come from tool results rather than
  quoted passages. Research tool metadata now grounds like firm records (passage text excluded).

Second run: all 6 used the research tools; **0 fabricated or wrong citations** in 36 authority citations
(each answer cite-checked against the database); expected authority cited 5 of 5; the Hodeidah answer
traced 2742 → 2786 → 2813 and concluded correctly that the mandate ended on 31 March 2026.

## Decision

Ship R1-local with the graph-gated search. Scorecard 1.6 → **6.0** (§22.18).

## Not solved here

- Post-generation stripping of unverified citations (the §22.9 hard rule is enforced by tools, prompt
  and grounding, not by a final pass).
- Grounding removes headings and table header rows it cannot tie to a source.
- Authority searches run one after another in a round (DocIndex alias allocation is not thread-safe).
- Search latency: p50 2.9 s against 1.0 s for firm search.
- Indian, ICJ and treaty sources (R2).
