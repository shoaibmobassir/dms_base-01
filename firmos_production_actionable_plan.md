# FirmOS Production-Grade Document Intelligence & Review System
## Actionable Implementation Plan

> **Goal:** Build a production system capable of ingesting thousands of files/folders, preserving document/matter context, indexing hundreds of long documents, and completing targeted reviews across 100s–1,000s of documents with parallel retrieval, reasoning, verification, caching, provenance, and observability.

---

# 0. Product Goal & Non-Negotiable Principles

## Target workload

The system must eventually support:

- 1,000+ documents per matter/workspace
- 100+ pages per document on average
- 100,000+ pages represented in a review corpus
- PDFs, DOCX, XLSX and other common legal/business files
- Nested folders and matter/client hierarchy
- Multiple immutable document versions
- AI findings anchored to exact source evidence
- Cross-document review
- Parallel processing
- Partial failure and retry
- Full auditability and traceability

## Core principle

> **The PDF is not the document.**

A PDF is one representation of a **document version**.

The canonical object is:

```text
Document Version
├── Raw artifact
├── Structured content
├── Visual representation
├── Semantic representation
├── Search representation
├── Graph representation
├── AI findings
├── Annotations
├── Citations
└── Audit history
```

## Architectural boundaries

Build two hard boundaries:

### Retrieval Engine

Answers:

> Where is the relevant knowledge?

```text
BM25 / lexical
Vector
Metadata
Matter hierarchy
Graph
Reranker
```

### Review Engine

Answers:

> What does the retrieved evidence collectively mean?

```text
Planner
→ parallel analysis
→ evidence extraction
→ aggregation
→ cross-document reasoning
→ verification
→ synthesis
```

---

# Part I — Foundation

## Phase 1 — Define the domain model

### Objective

Create the stable domain model before building retrieval or AI.

### Tasks

- [ ] Define `Tenant`
- [ ] Define `User`
- [ ] Define `Client`
- [ ] Define `Matter`
- [ ] Define `Folder`
- [ ] Define `Document`
- [ ] Define `DocumentVersion`
- [ ] Define `DocumentBlock`
- [ ] Define `Chunk`
- [ ] Define `Entity`
- [ ] Define `Relationship`
- [ ] Define `Finding`
- [ ] Define `Evidence`
- [ ] Define `Annotation`
- [ ] Define `ReviewJob`
- [ ] Define `ReviewTask`
- [ ] Define `AuditEvent`

### Required hierarchy

```text
Tenant
└── Client
    └── Matter
        └── Folder
            └── Document
                └── DocumentVersion
                    ├── Pages
                    ├── Sections
                    ├── Blocks
                    ├── Tables
                    ├── Chunks
                    ├── Entities
                    ├── Relationships
                    ├── Summaries
                    └── Findings
```

### Definition of Done

- [ ] Schema documented
- [ ] IDs are immutable/stable
- [ ] Foreign-key relationships defined
- [ ] Tenant isolation represented
- [ ] Versioning semantics documented
- [ ] Pydantic/domain models implemented
- [ ] Initial PostgreSQL migrations created
- [ ] Unit tests for hierarchy and version creation

---

# Phase 2 — Immutable document versioning

## Objective

Make versioning a first-class primitive.

### Rules

A version is immutable.

```text
Document
├── v1
├── v2
├── v3
└── v4 ← current
```

Never mutate v3 when v4 is uploaded.

### `document_versions`

```text
id
document_id
version_number
parent_version_id
content_hash
storage_uri
mime_type
page_count
created_by
created_at
change_summary
is_current
```

### Tasks

- [ ] Create version creation API
- [ ] Generate content hash
- [ ] Store parent version
- [ ] Enforce immutable versions
- [ ] Maintain `current_version_id`
- [ ] Add version timeline
- [ ] Add version metadata
- [ ] Add version status
- [ ] Add audit events
- [ ] Add duplicate-content detection

### Definition of Done

Upload the same document 3 times and prove:

```text
v1 != v2 != v3
```

while preserving all previous artifacts and intelligence.

---

# Phase 3 — Object storage

## Objective

Separate binary files from relational metadata.

### Storage layout

```text
tenant/
└── client/
    └── matter/
        └── document/
            └── versions/
                ├── v001/original.pdf
                ├── v002/original.pdf
                └── v003/original.pdf
```

### Tasks

- [ ] Configure S3-compatible object storage
- [ ] Implement upload service
- [ ] Generate deterministic storage keys
- [ ] Store object metadata
- [ ] Implement checksum validation
- [ ] Implement signed download URLs
- [ ] Implement delete/retention policy
- [ ] Implement object existence verification
- [ ] Never store large binaries in PostgreSQL

### Definition of Done

A document can be uploaded and downloaded without touching the application database for binary transfer.

---

# Part II — Production Ingestion

# Phase 4 — Asynchronous ingestion pipeline

## Objective

Uploading a folder should not synchronously parse and embed everything.

### Target architecture

```text
Upload
  ↓
Upload Batch
  ↓
Object Storage
  ↓
Manifest
  ↓
Workflow
  ↓
Parse
  ↓
OCR
  ↓
Structure
  ↓
Metadata
  ↓
Chunk
  ↓
Embed
  ↓
Entities
  ↓
Summaries
  ↓
Graph
  ↓
Indexes
  ↓
READY
```

