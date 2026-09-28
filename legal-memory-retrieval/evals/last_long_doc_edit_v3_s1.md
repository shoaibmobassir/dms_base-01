# Long-document editing (2026-09-28 03:19, model zai.glm-5)

| Architecture | exact | recall | precision | unintended | errors | median s | max prompt chars | calls |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| hybrid_v2 | 13/18 | 0.931 | 0.944 | 4 | 0 | 8.8 | 37,662 | 209 |
| hybrid_v3 | 12/18 | 0.875 | 0.885 | 6 | 1 | 14.1 | 38,418 | 147 |

Recall by task (pages):

| Architecture | amend_clause | crossref_update | delete_schedule | insert_after | rename_term | semantic_payment |
|---|--:|--:|--:|--:|--:|--:|
| hybrid_v2 | 1.00 / 0.00⚠1 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00⚠1 / 1.00⚠1 / 1.00⚠1 | 0.75 / 1.00 / 1.00 |
| hybrid_v3 | 1.00 / 1.00 / 0.00⚠1 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00⚠4 / 1.00 / 0.00 | 1.00⚠1 / 0.82 / 0.94 |
