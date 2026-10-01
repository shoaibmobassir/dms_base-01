# Long-document editing (2026-09-28 03:49, model zai.glm-5)

| Architecture | exact | recall | precision | unintended | errors | median s | max prompt chars | calls |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| production | 14/18 | 0.99 | 1.0 | 3 | 0 | 17.8 | 40,570 | 721 |

Recall by task (pages):

| Architecture | amend_clause | crossref_update | delete_schedule | insert_after | rename_term | semantic_payment |
|---|--:|--:|--:|--:|--:|--:|
| production | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00⚠1 / 1.00⚠1 / 1.00⚠1 | 1.00 / 0.82 / 1.00 |