### Tasks

- [ ] Create `UploadBatch`
- [ ] Create ingestion job model
- [ ] Add workflow engine
- [ ] Add job queue
- [ ] Implement job states
- [ ] Add retry policy
- [ ] Add dead-letter handling
- [ ] Add idempotency keys
- [ ] Add job heartbeat
- [ ] Add progress reporting
- [ ] Add cancellation
- [ ] Add per-document failure isolation

### Recommended first stack

```text
FastAPI
PostgreSQL
S3/MinIO
Redis
Temporal or Celery
```

### Definition of Done

Uploading 1,000 files creates 1,000 independently trackable ingestion tasks and one failed document does not fail the batch.

---

# Phase 5 — Folder and hierarchy preservation

## Objective

Never flatten user context.

### Preserve

```text
Client
└── Matter
    └── Transaction Documents
        └── Agreements
            └── SPA.pdf
```

### Tasks

- [ ] Create folder tree
- [ ] Store `parent_folder_id`
- [ ] Store source metadata
- [ ] Store source ID
- [ ] Store normalized path
- [ ] Preserve original filename
- [ ] Preserve upload order
- [ ] Preserve folder context in every downstream record
- [ ] Include folder/matter context in retrieval metadata

### Context envelope

Every chunk should be able to reconstruct:

```text
Tenant
→ Client
→ Matter
→ Folder
→ Document
→ Version
→ Section
→ Paragraph
→ Chunk
```

---

# Phase 6 — Document parsing and canonical structure

## Objective

Convert heterogeneous files into one canonical document representation.

### Canonical hierarchy

```text
DocumentVersion
└── Section
    └── Subsection
        └── Block
            ├── Paragraph
            ├── Heading
            ├── Table
            ├── Table Cell
            ├── List
            ├── Footnote
            ├── Header
            ├── Footer
            ├── Signature
            └── Citation
```

### Tasks

- [ ] PDF parser
- [ ] OCR fallback
- [ ] DOCX parser
- [ ] XLSX extraction
- [ ] Page extraction
- [ ] Heading detection
- [ ] Paragraph detection
- [ ] Table extraction
- [ ] Footnote detection
- [ ] Header/footer handling
- [ ] Citation extraction
- [ ] Signature detection
- [ ] Block ordering
- [ ] Block hashing
- [ ] Character offsets

### Definition of Done

Every extracted block has:

```text
block_id
version_id
page
section
sequence
text
text_hash
start_offset
end_offset
block_type
```

---

# Phase 7 — Durable evidence anchors

## Objective

Make AI highlights and annotations survive rendering changes, OCR regeneration and version changes.

## Canonical anchor

```json
{
  "version_id": "v8",
  "block_id": "blk_8_2_04",
  "start_offset": 183,
  "end_offset": 392,
  "quoted_text": "The aggregate liability...",
  "text_hash": "sha256..."
}
```

## Anchor fallback hierarchy

```text
1. block_id + offsets
2. quoted_text + text_hash
3. page + approximate bounding box
```

### Tasks

- [ ] Implement anchor schema
- [ ] Implement anchor resolver
- [ ] Implement text-hash validation
- [ ] Implement quote search fallback
- [ ] Implement nearest-block fallback
- [ ] Store rendering coordinates only as derived data
- [ ] Add anchor confidence
- [ ] Test against OCR regeneration
- [ ] Test against PDF re-rendering

### Definition of Done

A finding remains navigable after the document is rendered again.

---

# Part III — Document Intelligence

# Phase 8 — Hierarchical chunking

## Objective

Replace flat fixed-size chunking with structure-aware chunks.

### Hierarchy

```text
Document
└── Section
    └── Subsection
        └── Paragraph
            └── Chunk
```

### Chunk metadata

```text
tenant_id
client_id
matter_id
folder_id
document_id
version_id
section_id
parent_chunk_id
page
sequence
text
text_hash
```

### Tasks

- [ ] Implement section-aware chunking
- [ ] Implement paragraph-aware chunking
- [ ] Preserve parent/child relationships
- [ ] Add neighboring chunk relationships
- [ ] Add overlap only when useful
- [ ] Avoid splitting tables incorrectly
- [ ] Avoid splitting legal clauses unnecessarily
- [ ] Add chunk IDs stable within a version
- [ ] Add chunk token counts

---

# Phase 9 — Hierarchical summarization

## Objective

Create compressed representations so large document sets can be reviewed without sending entire documents to the LLM.

### Pipeline

```text
Page
 ↓
Section summary
 ↓
Document summary
 ↓
Matter summary
 ↓
Firm knowledge
```

### Document intelligence

```text
Document
├── Executive summary
├── Parties
├── Dates
├── Monetary values
├── Obligations
├── Rights
├── Risks
├── Clauses
├── Citations
├── Authorities
└── Entities
```

### Tasks

