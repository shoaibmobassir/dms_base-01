# P5.6-C5.5-D Document Profile Discovery

Queries **7** · gold docs **140** · hard-neg **242** · typed ceiling **0.829**

## D3 — Why typed ceiling ≈ .83

Interpretation: **B_benchmark_problem** (not a label bug on EL/ICA rows)

| Query | Typed ceil | Non-EL/ICA gold |
| ----- | ---------: | --------------- |
| Q-0271 (JV) | 0.80 | 4× **Term Sheet** (role=`PRIMARY_AGREEMENT`) |
| Q-0273 (flood) | **0.00** | 8× Research Memo, 9× Statement of Claim, 3× Hearing Notes |
| others | 1.00 | — |

So EL/ICA-only filters **cannot** be the final architecture: they hard-lose the flood query and partially lose JV.

## D2 — Top discriminative features (gold vs Research Memo / Opinion / Strategy)

| Feature | P(gold) | P(hard-neg) | mean_gold | mean_neg | log_odds |
| ------- | ------: | ----------: | --------: | -------: | -------: |
| is_el_ica | 0.829 | 0.000 | 0.829 | 0.0 | **8.48** |
| role_engagement | 0.829 | 0.000 | 0.829 | 0.0 | **8.48** |
| engagement_header | 0.429 | 0.000 | 0.429 | 0.0 | 6.62 |
| assessment_header | 0.400 | 0.000 | 0.400 | 0.0 | 6.50 |
| role_strategy / opinion_header | 0.000 | ~0.22–0.27 | — | — | **−5.6** |
| char/word_count (longer) | 0.264 | 0.641 | 576 / 82w | 717 / 106w | −1.60 |
| citation_count | 0.064 | 0.143 | — | — | −0.89 |

## What this means

1. **Genre/type/role is the discriminative signal** — not topical vocabulary.
2. On this corpus, signature / shall / defined-term features are **absent** (template bodies are short) — real production docs may still differ.
3. Hard-neg memos/opinions are slightly **longer** and more citation-like; gold EL/ICA are short engagement templates.
4. Next oracle tests should use **role families**, not EL/ICA alone:
   - `ENGAGEMENT_DOCUMENT` ∪ `PRIMARY_AGREEMENT` (Term Sheet)
   - plus dispute roles for flood-like queries (`PLEADING` / procedural)

Dataset: `gold_vs_hardneg_dataset.jsonl`

Next: **D4 type-oracle** / **D5 role-oracle** retrieval.  
`THEME_SCOPED_DOCUMENT_RETRIEVAL` remains off. CE / GraphRAG frozen.
