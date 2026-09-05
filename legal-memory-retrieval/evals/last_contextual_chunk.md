# P5.6-C5.5 Contextual Chunk Embeddings (A1/A2/A3)

Frozen C5.4-D: R@20 **0.007**, Hit@100 **0.429**, avg best-gold ≈ **147**

Theme ceiling **1.000**; typed ceiling **0.829**

| Variant | R@20 | Hit@20 | R@50 | R@100 | MRR | avg best-gold |
| ------- | ---: | -----: | ---: | ----: | --: | ------------: |
| raw_max (control) | 0.000 | 0.000 | 0.000 | 0.007 | 0.002 | ~248 |
| A1 ctx + max | 0.000 | 0.000 | 0.000 | 0.000 | 0.003 | ~163 |
| A2 ctx + top3_mean | 0.000 | 0.000 | 0.000 | 0.000 | 0.002 | ~211 |
| A3 ctx + top5_mean | 0.000 | 0.000 | 0.000 | 0.000 | 0.002 | ~211 |

Gate: **Case C** (R@100 ≈ 0) → inspect EL/ICA vs Research Memo representation

## Diagnostics

- Top-20 docs are dominated by **Legal Opinion / Research Memo / Matter Strategy Note** (topic match), not EL/ICA.
- Gold EL/ICA chunks often have sim ≈ **0.40–0.52** but still lose to topic-rich memos; when ranked, margin vs top-1 is negative (e.g. −0.11).
- Aggregation (max / top-3 / top-5) does **not** rescue missing documents.

## Decision

Contextualizing MiniLM chunk text with title+type+section is **not sufficient** to identify holder documents inside the theme.

Do **not** enable ctx lane / CE / GraphRAG.  
Do **not** jump to full hierarchical B/C until we answer: what content/labels actually separate gold EL/ICA from Research Memos in the same theme.

`THEME_SCOPED_DOCUMENT_RETRIEVAL` remains **off**.
