# P5.6-B0 Semantic Candidate Survival

Outcome: **A_candidate_generation**

Gold documents barely enter the pool — fix vector/BM25/query representation; **do not touch CE**.

Freeze: `MATTER_SCOPE=hard` + `p55_repair_ce_protect` (matter routing unchanged).

## Document-level R@20 (n=7)

| Stage        | Semantic R@20 | Hit@20 |
| ------------ | ------------: | -----: |
| BM25         |          0.00 |   0.00 |
| Vector       |          0.00 |   0.00 |
| Matter       |          0.00 |   0.00 |
| Hierarchical |          0.00 |   0.00 |
| Union        |          0.00 |   0.00 |
| Fusion       |          0.00 |   0.00 |
| CE           |          0.00 |   0.00 |
| Final        |          0.00 |   0.00 |

Drop stages: `candidate_generation` × 7

## Matter-level (theme clusters)

| Stage  | Matter R@20 | Matter Hit@20 |
| ------ | ----------: | ------------: |
| BM25   |       0.022 |         0.143 |
| Vector |       0.191 |         **1.0** |
| Matter |       0.012 |         0.571 |
| Union  |       0.207 |         **1.0** |
| Fusion |       0.111 |         1.0 |
| CE     |       0.212 |         1.0 |
| Final  |       0.126 |         1.0 |

## Deep-pool notes

- All gold docs are embedded (20/20 × 7).
- BM25 often returns 0 hits (AND-heavy FTS on long phrases).
- Vector@500 still finds **0 gold docs**, but finds many **gold matters**.
- So: right *theme/matters*, wrong *documents* — representation / doc selection problem, not fusion/CE.

## Next (P5.6-C)

1. Controlled query representation / 1–3 legal paraphrases
2. Contextual chunk embeddings (title + section + chunk) — ablation before full hierarchy
3. BM25 or-query / concept tokens so lexical channel fires
4. Optionally: after vector hits gold matters, retrieve docs **inside** those matters (reuse P5.6-A pattern)

Do **not** add channels or retune global fusion for this.
