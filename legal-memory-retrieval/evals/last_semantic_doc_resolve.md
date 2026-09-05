# P5.6-C0 Semantic Document Resolution

**Question:** Can vector-retrieved matters route document retrieval?

**Answer: Not yet** — matter theme discovery works; document-holding matters do not.

## Results

Baseline open-vector Doc R@20: **0.0**

| Matter K | Matter Hit@K | Matter Precision@K | Doc ceiling | Doc R@20 | Avg docs in scope |
| -------: | -----------: | -----------------: | ----------: | -------: | ----------------: |
| 5 | 1.000 | 1.000 | 0.029 | 0.014 | 188 |
| 10 | 1.000 | 1.000 | 0.057 | 0.000 | 379 |
| 20 | 1.000 | 1.000 | 0.100 | 0.000 | 654 |
| 50 | 1.000 | 1.000 | 0.100 | 0.000 | 685 |

## What this means

```text
Vector top-K matters
  ├── always gold matters (precision 1.0)  ✓ theme discovery
  └── rarely the ~3–10 matters that hold gold docs  ✗ doc routing
```

- Oracle (all labeled gold matters) → Doc ceiling **1.0**
- Vector-routed subset → Doc ceiling **≤ 0.10** even at K=50
- Holder-matter ranks: often **absent** from top-300 vector matters

## Decision

Do **not** enable `SEMANTIC_DOC_RESOLVE=c0` in production.

Next experiments must improve **holder-matter recall** before matter→doc routing can work:

1. **C1** OR-BM25 / phrase lexical
2. **C2** query representation (concepts/entities)
3. **C3** controlled paraphrases
4. **C4** contextual / matter-level embeddings
