# P5.6-C5.4 Discriminative Lexical Document Retrieval

Theme ceiling avg **1.000**; typed (EL+ICA) ceiling **0.829**

| Variant | R@20 | Hit@20 | R@50 | R@100 | MRR | avg best-gold |
| ------- | ---: | -----: | ---: | ----: | --: | ------------: |
| A OR-BM25 baseline | 0.007 | 0.143 | 0.007 | 0.036 | 0.026 | 165.75 |
| B disc field-weighted | 0.000 | 0.000 | 0.000 | 0.021 | 0.004 | 209.0 |
| C disc + phrase/concept | 0.007 | 0.143 | 0.014 | 0.057 | 0.025 | 175.4 |
| D disc + phrase/concept + EL/ICA prior | 0.007 | 0.143 | 0.029 | 0.086 | 0.030 | 146.86 |

Gate D materially > A: **False** (D R@20=0.0071, A R@20=0.0071)

## Diagnosis (component scores)

Token bucketing works (e.g. Q-0264 drops `information`/`price`; keeps `SCN`/`insider`).

Top non-gold rows are typically **Research Memos** with high phrase+concept scores on title/body (e.g. score≈34 from concept≈3.8 + phrase≈1.2).

Many gold **Engagement Letter / ICA** docs are **missing or mid-pack** once ultra-common OR terms are removed — they mainly matched C5.1 via high-DF tokens, not discriminative concepts.

D lifts Hit@100 (.43 vs .14) slightly but **does not move R@20**.

## Decision

→ **C5.5 contextual document embeddings** (title + type + section/chunk context).  
Do not enable `THEME_SCOPED_DOCUMENT_RETRIEVAL`. CE / vector path / GraphRAG remain frozen.
