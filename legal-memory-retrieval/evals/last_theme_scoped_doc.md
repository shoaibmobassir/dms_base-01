# P5.6-C5 Theme-Complete Document Resolution

max_themes=1 · feature flag `THEME_SCOPED_DOCUMENT_RESOLVE=off`

Avg scope: **93 matters → 3465 docs** (SRR **11.5×** vs 38,250 corpus docs)

## Gate metrics

| Stage | R@20 | Hit@20 | R@50 | Hit@50 | R@100 |
| ----- | ---: | -----: | ---: | -----: | ----: |
| **C5.0 ceiling** | — | — | — | — | **1.000** |
| C5.1 BM25 OR | 0.007 | 0.143 | 0.007 | 0.143 | 0.036 |
| C5.2 Vector | 0.000 | 0.000 | 0.000 | 0.000 | 0.007 |
| C5.3 Union RRF | 0.000 | 0.000 | 0.007 | 0.143 | 0.029 |

Gate enable THEME_SCOPED_DOCUMENT_RESOLVE: **False** (ceiling_ok=True, union_r20_pass=False)

BM25 avg best-gold rank (when in top-500): **~166**; Vector: **~248**

## Diagnosis

1. **C5.0 PASS** — every gold document sits in the matched `theme_key`. Theme is the right routing primitive.
2. **C5.1 FAIL** — OR-BM25 matches gold (`match_or=True`) but ranks them ~100–300 because the OR query is too broad inside the theme (~3.7k of ~3.8k docs match).
3. **C5.2 FAIL** — chunk-vector still cannot surface gold docs even with theme scope + large chunk pool (best ranks often ≫500).
4. **C5.3 FAIL** — union cannot rescue what neither lane ranks.

This is the roadmap branch: *theme routing = correct; document universe = correct; BM25/vector = insufficient* → fix lexical (phrase/concept/title fields) before CE or GraphRAG.

CE remains frozen until candidate generation clears.
