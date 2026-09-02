"""Data models for the ingest pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DocumentRecord:
    """A normalized document ready for DB insertion."""
    document_id: str
    matter_id: str
    matter_code: str
    title: str
    document_type: str
    body: str
    source_uri: str
    content_sha256: str
    mime_type: str = "application/pdf"
    client_id: str | None = None
    author_name: str | None = None
    doc_date: str | None = None


@dataclass
class IngestItem:
    """Tracks one file through the pipeline."""
    source_uri: str
    content_sha256: str | None = None
    status: str = "pending"
    document_id: str | None = None
    error: str | None = None


@dataclass
class IngestJob:
    """Tracks a bulk ingest job."""
    job_id: str
    source_root: str
    status: str = "pending"
    total_items: int = 0
    indexed_items: int = 0
    failed_items: int = 0
    skipped_items: int = 0
    workers: int = 1
    items: list[IngestItem] = field(default_factory=list)


@dataclass
class MatterManifest:
    """A matter definition from the YAML manifest."""
    matter_id: str
    matter_code: str
    title: str
    client_id: str
    client_name: str
    practice_area: str = "Regulatory"
    matter_type: str = "Litigation"
    court: str | None = None
    jurisdiction: str | None = None
    theme_key: str | None = None
    legal_issues: list[str] = field(default_factory=list)
    file_patterns: list[str] = field(default_factory=list)
    document_type_map: dict[str, str] = field(default_factory=dict)
