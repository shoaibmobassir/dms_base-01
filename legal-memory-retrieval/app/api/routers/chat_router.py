"""
Chat router: REST API for chat sessions with SSE streaming message endpoint.
Integrates the multi-round tool-use agent loop, citation verification, and
chat persistence.

Clean-room independent implementation for FirmOS legal assistant chatbot.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.chat.agent import run_chat_agent, sse_done, sse_event
from app.chat.models import (
    ChatMessage,
    ChatMessageCreate,
    ChatSession,
    ChatSessionCreate,
    ChatSessionPatch,
    MessageRole,
)
from app.chat.store import (
    append_message,
    create_session,
    delete_session,
    get_messages,
    get_session,
    list_sessions,
    patch_session,
    update_assistant_message,
)
from app.chat.title_generator import generate_chat_title
from app.chat.tools.document_tools import build_doc_index_from_hits
from app.db.connection import connect
from app.observability.request_id import current_request_id
from app.retrieval.engine import retrieve

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health")
def chat_health() -> dict:
    return {"status": "ok", "service": "chat"}


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

@router.post("/sessions", response_model=ChatSession)
def create_chat_session(req: ChatSessionCreate):
    """Create a new chat session."""
    with connect() as conn:
        session = create_session(conn, req)
    return session


@router.get("/sessions", response_model=list[ChatSession])
def list_chat_sessions(
    member_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List chat sessions, optionally filtered by member_id."""
    with connect() as conn:
        sessions = list_sessions(conn, member_id=member_id, limit=limit, offset=offset)
    return sessions


@router.get("/sessions/{session_id}")
def get_chat_session(session_id: str):
    """Get a chat session with all its messages."""
    with connect() as conn:
        session = get_session(conn, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")
        messages = get_messages(conn, session_id)
    return {"session": session, "messages": messages}


@router.patch("/sessions/{session_id}", response_model=ChatSession)
def update_chat_session(session_id: str, patch: ChatSessionPatch):
    """Update session title, model, or status."""
    with connect() as conn:
        updated = patch_session(conn, session_id, patch)
        if not updated:
            raise HTTPException(status_code=404, detail="Chat session not found")
    return updated


@router.delete("/sessions/{session_id}", status_code=204)
def delete_chat_session(session_id: str):
    """Soft-delete a chat session."""
    with connect() as conn:
        deleted = delete_session(conn, session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Chat session not found")


# ---------------------------------------------------------------------------
# SSE streaming message endpoint
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/messages")
def send_message(session_id: str, req: ChatMessageCreate):
    """
    Send a user message and receive an SSE-streamed assistant response.
    The response includes text deltas, tool events, citations, and [DONE].
    """
    with connect() as conn:
        session = get_session(conn, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")

        # Persist the user message
        user_msg = append_message(
            conn,
            session_id,
            role=MessageRole.user,
            content=req.content,
            files=req.files,
        )

        # Load conversation history
        history = get_messages(conn, session_id)

        # Retrieve relevant documents for the query
        try:
            hits, _ = retrieve(conn, req.content, session.member_id)
        except Exception as exc:
            logger.warning(
                "[chat] retrieval failed: %s, request_id=%s",
                exc,
                current_request_id() or "-",
            )
            hits = []

        # Build document index from retrieval hits
        doc_index = build_doc_index_from_hits(hits)

        # Reserve assistant message ID
        assistant_msg = append_message(
            conn,
            session_id,
            role=MessageRole.assistant,
            content="",  # Will be updated after streaming
            model=session.model,
        )

    def stream_response():
        """Generator that yields SSE events from the agent loop."""
        # Emit session and message IDs
        yield sse_event("session_id", {
            "session_id": session_id,
            "assistant_message_id": assistant_msg.id,
        })

        full_text = ""
        all_events = []
        all_citations = []

        with connect() as stream_conn:
            gen = run_chat_agent(
                stream_conn,
                req.content,
                history,
                doc_index,
                session.model,
                member_id=session.member_id,
            )

            try:
                while True:
                    sse_chunk = next(gen)
                    yield sse_chunk

                    # Parse SSE to collect full text
                    if sse_chunk.startswith("data: "):
                        data_str = sse_chunk[6:].strip()
                        if data_str and data_str != "[DONE]":
                            try:
                                data = json.loads(data_str)
                                if data.get("type") == "text_delta":
                                    full_text += data.get("text", "")
                                elif data.get("type") == "citation_data":
                                    all_citations.append(data)
                                elif data.get("type") not in ("session_id", "done"):
                                    all_events.append(data)
                            except json.JSONDecodeError:
                                pass

            except StopIteration as e:
                result = e.value or {}
                full_text = result.get("full_text", full_text)
                all_events = result.get("events", all_events)
                all_citations = result.get("citations", all_citations)

            # Auto-generate title if this is the first user message
            if not session.title:
                try:
                    title = generate_chat_title(req.content)
                    patch_session(stream_conn, session_id, ChatSessionPatch(title=title))
                    yield sse_event("chat_title", {
                        "session_id": session_id,
                        "title": title,
                    })
                except Exception as exc:
                    logger.warning("[chat] title generation failed: %s", exc)

            # Update the reserved assistant message with final content
            try:
                update_assistant_message(
                    stream_conn,
                    assistant_msg.id,
                    content=full_text,
                    events=all_events if all_events else None,
                    citations=all_citations if all_citations else None,
                )
            except Exception as exc:
                logger.error("[chat] failed to save assistant message: %s", exc)

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Non-streaming convenience endpoint (for testing / simple clients)
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/ask")
def ask_sync(session_id: str, req: ChatMessageCreate):
    """
    Synchronous message endpoint — sends a message and returns the full
    assistant response as JSON (no streaming). Useful for testing.
    """
    from app.chat.agent import run_chat_agent_sync

    with connect() as conn:
        session = get_session(conn, session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found")

        # Persist user message
        append_message(conn, session_id, role=MessageRole.user, content=req.content, files=req.files)
        history = get_messages(conn, session_id)

        # Retrieve documents
        try:
            hits, _ = retrieve(conn, req.content, session.member_id)
        except Exception:
            hits = []

        doc_index = build_doc_index_from_hits(hits)

        # Run agent synchronously
        result = run_chat_agent_sync(
            conn,
            req.content,
            history,
            doc_index,
            session.model,
            member_id=session.member_id,
        )

        # Save assistant response
        assistant_msg = append_message(
            conn,
            session_id,
            role=MessageRole.assistant,
            content=result.get("full_text", ""),
            events=result.get("events"),
            citations=result.get("citations"),
            model=session.model,
        )

        # Auto-generate title
        if not session.title:
            try:
                title = generate_chat_title(req.content)
                patch_session(conn, session_id, ChatSessionPatch(title=title))
            except Exception:
                pass

    return {
        "message": assistant_msg.model_dump(),
        "events": result.get("events", []),
        "citations": result.get("citations", []),
    }