- [ ] Generate page/section summaries where useful
- [ ] Generate document summary
- [ ] Extract key facts
- [ ] Extract parties
- [ ] Extract dates
- [ ] Extract monetary values
- [ ] Extract obligations
- [ ] Extract rights
- [ ] Extract risks
- [ ] Extract legal concepts
- [ ] Store structured intelligence
- [ ] Version intelligence artifacts
- [ ] Cache intelligence artifacts

### Important optimization

If only the summary prompt changes:

```text
DO NOT:
reparse → re-chunk → re-embed

DO:
regenerate summary only
```

---

# Phase 10 — Entity and relationship extraction

## Objective

Build the graph during ingestion rather than at query time.

### Example

```text
Contract
├── Party
├── Counterparty
├── Agreement Type
├── Clause
│   ├── Indemnity
│   ├── Termination
│   └── Change of Control
├── Obligation
├── Date
└── Governing Law
```

### Tasks

- [ ] Define entity taxonomy
- [ ] Define relationship taxonomy
- [ ] Extract entities
- [ ] Normalize entities
- [ ] Deduplicate entities
- [ ] Extract relationships
- [ ] Link relationships to source blocks
- [ ] Store confidence
- [ ] Store extraction model/version
- [ ] Build graph update pipeline

---

# Part IV — Retrieval Engine

# Phase 11 — Hybrid retrieval

## Objective

Run retrieval channels in parallel.

```text
                 Query
                   ↓
             Query Planner
                   ↓
       ┌───────────┼───────────┐
       ↓           ↓           ↓
     BM25        Vector       Graph
       ↓           ↓           ↓
       └───────────┼───────────┘
                   ↓
                 Fusion
                   ↓
                Rerank
```

### Initial implementation

- [ ] BM25 / PostgreSQL FTS
- [ ] Vector retrieval / pgvector
- [ ] Metadata filtering
- [ ] Graph retrieval
- [ ] Parallel execution
- [ ] Per-channel scores
- [ ] Candidate deduplication
- [ ] Reciprocal Rank Fusion
- [ ] Cross-encoder reranking

### Definition of Done

A query returns candidates with:

```text
source
score
document
version
section
chunk
retrieval_channel
rank
```

---

# Phase 12 — Hierarchical retrieval

## Objective

Avoid searching millions of chunks blindly.

### Pipeline

```text
Query
 ↓
Matter retrieval
 ↓
Document retrieval
 ↓
Chunk retrieval
 ↓
Rerank
 ↓
Evidence
```

### Tasks

- [ ] Build matter-level search
- [ ] Build document-level search
- [ ] Build chunk-level search
- [ ] Propagate scores downward
- [ ] Add metadata filters early
- [ ] Add candidate budgets
- [ ] Add adaptive retrieval depth
- [ ] Benchmark flat vs hierarchical retrieval

### Target

Reduce:

```text
100,000 pages
```

to:

```text
candidate documents
→ relevant sections
→ relevant evidence blocks
```

before invoking expensive reasoning.

---

# Phase 13 — Query understanding and planning

## Objective

Turn natural-language review requests into executable retrieval plans.

### Example

User:

> Find unusual change-of-control provisions across these contracts.

Planner creates:

```text
Intent:
legal_review

Issues:
- change_of_control
- consent_requirements
- unusual_terms

Scope:
selected matter

Retrieval:
- semantic
- lexical
- graph

Review:
cross_document
```

### Tasks

- [ ] Query classification
- [ ] Entity extraction
- [ ] Issue extraction
- [ ] Scope detection
- [ ] Query decomposition
- [ ] Retrieval channel selection
- [ ] Retrieval budget selection
- [ ] Review strategy selection

---

# Phase 14 — Context builder

## Objective

Construct compact but context-rich LLM inputs.

Never simply concatenate the top 20 chunks.

### Context structure

```text
Matter context
+
Document context
+
Section context
+
Primary evidence
+
Supporting evidence
+
Neighboring blocks
+
Graph evidence
+
Version comparison
+
Citations
+
Instructions
```

### Tasks

- [ ] Primary evidence selection
- [ ] Supporting evidence selection
- [ ] Neighbor expansion
- [ ] Parent section expansion
- [ ] Document summary injection
- [ ] Matter context injection
- [ ] Graph context injection
- [ ] Token budget management
- [ ] Evidence deduplication
- [ ] Citation mapping

---

# Part V — Review Engine

# Phase 15 — Review Planner

## Objective

Convert a large review into independent executable tasks.

### Example

```text
Review Request
├── Change of Control
├── Termination
├── Indemnification
├── Liability Caps
├── Governing Law
└── Unusual Obligations
```

Each issue becomes an independent review task.

### Tasks

- [ ] Define `ReviewJob`
- [ ] Define `ReviewTask`
- [ ] Generate subquestions
- [ ] Assign document scopes
- [ ] Assign retrieval strategies
- [ ] Assign token budgets
- [ ] Assign model policies
- [ ] Assign priority

---

# Phase 16 — Map → Reduce → Verify

## MAP

Analyze documents independently.

```text
Document
 ↓
Evidence extraction
 ↓
Finding
 ↓
Citation
 ↓
Confidence
```

Run these in parallel.

## REDUCE

Aggregate:

