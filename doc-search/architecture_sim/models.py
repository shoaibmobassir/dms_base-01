"""Canonical document intelligence models.

PDF is a representation of a Version — never the document itself.
Anchors bind to content (block + offsets + quote hash), not PDF coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    TABLE_CELL = "table_cell"
    FOOTNOTE = "footnote"
    HEADER = "header"
    FOOTER = "footer"
    LIST = "list"
    SIGNATURE = "signature"
    CITATION = "citation"


class AnnotationType(str, Enum):
    AI_HIGHLIGHT = "AI_HIGHLIGHT"
    LAWYER_HIGHLIGHT = "LAWYER_HIGHLIGHT"
    COMMENT = "COMMENT"
    ISSUE = "ISSUE"
    REDLINE = "REDLINE"
    CITATION = "CITATION"


class FindingStatus(str, Enum):
    OPEN = "open"
    REVIEWED = "reviewed"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"


class FindingSeverity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ContentAnchor:
    """Canonical location of evidence. Coordinates are optional render artifacts."""

    document_id: str
    version_id: str
    block_id: str
    start_offset: int
    end_offset: int
    quoted_text: str
    text_hash: str
    page: int | None = None
    section_id: str | None = None
    # Tertiary fallback only — never the source of truth
    bbox: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "version_id": self.version_id,
            "block_id": self.block_id,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "quoted_text": self.quoted_text,
            "text_hash": self.text_hash,
            "page": self.page,
            "section_id": self.section_id,
            "bbox": self.bbox,
        }


@dataclass
class Folder:
    folder_id: str
    name: str
    parent_folder_id: str | None
    path: str  # materialized: Client A/Project Ganges/Agreements


@dataclass
class Matter:
    matter_id: str
    name: str
    client_name: str
    summary: str = ""


@dataclass
class Document:
    document_id: str
    matter_id: str
    folder_id: str
    name: str
    document_type: str
    current_version_id: str | None = None
    folder_path: str = ""
    status: str = "active"


@dataclass
class DocumentVersion:
    version_id: str
    document_id: str
    version_number: int
    parent_version_id: str | None
    content_hash: str
    storage_uri: str
    mime_type: str
    page_count: int
    created_by: str
    change_summary: str
    is_current: bool
    raw_text: str
    # Intelligence (per-version — never overwrite prior versions)
    executive_summary: str = ""
    section_summaries: dict[str, str] = field(default_factory=dict)
    entities: list[str] = field(default_factory=list)
    clauses: list[str] = field(default_factory=list)


@dataclass
class DocumentBlock:
    block_id: str
    version_id: str
    page_number: int
    section_id: str
    block_type: BlockType
    sequence: int
    text: str
    text_hash: str
    start_offset: int
    end_offset: int


@dataclass
class Chunk:
    chunk_id: str
    version_id: str
    document_id: str
    matter_id: str
    folder_path: str
    page: int
    section_id: str
    section_title: str
    block_ids: list[str]
    text: str
    parent_chunk_id: str | None = None
    position: int = 0
    embedding: list[float] | None = None


@dataclass
class Evidence:
    version_id: str
    block_id: str
    page: int | None
    section: str | None
    quote: str
    offsets: tuple[int, int]
    text_hash: str
    chunk_id: str | None = None


@dataclass
class Finding:
    finding_id: str
    document_id: str
    version_id: str
    category: str
    severity: FindingSeverity
    title: str
    explanation: str
    confidence: float
    evidence: list[Evidence]
    status: FindingStatus = FindingStatus.OPEN
    created_by: str = "AI"
    comparison: dict[str, str] | None = None
    verified: bool = False


@dataclass
class Annotation:
    annotation_id: str
    version_id: str
    anchor: ContentAnchor
    annotation_type: AnnotationType
    author: str
    finding_id: str | None = None
    body: str = ""


@dataclass
class ReviewJob:
    job_id: str
    document_ids: list[str]
    features: list[str]
    status: str = "pending"
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceSpan:
    name: str
    started_ms: float
    ended_ms: float
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return self.ended_ms - self.started_ms
