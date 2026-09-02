"""Production ingest pipeline for legal documents.

This package provides:
- PDF/text/JSONL extractors
- Metadata normalizer (filename → document_type, matter mapping)
- Chunker (reuses app.db.chunking)
- Batch writer (COPY/executemany in batches of 500)
- Job tracking (ingest_jobs + ingest_items tables)
- CLI entry point (python -m app.ingest run)
"""
