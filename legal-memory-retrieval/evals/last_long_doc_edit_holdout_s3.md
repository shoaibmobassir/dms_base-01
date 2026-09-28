# Long-document editing (2026-09-28 03:31, model zai.glm-5)

| Architecture | exact | recall | precision | unintended | errors | median s | max prompt chars | calls |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| hybrid_v2 | 11/18 | 0.944 | 0.883 | 248 | 0 | 9.6 | 40,780 | 237 |
| hybrid_v4 | 18/18 | 1.0 | 1.0 | 0 | 0 | 11.9 | 40,636 | 729 |

Recall by task (pages):

| Architecture | amend_clause | crossref_update | delete_schedule | insert_after | rename_term | semantic_payment |
|---|--:|--:|--:|--:|--:|--:|
| hybrid_v2 | 1.00 / 1.00⚠240 / 0.00⚠1 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00⚠3 / 1.00⚠1 / 1.00⚠1 | 1.00⚠1 / 1.00⚠1 / 1.00 |
| hybrid_v4 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |
