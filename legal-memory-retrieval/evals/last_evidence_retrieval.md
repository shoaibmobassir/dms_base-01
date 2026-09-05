# P5.6-C7.4b / C7.5 Evidence Retrieval + CE

Soft role: ×2.5 preferred / ×0.7 ANALYSIS. CE = proposition↔passage.
Flags OFF. CE not enabled for document ranking.

| Variant | Ev R@20 | Hit@20 | Ev R@50 | Ev R@100 | MRR |
| ------- | ------: | -----: | ------: | -------: | --: |
| lexical | 0.033 | 0.357 | 0.056 | 0.072 | 0.190 |
| phrase | 0.026 | 0.214 | 0.049 | 0.065 | 0.021 |
| proximity | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| hybrid_lexical | 0.026 | 0.214 | 0.049 | 0.065 | 0.021 |
| lexical_hard_role | 0.055 | 0.714 | 0.126 | 0.168 | 0.241 |
| vector_raw | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| vector_ctx | 0.000 | 0.000 | 0.007 | 0.007 | 0.006 |
| hybrid_rrf | 0.000 | 0.000 | 0.033 | 0.056 | 0.009 |
| hybrid_hard_role | 0.025 | 0.357 | 0.092 | 0.170 | 0.061 |
| ce_soft | 0.004 | 0.071 | 0.023 | 0.065 | 0.040 |
| ce_hard_role | 0.024 | 0.357 | 0.071 | 0.168 | 0.087 |

Doc-from-ce_hard R@20 **0.018** (D5 ref 0.043)

Gate: soft_r20=0.033 ce_hard=0.024 helps_hard=False → **candidate generation still bottleneck; CE cannot invent gold**
