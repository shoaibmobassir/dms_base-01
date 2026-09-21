# Index baseline — HNSW and GIN with and without a matter filter

Captured 2026-09-14 against Postgres 16.14 at `localhost:55432`. Corpus: 3,081 documents, 36,191 embedded chunks. No index knobs were changed. This is the million-document control sample: a matter filter already changes the plan from an index-wide ANN/FTS scan to a nested loop over one matter's documents.

Probe vector: one stored chunk embedding. FTS probe: `factory | chorzow`. Matter filter: `documents.matter_id = (SELECT matter_id FROM documents LIMIT 1)` (that matter had 6 documents / 79 chunks; the lexical probe did not occur in it, so the filtered FTS returned 0 rows).

| Query | Plan shape | Execution |
| ----- | ---------- | --------: |
| HNSW, no matter filter | Index scan `idx_chunks_embedding_hnsw`, Order By embedding distance | 200.7 ms (50 requested, 40 returned) |
| HNSW, matter filter | Index on `documents.matter_id`, then bitmap chunk lookup, in-memory sort | 10.2 ms (50 returned) |
| GIN, no matter filter | Bitmap index scan `idx_chunks_tsv` (272 hits) | 32.8 ms |
| GIN, matter filter | Index on `documents.matter_id`, bitmap-and with `idx_chunks_tsv` | 0.2 ms (0 hits in that matter) |

No sequential scan of `chunks` on any of the four probes. Partitioning is not justified by this snapshot. Runtime `to_tsvector(title)` is not in these probes; the live BM25 query adds it, so re-check that clause only if stage p95 later names BM25.

Do not treat the 0.2 ms GIN number as a production p95. It is one matter that did not match the probe terms. The useful comparison is the plan shape: scoped queries do not walk the HNSW index.
