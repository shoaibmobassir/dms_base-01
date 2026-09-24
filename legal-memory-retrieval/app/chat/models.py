"""
Chat models: Pydantic schemas for chat sessions, messages, and events.
Clean-room independent implementation for FirmOS legal assistant chatbot.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MessageRole(str, Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class SessionStatus(str, Enum):
    active = "active"
    archived = "archived"


# ---------------------------------------------------------------------------
# Chat session
# ---------------------------------------------------------------------------

class ChatSessionCreate(BaseModel):
    title: Optional[str] = None
    matter_id: Optional[str] = None
    model: Optional[str] = None
    member_id: Optional[str] = None


class ChatSession(BaseModel):
    id: str
    title: Optional[str] = None
    matter_id: Optional[str] = None
    model: Optional[str] = None
    member_id: Optional[str] = None
    status: SessionStatus = SessionStatus.active
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatSessionPatch(BaseModel):
    title: Optional[str] = None
    model: Optional[str] = None
    status: Optional[SessionStatus] = None


# ---------------------------------------------------------------------------
# Chat messages
# ---------------------------------------------------------------------------

class FileAttachment(BaseModel):
    """A document attached to a user message."""
    filename: str
    document_id: Optional[str] = None
    content_type: Optional[str] = None


class WorkMode(str, Enum):
    """How the next answer should be shaped. Chosen by the lawyer, not inferred."""

    reason = "reason"
    research = "research"
    review = "review"
    cite = "cite"


class ChatMessageCreate(BaseModel):
    content: str
    role: MessageRole = MessageRole.user
    files: Optional[list[FileAttachment]] = None
    mode: Optional[WorkMode] = None


class ChatMessage(BaseModel):
    id: str
    session_id: str
    role: MessageRole
    content: str
    files: Optional[list[FileAttachment]] = None
    events: Optional[list[dict[str, Any]]] = None
    citations: Optional[list[dict[str, Any]]] = None
    model: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# SSE event types streamed to the client
# ---------------------------------------------------------------------------

class SSEEventType(str, Enum):
    session_id = "session_id"
    text_delta = "text_delta"
    reasoning = "reasoning"
    citation_data = "citation_data"
    doc_read = "doc_read"
    doc_find = "doc_find"
    doc_created = "doc_created"
    ask_inputs = "ask_inputs"
    chat_title = "chat_title"
    error = "error"
    done = "done"


# ---------------------------------------------------------------------------
# Source document model (structured citation reference)
# ---------------------------------------------------------------------------

class SourceDocumentAction(BaseModel):
    type: str  # "download" | "link"
    url: str
    label: str
    title: Optional[str] = None


class SourceDocumentQuote(BaseModel):
    quote: str
    verification: Optional[dict[str, Any]] = None
    target: dict[str, Any] = Field(default_factory=dict)  # {page, sheet, cell}


class SourceDocument(BaseModel):
    document_id: str
    title: str
    type: str  # "pdf" | "docx" | "spreadsheet" | "case" | "legislation"
    metadata: list[dict[str, str]] = Field(default_factory=list)
    actions: list[SourceDocumentAction] = Field(default_factory=list)
    quotes: list[SourceDocumentQuote] = Field(default_factory=list)
    version_id: Optional[str] = None
    version_number: Optional[int] = None