```text
150 documents
 ↓
150 structured results
 ↓
group by issue
 ↓
cross-document patterns
```

## VERIFY

For every material claim:

```text
Claim
 ↓
Evidence lookup
 ↓
Does evidence support claim?
 ├── YES → keep
 └── NO  → abstain/remove
```

### Tasks

- [ ] Implement parallel document review
- [ ] Define structured finding schema
- [ ] Implement finding store
- [ ] Implement aggregation
- [ ] Implement cross-document comparison
- [ ] Implement claim/evidence verification
- [ ] Implement abstention
- [ ] Implement final synthesis

---

# Phase 17 — Finding + Evidence abstraction

## Objective

Make `Finding + Evidence + Anchor + Version` a core product primitive.

### Finding

```text
Finding
├── id
├── document_id
├── version_id
├── category
├── severity
├── title
├── explanation
├── confidence
├── evidence[]
├── comparison
├── status
└── created_by
```

### Evidence

```text
Evidence
├── version_id
├── document_id
├── block_id
├── page
├── section
├── quote
├── offsets
└── anchor
```

### Finding lifecycle

```text
OPEN
 ↓
REVIEWED
 ↓
ACCEPTED
```

or:

```text
OPEN
 ↓
DISMISSED
```

### Tasks

- [ ] Create finding schema
- [ ] Create evidence schema
- [ ] Link findings to exact blocks
- [ ] Add severity
- [ ] Add confidence
- [ ] Add review status
- [ ] Add AI/lawyer authorship
- [ ] Add finding versioning
- [ ] Add finding audit trail

---

# Phase 18 — Version comparison

## Objective

Support both exact textual and semantic/legal changes.

## Level 1 — File diff

```text
Pages: 48 → 49
Sections: 32 → 33
Tables: 7 → 8
```

## Level 2 — Section diff

```text
8.2 Tax Indemnity     CHANGED
11 Governing Law      CHANGED
12 Termination        ADDED
```

## Level 3 — Paragraph diff

Exact textual changes.

## Level 4 — Semantic/legal diff

```text
LIABILITY

Seller tax indemnity cap

$50,000 → $75,000

Impact:
Seller exposure increased by $25,000.
```

### Tasks

- [ ] Implement block matching
- [ ] Implement lexical diff
- [ ] Implement section diff
- [ ] Implement paragraph diff
- [ ] Implement semantic diff
- [ ] Categorize legal impact
- [ ] Detect financial impact
- [ ] Detect obligation changes
- [ ] Detect deadline changes
- [ ] Detect rights changes
- [ ] Detect termination changes
- [ ] Detect governing-law changes
- [ ] Store diff artifacts

---

# Phase 19 — Annotation system

## Supported types

```text
AI Highlight
Lawyer Highlight
Comment
Issue
Redline
Citation
```

### Tasks

- [ ] Unified annotation schema
- [ ] Durable anchors
- [ ] AI → document navigation
- [ ] Document → finding navigation
- [ ] Comments
- [ ] Mentions
- [ ] Review status
- [ ] Annotation permissions
- [ ] Audit events

### UX requirement

Clicking a finding:

```text
Finding
 ↓
Exact document location
 ↓
Page
 ↓
Section
 ↓
Highlighted evidence
```

Clicking highlighted evidence:

```text
Evidence
 ↓
Why highlighted?
 ↓
Finding
 ↓
Previous/current comparison
 ↓
Risk
 ↓
Citation
```

---

# Part VI — Scale & Performance

# Phase 20 — Multi-level caching

## Objective

Avoid recomputing expensive derived intelligence.

### Cache

```text
Parsing
Structure
Chunks
Embeddings
Summaries
Entities
Graph extraction
Retrieval
Review results
```

### Cache identity

```text
tenant_id
document_id
version_id
permission_version
model_version
analysis_version
```

### Content-aware invalidation

Track:

```text
document_hash
content_version
parser_version
embedding_version
summary_version
analysis_version
```

### Tasks

- [ ] Redis cache layer
- [ ] Content-addressed cache keys
- [ ] Embedding cache
- [ ] Summary cache
- [ ] Retrieval cache
- [ ] Review cache
- [ ] Permission-aware cache isolation
- [ ] Cache metrics
- [ ] Cache invalidation rules

---

# Phase 21 — Parallelism and workload control

## Objective

Scale throughput without overwhelming databases, model APIs or workers.

### Implement

- [ ] Worker pools
- [ ] Per-stage concurrency limits
- [ ] Global concurrency limits
- [ ] Rate limiting
- [ ] Backpressure
- [ ] Priority queues
- [ ] Batch embedding
- [ ] Batch metadata operations
- [ ] Parallel retrieval channels
- [ ] Parallel document reviews
- [ ] Timeouts
- [ ] Retries with exponential backoff
- [ ] Circuit breakers

### Critical rule

Do not make "parallel" mean "unbounded."

Use:

```text
Queue
→ Scheduler
→ bounded workers
→ downstream limits
```

---

# Phase 22 — Graceful degradation

## Objective

One failure should not destroy an entire review.

Example:

```text
150 documents

147 successful
2 OCR failed
1 parser failed
```

Return:

