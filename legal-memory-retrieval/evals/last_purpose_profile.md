# P5.6-C5.5-D6 Within-Family Purpose Profiling

## Ceilings

| Scope | Ceiling | Avg docs |
| ----- | ------: | -------: |
| Theme | **1.000** | — |
| Role family | **1.000** | 855 |
| **Purpose (oracle)** | **1.000** | **855** |
| Type EL/ICA | 0.829 | — |

Family→purpose reduction **1.00×** (no further cut on this corpus)

Oracle purposes (gold-derived):
- Q-0264–0270 → `ESTABLISH` + `ASSESS`
- Q-0271 → `ESTABLISH` + `ASSESS` + `PROPOSE`
- Q-0273 → `PLEAD` + `ANALYZE` + `RECORD`

## Retrieval (oracle purpose hard scope)

| Variant | R@20 | Hit@20 | R@100 |
| ------- | ---: | -----: | ----: |
| D6-A family + lexical (D5 control) | 0.043 | 0.571 | 0.164 |
| D6-B purpose + lexical | **0.043** | **0.571** | **0.164** |
| D6-C purpose + contextual | 0.014 | 0.286 | 0.136 |
| D6-D purpose hybrid | 0.029 | 0.286 | 0.121 |

## Decision — D6 FAIL on information gain

1. Purpose ceiling is **1.0**, but purpose scope ≈ role-family scope (multi-purpose gold oracles recreate the family).
2. Oracle purpose **does not beat D5** (R@20 stays .043).
3. Purpose is useful as a **label/debug card**, not as a new hard routing layer on this corpus.

**Stop classifying documents further.** Next: **proposition / evidence-level retrieval** — retrieve passages that support the legal proposition the query asks for, inside theme (+ soft role prior).

Flags remain OFF.
