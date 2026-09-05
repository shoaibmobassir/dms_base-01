# P5.6-C5.5-D4/D5 Role-Family Oracle

## D4 ceilings

| Scope | Ceiling | Avg docs |
| ----- | ------: | -------: |
| Theme | **1.000** | 3465 |
| Role family (oracle from gold) | **1.000** | 855 |
| Document type EL/ICA | **0.829** | — |

Theme→family scope reduction **~4.3×**

Oracle families are **derived from gold labels** (not hardcoded per query):
- Q-0264–0271 → `TRANSACTIONAL` (includes Term Sheet; fixes JV typed_ceil)
- Q-0273 → `PLEADING` + `ANALYSIS` + `EVIDENCE_RECORD`

## D5 retrieval (oracle hard scope)

| Variant | R@20 | Hit@20 | R@50 | R@100 | MRR |
| ------- | ---: | -----: | ---: | ----: | --: |
| D5-A theme + raw vector | 0.000 | 0.000 | — | 0.007 | — |
| D5-B family + raw vector | 0.000 | 0.000 | — | 0.107 | — |
| D5-C family + contextual | 0.014 | 0.286 | — | 0.136 | — |
| **D5-D family + lexical** | **0.043** | **0.571** | — | **0.164** | — |
| D5-E family + lex∪ctx RRF | 0.029 | 0.286 | — | 0.121 | — |

vs C5.4-D R@20=.007 · C5.5 ctx R@20=.000

## Decision

1. **Role family is the correct routing abstraction** (ceiling 1.0 > type .83).
2. Role conditioning **partially** recovers identity: Hit@20 jumps to **.57** (lexical), R@100 to **.16** — embeddings alone still weak.
3. R@20 **.043** is still far from .30/.70 → within-family discrimination remains unsolved.

**Adopt role family as a scope/prioritization layer** (production: soft promotion + fallback, not hard exclude).  
**Next:** document-purpose/content profiling **inside** the role-family scope (not another global embedding).

THEME_SCOPED / CE / GraphRAG remain off. This run is oracle-only.