> Reviewed 147/150 documents. 3 documents require attention.

### Tasks

- [ ] Per-document failure state
- [ ] Per-task failure state
- [ ] Partial result support
- [ ] Retry failed documents
- [ ] Dead-letter queue
- [ ] User-visible error list
- [ ] Confidence reduction when coverage is incomplete
- [ ] Final response coverage statistics

---

# Part VII — Production Search Infrastructure

# Phase 23 — Storage strategy

## Start simple

```text
PostgreSQL
+
pgvector
+
S3/MinIO
+
Redis
```

## Scale when benchmarks justify it

Potential evolution:

```text
PostgreSQL
→ OpenSearch for large-scale lexical/search workloads

pgvector
→ specialized vector store only if required

Graph interface
→ PostgreSQL/AGE or Neo4j based on benchmark results
```

### Rule

Do not introduce infrastructure because it is fashionable.

Introduce it when measured workload requires it.

---

# Phase 24 — GraphRAG

## Ingestion-time graph creation

```text
Upload
 ↓
Parse
 ↓
Entity extraction
 ↓
Relationship extraction
 ↓
Graph update
```

## Query-time graph retrieval

```text
Query
 ↓
Entity identification
 ↓
Graph traversal
 ↓
Relevant relationships
 ↓
Evidence retrieval
```

### Tasks

- [ ] Define graph schema
- [ ] Build entity nodes
- [ ] Build relationship edges
- [ ] Attach source evidence
- [ ] Add graph confidence
- [ ] Implement graph traversal
- [ ] Combine graph results with vector/BM25
- [ ] Benchmark graph usefulness

---

# Part VIII — Security, Permissions & Audit

# Phase 25 — Authorization

## Objective

Never allow retrieval to bypass document permissions.

### Permission boundary

Authorization must be applied before retrieval results reach the model.

```text
User
 ↓
ACL
 ↓
Allowed tenant/matter/document/version IDs
 ↓
Retrieval
 ↓
Evidence
 ↓
LLM
```

### Tasks

- [ ] Tenant isolation
- [ ] Matter-level permissions
- [ ] Folder permissions
- [ ] Document permissions
- [ ] Role-based access
- [ ] Retrieval-time ACL filtering
- [ ] Cache permission isolation
- [ ] Signed object access
- [ ] Audit all access

---

# Phase 26 — Audit & provenance

## Objective

Answer:

> Why did the system say this?

All the way down to source evidence.

```text
Answer
 ↓
Claim
 ↓
Finding
 ↓
Evidence
 ↓
Chunk
 ↓
Block
 ↓
Page
 ↓
Document
 ↓
Version
 ↓
Matter
```

### Tasks

- [ ] Audit event model
- [ ] AI request logging
- [ ] Model/version logging
- [ ] Prompt/version logging
- [ ] Retrieval trace
- [ ] Evidence trace
- [ ] Human review events
- [ ] Version changes
- [ ] Permission events

---

# Part IX — Observability

# Phase 27 — End-to-end tracing

## Objective

Every review should become a trace.

```text
REVIEW-8291
├── planner
├── retrieval
│   ├── BM25
│   ├── Vector
│   ├── Graph
│   └── Metadata
├── document analysis
│   ├── DOC-1
│   ├── DOC-2
│   └── DOC-150
├── aggregation
├── verification
└── synthesis
```

### Recommended

```text
OpenTelemetry
Prometheus
Grafana
Tempo/Jaeger
Loki
```

### Metrics

- [ ] Ingestion throughput
- [ ] Queue depth
- [ ] Worker utilization
- [ ] Retrieval latency
- [ ] Review latency
- [ ] LLM latency
- [ ] Token usage
- [ ] Cost
- [ ] Cache hit rate
- [ ] Retrieval recall
- [ ] Evidence coverage
- [ ] Failure rate
- [ ] Retry rate
- [ ] Partial-review rate

---

# Part X — Evaluation & Benchmarking

# Phase 28 — Build the benchmark corpus

## Required benchmark

```text
1,000 documents
×
100 pages average
=
100,000 pages
```

Review query:

> Review all documents and identify contracts containing unusual change-of-control provisions and summarize the associated risk.

### Expected output metrics

```text
Documents scanned:       1,000
Pages represented:       100,000
Relevant documents:      X
Relevant clauses:        X
LLM document calls:      X
Cache hits:              X%
Retrieval latency:       X ms
Review latency:          X sec
Evidence coverage:      X%
```

---

# Phase 29 — Retrieval evaluation

Track:

```text
Recall@K
Precision@K
MRR
NDCG
Reranker lift
```

### Compare

```text
Vector only
BM25 only
Hybrid
Hybrid + Graph
Hybrid + Graph + Reranker
```

### Tasks

- [ ] Create labeled retrieval dataset
- [ ] Define relevance judgments
- [ ] Run automated retrieval benchmarks
- [ ] Track regressions
- [ ] Store benchmark history

---

# Phase 30 — Review quality evaluation

Evaluate:

- [ ] Finding precision
- [ ] Finding recall
- [ ] Evidence correctness
- [ ] Citation correctness
- [ ] Unsupported-claim rate
- [ ] Abstention quality
- [ ] Cross-document consistency
- [ ] Human reviewer agreement

### Hard requirement

A fast system with unsupported legal claims is not production-ready.

---

# Part XI — Notebook / Architecture Simulator

# Phase 31 — Build the production simulator

The notebook should demonstrate the production architecture, not simply be another PDF RAG demo.

## Notebook structure

```text
00_config
01_document_models
02_ingestion
03_document_structure
04_hierarchical_chunking
05_document_intelligence
06_vector_index
07_bm25_index
08_metadata_index
09_graph_store
10_query_understanding
11_retrieval_planner
12_parallel_retrieval
13_hierarchical_retrieval
14_fusion
15_reranking
16_review_engine
17_context_builder
18_cache
19_observability
20_load_test
21_benchmark
22_debugger
```

### Tasks

- [ ] Implement synthetic/representative corpus
- [ ] Simulate folder hierarchy
- [ ] Simulate 1,000 documents
- [ ] Simulate long documents
- [ ] Simulate versions
- [ ] Simulate graph
- [ ] Simulate failures
- [ ] Simulate cache
- [ ] Run retrieval benchmarks
- [ ] Run review benchmark
- [ ] Produce latency/cost report

---

# Part XII — Production APIs

# Phase 32 — Core APIs

## Document APIs

```text
POST   /documents
GET    /documents/:id
GET    /documents/:id/versions
POST   /documents/:id/versions
GET    /documents/:id/structure
```

## Ingestion APIs

```text
POST   /uploads
GET    /uploads/:id
GET    /uploads/:id/progress
POST   /uploads/:id/retry
POST   /uploads/:id/cancel
```

## Review APIs

```text
POST   /reviews
GET    /reviews/:id
GET    /reviews/:id/findings
GET    /reviews/:id/progress
POST   /reviews/:id/cancel
```

## Finding APIs

```text
GET    /findings/:id
PATCH  /findings/:id
GET    /findings/:id/evidence
GET    /findings/:id/annotations
```

## Diff APIs

```text
GET /documents/:id/diff?from=v7&to=v8
GET /documents/:id/semantic-diff?from=v7&to=v8
```

---

# Part XIII — UI Implementation

# Phase 33 — Document viewer

Build only after the backend primitives exist.

## Layout

```text
┌────────────────────────────────────────────────────────────┐
│ Matter > Folder > Document                                 │
├────────────────────────────────────────────────────────────┤
│ Document | Review | Version Control | Citations | Activity │
├───────────────────────────────┬────────────────────────────┤
│                               │                            │
│         DOCUMENT              │     AI FINDINGS            │
│         VIEWER                │                            │
│                               │     High                   │
│         Page 47               │     Liability cap ↑        │
│                               │                            │
│         highlighted text     │     Medium                 │
│                               │     Governing law          │
│                               │                            │
└───────────────────────────────┴────────────────────────────┘
```

### Tasks

- [ ] PDF rendering
- [ ] Page navigation
- [ ] Search
- [ ] Text selection
- [ ] Durable highlighting
- [ ] Finding navigation
- [ ] Version timeline
- [ ] Diff view
- [ ] Annotation panel
- [ ] Review panel
- [ ] Lazy loading
- [ ] Virtualized long documents

---

# Phase 34 — Review mode

```text
┌──────────────────────┬───────────────────────────┐
│ REVIEW               │ DOCUMENT                  │
│                      │                           │
│ 18 findings          │ Section 8.2               │
│                      │ Seller shall...           │
│ HIGH                 │                           │
│ Liability cap ↑      │ █████████████             │
│                      │                           │
│ MEDIUM               │                           │
│ Governing law        │                           │
│                      │                           │
│ LOW                  │                           │
│ Assignment           │                           │
└──────────────────────┴───────────────────────────┘
```

### Tasks

- [ ] Finding list
- [ ] Severity filters
- [ ] Evidence navigation
- [ ] Accept/dismiss
- [ ] Reviewer comments
- [ ] Finding status
- [ ] Review completion state
- [ ] Coverage indicator

---

# Part XIV — Scale Testing

# Phase 35 — Load test progressively

Do not jump directly to 1,000 documents.

### Milestones

```text
10 docs
 ↓
50 docs
 ↓
100 docs
 ↓
500 docs
 ↓
1,000 docs
 ↓
10,000 docs
```

### For each milestone measure

```text
Ingestion throughput
Indexing throughput
Storage growth
Queue latency
Retrieval latency
Review latency
LLM calls
Tokens
Cost
Cache hit rate
Failure rate
```

### Success criteria

Define target SLOs before optimization.

Example categories:

```text
Upload acknowledgement: seconds
Search retrieval: sub-second to low seconds
Review planning: seconds
Large review: bounded by configured parallelism
UI first render: fast and independent of full analysis
```

Do not hard-code a "100 documents in one minute" promise until the benchmark proves it for a defined corpus, model configuration and review type.

---

# Part XV — Implementation Order

# Phase 36 — Build sequence

## Milestone 1 — Core data layer

- [ ] PostgreSQL
- [ ] Tenant
- [ ] Client
- [ ] Matter
- [ ] Folder
- [ ] Document
- [ ] DocumentVersion
- [ ] AuditEvent

**Output:** stable document/version model.

---

## Milestone 2 — Storage + upload

- [ ] S3/MinIO
- [ ] Upload API
- [ ] Folder upload
- [ ] Manifest
- [ ] Checksums
- [ ] Idempotency

**Output:** safely ingest thousands of files without processing them yet.

---

## Milestone 3 — Async ingestion

- [ ] Workflow engine
- [ ] Queues
- [ ] Workers
- [ ] Retry
- [ ] Progress
- [ ] Failure isolation

**Output:** production-like ingestion pipeline.

---

## Milestone 4 — Canonical document model

- [ ] PDF parsing
- [ ] OCR fallback
- [ ] DOCX parsing
- [ ] Pages
- [ ] Sections
- [ ] Blocks
- [ ] Tables
- [ ] Anchors

**Output:** every document becomes structured data.

---

## Milestone 5 — Viewer

- [ ] PDF viewer
- [ ] Page navigation
- [ ] Search
- [ ] Stable highlights
- [ ] Version timeline

**Output:** usable document workspace.

---

## Milestone 6 — Retrieval

- [ ] BM25
- [ ] Vector
- [ ] Metadata
- [ ] Hybrid fusion
- [ ] Reranker
- [ ] Hierarchical retrieval

**Output:** high-quality evidence retrieval.

---

## Milestone 7 — Intelligence

- [ ] Document summaries
- [ ] Section summaries
- [ ] Entities
- [ ] Relationships
- [ ] Graph
- [ ] Intelligence cache

**Output:** compressed document knowledge layer.

---

## Milestone 8 — Review Engine

- [ ] Review planner
- [ ] Parallel map
- [ ] Reduce
- [ ] Verify
- [ ] Findings
- [ ] Evidence
- [ ] Synthesis

**Output:** multi-document review.

---

## Milestone 9 — Version intelligence

- [ ] Lexical diff
- [ ] Semantic diff
- [ ] Legal impact
- [ ] Finding comparison
- [ ] Version-aware embeddings/intelligence

**Output:** Git-like legal document version intelligence.

---

## Milestone 10 — Production hardening

- [ ] ACL
- [ ] Audit
- [ ] OTel
- [ ] Metrics
- [ ] Cost tracking
- [ ] Caching
- [ ] Rate limits
- [ ] Backpressure
- [ ] Graceful degradation
- [ ] Load testing

**Output:** production candidate.

---

# Part XVI — Suggested Repository Structure

```text
firmos/
├── apps/
│   ├── api/
│   ├── worker/
│   └── web/
│
├── services/
│   ├── documents/
│   ├── versions/
│   ├── ingestion/
│   ├── parsing/
│   ├── structure/
│   ├── indexing/
│   ├── retrieval/
│   ├── graph/
│   ├── review/
│   ├── findings/
│   ├── annotations/
│   ├── diff/
│   ├── audit/
│   └── permissions/
│
├── infrastructure/
│   ├── postgres/
│   ├── redis/
│   ├── object_storage/
│   ├── workflows/
│   └── observability/
│
├── evaluation/
│   ├── datasets/
│   ├── retrieval/
│   ├── review/
│   └── benchmarks/
│
├── notebooks/
│   └── production_architecture_simulator/
│
└── docs/
    ├── architecture/
    ├── api/
    ├── data_model/
    ├── runbooks/
    └── decisions/
```

---

# Part XVII — Critical Engineering Rules

## Rule 1 — Never overwrite document versions

```text
v7 remains v7.
```

---

## Rule 2 — Never use PDF coordinates as the canonical evidence anchor

Use:

```text
block + offsets + quote + hash
```

Coordinates are rendering metadata.

---

## Rule 3 — Never send the entire corpus to an LLM

Use:

```text
Hierarchy
→ retrieval
→ reranking
→ evidence
→ reasoning
```

---

## Rule 4 — Never perform all processing synchronously

Use:

```text
object storage
→ queue/workflow
→ bounded workers
```

---

## Rule 5 — Never rely on one retrieval channel

Use:

```text
Lexical
+
Vector
+
Metadata
+
Graph
+
Reranker
```

---

## Rule 6 — Never let retrieval bypass permissions

ACL filtering must happen before evidence reaches the model.

---

## Rule 7 — Every AI claim must have evidence

```text
Claim
→ Finding
→ Evidence
→ Exact source
```

---

## Rule 8 — Every expensive computation should be cacheable

Version/content-aware cache keys are preferred over TTL-only invalidation.

---

## Rule 9 — Every review must be traceable

```text
Review
→ Planner
→ Retrieval
→ Evidence
→ Finding
→ Verification
→ Answer
```

---

## Rule 10 — Optimize from benchmarks, not assumptions

Do not prematurely deploy:

```text
Kafka
Kubernetes
Neo4j
Elasticsearch
Qdrant
GPU clusters
10 microservices
```

Start with a small production-grade stack and introduce infrastructure when measured bottlenecks justify it.

---

# Part XVIII — Final Architecture

```text
                              USER
                                │
                                ▼
                          API GATEWAY
                                │
                          AUTH / ACL
                                │
                                ▼
                       QUERY / REVIEW API
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
          RETRIEVAL ENGINE               REVIEW ENGINE
                 │                             │
          QUERY PLANNER                  REVIEW PLANNER
                 │                             │
       ┌─────────┼─────────┐                   │
       ▼         ▼         ▼                   │
     BM25      Vector     Graph                │
       │         │         │                   │
       └─────────┼─────────┘                   │
                 ▼                             │
          Matter Retrieval                    │
                 ▼                             │
        Document Retrieval                    │
                 ▼                             │
          Chunk Retrieval                      │
                 ▼                             │
             Reranker                          │
                 │                             │
                 └──────────────┬──────────────┘
                                ▼
                         EVIDENCE STORE
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
                 Finding A   Finding B   Finding N
                    │           │           │
                    └───────────┼───────────┘
                                ▼
                           AGGREGATION
                                │
                           VERIFICATION
                                │
                         CONTEXT BUILDER
                                │
                                ▼
                               LLM
                                │
                                ▼
                         ANSWER + CITATIONS
```

### Async ingestion underneath

```text
Sources
   ↓
Object Storage
   ↓
Workflow / Queue
   ↓
Workers
   ├── Parse
   ├── OCR
   ├── Structure
   ├── Chunk
   ├── Embed
   ├── Entities
   ├── Summaries
   └── Graph
          ↓
        Indexes
```

### Shared infrastructure

```text
PostgreSQL
├── Metadata
├── Versions
├── Structure
├── Findings
├── Audit
└── Permissions

pgvector
└── Embeddings

Redis
├── Cache
└── Coordination

S3 / MinIO
└── Raw artifacts

Graph Store
└── Entities + relationships

OpenTelemetry
├── Traces
├── Metrics
├── Logs
├── Cost
└── Quality
```

---

# Part XIX — The Immediate Next 10 Tasks

Do **not** start by building GraphRAG or the final UI.

Start here:

1. [x] Freeze the domain model: `Tenant → Client → Matter → Folder → Document → Version`.
2. [x] Implement PostgreSQL migrations.
3. [x] Implement S3/MinIO object storage and deterministic storage keys.
4. [x] Implement folder upload + manifest creation.
5. [x] Implement asynchronous ingestion workflow with retries and per-file failure isolation.
6. [x] Implement PDF/DOCX parsing into `Page → Section → Block`.
7. [x] Implement durable `block_id + offsets + quote + hash` anchors.
8. [x] Implement hierarchical chunks with full context metadata.
9. [x] Implement BM25 + vector retrieval behind a common `RetrievalEngine` interface.
10. [x] Build a 100-document benchmark before adding more infrastructure.

> **Progress (2026-09-05):** P5.5 CE-protect frozen + **exact repair**. Eval: R@10 **.739**, Hit@10 **.926**, MRR **.805** (gate **PASS**). Exact Hit@10 **.996**. Next: matter/semantic query-type policies — not GraphRAG.

Then expand:

```text
100 docs
→ 500 docs
→ 1,000 docs
→ 10,000 docs
```

and only introduce infrastructure when benchmark data shows the current component is the bottleneck.

---

# Definition of "Production Ready"

The system should not be considered production-ready merely because it can answer questions over PDFs.

It should satisfy all of these:

- [ ] Documents and folders retain their original hierarchy.
- [ ] Every version is immutable.
- [ ] Previous versions remain searchable.
- [ ] Every chunk can reconstruct its matter/document context.
- [ ] AI findings point to exact source evidence.
- [ ] Highlights survive re-rendering/OCR changes.
- [ ] Retrieval combines lexical, semantic, metadata and graph signals.
- [ ] Retrieval is hierarchical.
- [ ] Large reviews execute with bounded parallelism.
- [ ] Review uses Map → Reduce → Verify.
- [ ] Failed documents do not fail the entire review.
- [ ] Expensive intelligence is cached by content/version.
- [ ] Permissions are enforced before model access.
- [ ] Every answer is traceable to evidence.
- [ ] Every review has an end-to-end trace.
- [ ] Retrieval and review quality are continuously benchmarked.
- [ ] 1,000-document / 100-page average workloads have been load tested.
- [ ] Cost and latency are measured rather than guessed.

---

# North Star

The final experience should feel like:

```text
Upload 1,000 documents
        ↓
System understands the hierarchy
        ↓
System creates structured document intelligence
        ↓
System indexes everything
        ↓
User asks a review question
        ↓
Planner decomposes the question
        ↓
BM25 + Vector + Graph retrieve in parallel
        ↓
Matter → Document → Section → Evidence
        ↓
Relevant documents are reviewed concurrently
        ↓
Findings are aggregated
        ↓
Every material claim is verified
        ↓
Answer is generated
        ↓
Every claim links back to exact evidence
        ↓
User can jump directly into the document
        ↓
Version history explains what changed and why
```

**The key product primitive is:**

```text
Finding
+
Evidence
+
Anchor
+
Version
+
Provenance
```

Build that correctly and the viewer, AI review, version control, citations, RAG, GraphRAG, institutional memory and audit trail become different views over the same underlying document intelligence system.
