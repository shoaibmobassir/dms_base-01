"""Storage abstractions — decouple retrieval from specific infrastructure.

This package defines Protocol implementations that wrap the current Postgres
infrastructure.  The retrieval engine imports only the Protocol; swapping
pgvector for Qdrant or Postgres FTS for Elasticsearch means changing only
the implementation in this package.

Current implementations:
  PgVectorStore  → pgvector ANN search
  PgGraphStore   → Postgres relationships table + SQL graph traversal
  PgSearchStore  → Postgres tsvector/GIN full-text search
"""
