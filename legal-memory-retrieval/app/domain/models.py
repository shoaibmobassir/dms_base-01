"""FirmOS canonical domain models.

Hierarchy (immutable IDs):
  Tenant → Client → Matter → Folder → Document → DocumentVersion
    → Blocks / Chunks / Findings / Evidence / Annotations

PDF is a representation of DocumentVersion — never the document itself.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    CLAUSE = "clause"
    TABLE = "table"
    TABLE_CELL = "table_cell"
    FOOTNOTE = "footnote"
    HEADER = "header"
    FOOTER = "footer"
    LIST = "list"
    SIGNATURE = "signature"
    CITATION = "citation"


class AnnotationType(str, Enum):
    AI_HIGHLIGHT = "ai_highlight"
    USER_HIGHLIGHT = "user_highlight"
    COMMENT = "comment"
    ISSUE = "issue"
    REDLINE = "redline"
    CITATION = "citation"


class FindingStatus(str, Enum):
    OPEN = "open"
    REVIEWED = "reviewed"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


class FindingSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class IngestItemStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    INDEXED = "indexed"
    SKIPPED = "skipped"
    FAILED = "failed"


class Tenant(BaseModel):
    tenant_id: str
    name: str


class User(BaseModel):
    """Maps to members in the current LEXOS schema."""

    user_id: str
    tenant_id: str = "harbour"
    name: str
    email: Optional[str] = None
    role: Optional[str] = None


class Client(BaseModel):
    client_id: str
    tenant_id: str = "harbour"
    name: str
    industry: Optional[str] = None


class Matter(BaseModel):
    matter_id: str
    tenant_id: str = "harbour"
    client_id: str
    matter_code: str
    title: str
    practice_area: Optional[str] = None


class Folder(BaseModel):
    folder_id: str
    tenant_id: str = "harbour"
    matter_id: Optional[str] = None
    project_id: Optional[str] = None
    name: str
    parent_folder_id: Optional[str] = None
    path: str = ""  # materialized: Client/Matter/Agreements


class Document(BaseModel):
    document_id: str
    tenant_id: str = "harbour"
    matter_id: str
    folder_id: Optional[str] = None
    folder_path: str = ""
    name: str
    document_type: str
    status: str = "active"
    current_version_id: Optional[str] = None
    mime_type: Optional[str] = None
    content_sha256: Optional[str] = None


class DocumentVersion(BaseModel):
    version_id: str
    document_id: str
    version_number: int
    parent_version_id: Optional[str] = None
    content_hash: str
    storage_uri: Optional[str] = None
    mime_type: str = "application/octet-stream"
    page_count: Optional[int] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    change_summary: Optional[str] = None
    is_current: bool = False
    version_status: str = "draft"
    version_label: Optional[str] = None


class DocumentBlock(BaseModel):
    block_id: str
    version_id: str
    document_id: str
    page_number: int = 1
    section_id: Optional[str] = None
    section_title: Optional[str] = None
    block_type: BlockType
    sequence: int
    text: str
    text_hash: str
    start_offset: int
    end_offset: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    chunk_id: str
    version_id: Optional[str] = None
    document_id: str
    matter_id: str
    folder_path: str = ""
    page: Optional[int] = None
    section_id: Optional[str] = None
    text: str
    parent_chunk_id: Optional[str] = None
    position: int = 0


class Entity(BaseModel):
    entity_id: str
    version_id: Optional[str] = None
    document_id: Optional[str] = None
    name: str
    entity_type: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class Relationship(BaseModel):
    source_id: str
    rel_type: str
    target_id: str


class Evidence(BaseModel):
    """Content-anchored evidence — never PDF coordinates as source of truth."""

    version_id: str
    block_id: str
    page: Optional[int] = None
    section: Optional[str] = None
    quote: str
    start_offset: int
    end_offset: int
    text_hash: str
    chunk_id: Optional[str] = None
    bbox: Optional[dict[str, float]] = None  # render artifact only


class Finding(BaseModel):
    finding_id: str
    document_id: str
    version_id: str
    category: str
    severity: FindingSeverity = FindingSeverity.MEDIUM
    title: str
    explanation: str
    confidence: float = 1.0
    evidence: list[Evidence] = Field(default_factory=list)
    status: FindingStatus = FindingStatus.OPEN
    created_by: str = "AI"
    comparison: Optional[dict[str, str]] = None


class Annotation(BaseModel):
    annotation_id: str
    document_id: str
    version_id: str
    block_id: Optional[str] = None
    annotation_type: AnnotationType
    author: Optional[str] = None
    finding_id: Optional[str] = None
    quoted_text: str
    text_hash: str
    start_offset: int = 0
    end_offset: int = 0
    page_number: int = 1
    content: Optional[str] = None


class ReviewTask(BaseModel):
    task_id: str
    job_id: str
    document_id: str
    feature: str
    status: str = "pending"
    error: Optional[str] = None


class ReviewJob(BaseModel):
    job_id: str
    matter_id: Optional[str] = None
    title: str
    features: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    status: str = "pending"
    findings: list[Finding] = Field(default_factory=list)


class AuditEvent(BaseModel):
    event_id: Optional[str] = None
    tenant_id: str = "harbour"
    actor_id: Optional[str] = None
    action: str
    target_type: str
    target_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class UploadBatchFile(BaseModel):
    relative_path: str
    storage_uri: str
    content_sha256: str
    size_bytes: int
    mime_type: str = "application/octet-stream"
    status: IngestItemStatus = IngestItemStatus.PENDING


class UploadBatch(BaseModel):
    batch_id: str
    tenant_id: str = "harbour"
    matter_id: str
    client_id: Optional[str] = None
    status: str = "pending"
    total_files: int = 0
    processed_files: int = 0
    failed_files: int = 0
    ingest_job_id: Optional[str] = None
    files: list[UploadBatchFile] = Field(default_factory=list)
    created_at: Optional[datetime] = None
