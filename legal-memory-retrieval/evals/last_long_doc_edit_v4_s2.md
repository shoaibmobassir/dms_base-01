# Long-document editing (2026-09-28 03:28, model zai.glm-5)

| Architecture | exact | recall | precision | unintended | errors | median s | max prompt chars | calls |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| hybrid_v4 | 16/18 | 0.996 | 0.965 | 21 | 0 | 13.1 | 42,313 | 837 |

Recall by task (pages):

| Architecture | amend_clause | crossref_update | delete_schedule | insert_after | rename_term | semantic_payment |
|---|--:|--:|--:|--:|--:|--:|
| hybrid_v4 | 1.00 / 1.00 / 1.00⚠1 | 1.00 / 1.00 / 0.93⚠20 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |
