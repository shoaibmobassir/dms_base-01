# Long-document editing (2026-09-28 04:02, model zai.glm-5)

| Architecture | exact | recall | precision | unintended | errors | median s | max prompt chars | calls |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| production | 15/18 | 0.88 | 0.889 | 0 | 0 | 12.3 | 42,247 | 651 |

Recall by task (pages):

| Architecture | amend_clause | crossref_update | delete_schedule | insert_after | rename_term | semantic_payment |
|---|--:|--:|--:|--:|--:|--:|
| production | 1.00 / 1.00 / 0.00 | 1.00 / 1.00 / 1.00 | 1.00 / 0.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 0.84 |
