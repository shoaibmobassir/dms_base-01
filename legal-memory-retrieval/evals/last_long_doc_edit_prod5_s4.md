# Long-document editing (2026-09-28 03:41, model zai.glm-5)

| Architecture | exact | recall | precision | unintended | errors | median s | max prompt chars | calls |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| production | 13/18 | 0.941 | 0.944 | 3 | 0 | 12.2 | 41,748 | 794 |

Recall by task (pages):

| Architecture | amend_clause | crossref_update | delete_schedule | insert_after | rename_term | semantic_payment |
|---|--:|--:|--:|--:|--:|--:|
| production | 0.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00⚠1 / 1.00⚠1 / 1.00⚠1 | 1.00 / 1.00 / 0.94 |
