# Long-document editing (2026-09-28 03:23, model zai.glm-5)

| Architecture | exact | recall | precision | unintended | errors | median s | max prompt chars | calls |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| hybrid_v2 | 11/18 | 0.875 | 0.883 | 525 | 1 | 11.3 | 42,309 | 205 |
| hybrid_v3 | 16/18 | 0.889 | 0.889 | 0 | 2 | 15.1 | 39,920 | 202 |

Recall by task (pages):

| Architecture | amend_clause | crossref_update | delete_schedule | insert_after | rename_term | semantic_payment |
|---|--:|--:|--:|--:|--:|--:|
| hybrid_v2 | 1.00 / 1.00 / 0.00⚠520 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00⚠1 / 0.00 / 1.00⚠1 | 0.89 / 0.92⚠1 / 0.95⚠2 |
| hybrid_v3 | 1.00 / 1.00 / 0.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 0.00 |
