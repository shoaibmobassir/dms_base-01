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

from app.audit import events as audit
from app.auth.deps import resolve_member
from app.chat.agent import run_chat_agent, sse_done, sse_event
from app.chat.models import (
    ChatMessage,
    ChatMessageCreate,
    ChatSession,
    ChatSessionCreate,
    ChatSessionPatch,
    MessageRole,
    SessionStatus,
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
from app.api.acl import ACL_CLAUSE
from app.chat.tools.document_tools import build_doc_index_from_hits
from app.config import settings
from app.db.connection import connect
from app.llm.bedrock_client import bedrock_configured
from app.observability.request_id import current_request_id
from app.resilience.rate_limit import check_rate_limit
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
# Models and suggestions
# ---------------------------------------------------------------------------

def available_models() -> list[dict[str, Any]]:
    """Models the chat agent can actually call.

    The agent picks the provider by configuration (Bedrock → Gemini → Groq), so only
    the active provider's model is offered — a model id from another provider would
    be sent to the wrong API.
    """
    if bedrock_configured():
        provider, model = "bedrock", settings.bedrock_model
    elif settings.gemini_api_key:
        provider, model = "gemini", settings.gemini_model
    elif settings.groq_api_key:
        provider, model = "groq", settings.groq_model
    else:
        return []
    return [{"id": model, "label": model, "provider": provider, "default": True}]


def _resolve_model(requested: str | None) -> str | None:
    """Return ``requested`` if the active provider serves it, else the default model."""
    models = available_models()
    ids = {m["id"] for m in models}
    if requested in ids:
        return requested
    return models[0]["id"] if models else None


@router.get("/models")
def list_models() -> dict:
    models = available_models()
    return {"service": "chat", "models": models, "configured": bool(models)}


@router.get("/suggestions")
def chat_suggestions(member_id: str | None = Depends(resolve_member)) -> dict:
    """Starter questions drawn from the caller's most recent open matters."""
    sql = f"""
        SELECT m.matter_code, m.title, m.court
        FROM matters m
        LEFT JOIN permissions p ON p.matter_id = m.matter_id
        WHERE m.status = 'Open' AND {ACL_CLAUSE}
        ORDER BY m.opened_date DESC NULLS LAST, m.matter_id DESC
        LIMIT 3
    """
    with connect() as conn:
        rows = conn.execute(sql, {"member_id": member_id}).fetchall()
    suggestions: list[str] = []
    for r in rows:
        suggestions.append(f"Summarise the arguments filed so far in {r['title']}.")
        if r["court"]:
            suggestions.append(f"What relief has been sought before the {r['court']} in {r['matter_code']}?")
    return {"service": "chat", "suggestions": suggestions[:4]}


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def _owned_session(conn, session_id: str, member_id: str | None) -> ChatSession:
    """Return the session if the caller owns it; 404 otherwise (never leak existence).

    An anonymous caller (dev mode, no X-Member-Id) may only reach unowned sessions.
    """
    session = get_session(conn, session_id)
    # Deleting archives the row; to the owner it is gone.
    if not session or session.member_id != member_id or session.status != SessionStatus.active:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


@router.post("/sessions", response_model=ChatSession)
def create_chat_session(
    req: ChatSessionCreate,
    member_id: str | None = Depends(resolve_member),
):
    """Create a new chat session owned by the caller."""
    owned = req.model_copy(update={"member_id": member_id, "model": _resolve_model(req.model)})
    with connect() as conn:
        session = create_session(conn, owned)
    return session


@router.get("/sessions", response_model=list[ChatSession])
def list_chat_sessions(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    member_id: str | None = Depends(resolve_member),
):
    """List the caller's chat sessions, newest first."""
    if member_id is None:
        return []
    with connect() as conn:
        sessions = list_sessions(conn, member_id=member_id, limit=limit, offset=offset)
    return sessions


@router.get("/sessions/{session_id}")
def get_chat_session(session_id: str, member_id: str | None = Depends(resolve_member)):
    """Get a chat session with all its messages."""
    with connect() as conn:
        session = _owned_session(conn, session_id, member_id)
        messages = get_messages(conn, session_id)
    return {"session": session, "messages": messages}


@router.patch("/sessions/{session_id}", response_model=ChatSession)
def update_chat_session(
    session_id: str,
    patch: ChatSessionPatch,
    member_id: str | None = Depends(resolve_member),
):
    """Update session title, model, or status."""
    with connect() as conn:
        _owned_session(conn, session_id, member_id)
        updated = patch_session(conn, session_id, patch)
        if not updated:
            raise HTTPException(status_code=404, detail="Chat session not found")
    return updated


@router.delete("/sessions/{session_id}", status_code=204)
def delete_chat_session(session_id: str, member_id: str | None = Depends(resolve_member)):
    """Soft-delete a chat session."""
    with connect() as conn:
        _owned_session(conn, session_id, member_id)
        deleted = delete_session(conn, session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Chat session not found")


# ---------------------------------------------------------------------------
# SSE streaming message endpoint
# ---------------------------------------------------------------------------

@router.post("/sessions/{session_id}/messages")
def send_message(
    session_id: str,
    req: ChatMessageCreate,
    member_id: str | None = Depends(resolve_member),
):
    """
    Send a user message and receive an SSE-streamed assistant response.
    The response includes text deltas, tool events, citations, and [DONE].
    """
    check_rate_limit(
        f"chat:{member_id or 'anon'}",
        limit=settings.rate_limit_chat_per_minute,
        window_seconds=60.0,
    )
    with connect() as conn:
        session = _owned_session(conn, session_id, member_id)

        audit.record("chat.prompt", member_id=member_id, object_type="chat_session", object_id=session_id,
                     matter_id=session.matter_id, detail={"prompt": req.content})
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

    model = _resolve_model(session.model)

    def stream_response():
        """Generator that yields SSE events from the agent loop.

        If the client disconnects (the lawyer pressed Stop) the generator is closed
        at a ``yield``; the ``finally`` block still saves the partial answer.
        """
        # Emit session and message IDs
        yield sse_event("session_id", {
            "session_id": session_id,
            "assistant_message_id": assistant_msg.id,
        })

        full_text = ""
        all_events: list[dict[str, Any]] = []
        all_citations: list[dict[str, Any]] = []
        completed = False

        with connect() as stream_conn:
            try:
                gen = run_chat_agent(
                    stream_conn,
                    req.content,
                    history,
                    doc_index,
                    model,
                    member_id=session.member_id,
                    mode=req.mode.value if req.mode else None,
                    hit_count=len(doc_index),
                )
                try:
                    while True:
                        sse_chunk = next(gen)
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
                        yield sse_chunk
                except StopIteration as e:
                    result = e.value or {}
                    full_text = result.get("full_text", full_text)
                    all_events = result.get("events", all_events)
                    all_citations = result.get("citations", all_citations)
                    completed = True

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
            finally:
                if not completed:
                    all_events.append({"type": "stopped"})
                audit.record("chat.answer", member_id=member_id, object_type="chat_session", object_id=session_id,
                             matter_id=session.matter_id, detail={
                                 "completed": completed,
                                 "cited_documents": sorted({str(c.get("document_id")) for c in all_citations if c.get("document_id")}),
                                 "chars": len(full_text),
                             })
                # Update the reserved assistant message with final (or partial) content
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
def ask_sync(
    session_id: str,
    req: ChatMessageCreate,
    member_id: str | None = Depends(resolve_member),
):
    """
    Synchronous message endpoint — sends a message and returns the full
    assistant response as JSON (no streaming). Useful for testing.
    """
    from app.chat.agent import run_chat_agent_sync

    with connect() as conn:
        session = _owned_session(conn, session_id, member_id)

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
            _resolve_model(session.model),
            member_id=session.member_id,
            mode=req.mode.value if req.mode else None,
            hit_count=len(doc_index),
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
