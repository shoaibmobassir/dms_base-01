# Long-document editing (2026-09-28 03:15, model zai.glm-5)

| Architecture | exact | recall | precision | unintended | errors | median s | max prompt chars | calls |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| mapreduce_v2 | 11/18 | 0.817 | 0.885 | 136 | 1 | 9.3 | 31,483 | 159 |
| hybrid_v2 | 12/18 | 0.929 | 0.938 | 9 | 0 | 8.7 | 37,662 | 208 |

Recall by task (pages):

| Architecture | amend_clause | crossref_update | delete_schedule | insert_after | rename_term | semantic_payment |
|---|--:|--:|--:|--:|--:|--:|
| mapreduce_v2 | 1.00 / 0.00⚠1 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 0.98⚠16 / 0.00 / 0.96⚠119 | 0.75 / 0.55 / 0.47 |
| hybrid_v2 | 0.00⚠1 / 1.00 / 1.00 | 0.97⚠1 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 | 1.00⚠1 / 1.00⚠1 / 1.00⚠4 | 0.75⚠1 / 1.00 / 1.00 |
