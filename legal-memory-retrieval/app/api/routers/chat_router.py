"""
Chat router: REST API for chat sessions with SSE streaming message endpoint.
Integrates the multi-round tool-use agent loop, citation verification, and
chat persistence.

Clean-room independent implementation for FirmOS legal assistant chatbot.
"""

from __future__ import annotations

import uuid

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
    get_message,
    set_message_events,
    create_session,
    delete_session,
    get_messages,
    get_session,
    list_sessions,
    patch_session,
    update_assistant_message,
)
from app.chat.title_generator import generate_chat_title
from app.api.acl import ACL_CLAUSE, doc_acl
from app.chat.tools.document_tools import (
    DocIndex,
    add_documents_to_index,
    build_doc_index_from_hits,
    fetch_document_pages,
    paged_text,
)
from app.chat.tools.review_tools import EDIT_STATUSES, apply_accepted_edits, strip_page_markers
from pydantic import BaseModel
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


def _require_matter(conn, matter_id: str, member_id: str | None) -> None:
    """A conversation can only be limited to a matter the caller may see (404 otherwise)."""
    row = conn.execute(
        f"""
        SELECT 1 FROM matters m LEFT JOIN permissions p ON p.matter_id = m.matter_id
        WHERE m.matter_id = %(matter_id)s AND {ACL_CLAUSE}
        """,
        {"matter_id": matter_id, "member_id": member_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Matter not found")


def _matter_scope(conn, session: ChatSession) -> dict[str, str] | None:
    """The conversation's matter as the agent's tools need it, or None for firm-wide search."""
    if not session.matter_id:
        return None
    row = conn.execute(
        "SELECT matter_id, matter_code, title FROM matters WHERE matter_id = %s", (session.matter_id,)
    ).fetchone()
    return {"matter_id": row["matter_id"], "matter_code": row["matter_code"], "title": row["title"]} if row else None


def _search(conn, session: ChatSession, query: str) -> list[dict]:
    """Passages for this turn: inside the conversation's matter when it has one, else firm-wide."""
    if session.matter_id:
        from app.km.passages import scoped_passages

        return scoped_passages(conn, query, [session.matter_id], session.member_id, limit=14, per_doc=3)
    hits, _ = retrieve(conn, query, session.member_id)
    return hits


@router.post("/sessions", response_model=ChatSession)
def create_chat_session(
    req: ChatSessionCreate,
    member_id: str | None = Depends(resolve_member),
):
    """Create a new chat session owned by the caller."""
    owned = req.model_copy(update={"member_id": member_id, "model": _resolve_model(req.model)})
    with connect() as conn:
        if owned.matter_id:
            _require_matter(conn, owned.matter_id, member_id)
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
        if patch.matter_id:
            _require_matter(conn, patch.matter_id, member_id)
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

def _page_note(conn, files, member_id: str | None, history: list[ChatMessage] | None = None) -> str | None:
    """For the system prompt: the text of any page the lawyer dragged in, and the current headings of the documents
    in play (attached in this conversation or worked on in recent turns). None when there is neither."""
    from app.chat.context import carried_documents
    from app.chat.page_reference import outline_note, reference_note, resolve_references

    note = ""
    try:
        note += reference_note(resolve_references(conn, files, member_id))
    except Exception as exc:  # a failed lookup must not stop the answer
        logger.warning("[chat] page reference failed: %s", exc)
    try:
        ids = [f.document_id for f in files or [] if f.document_id]
        for msg in reversed(history or []):
            ids += [f.document_id for f in msg.files or [] if f.document_id]
        ids += [d["document_id"] for d in carried_documents(history or [])]
        note += outline_note(conn, ids, member_id)
    except Exception as exc:
        logger.warning("[chat] document outline failed: %s", exc)
    return note or None


def _with_attachments(conn, index: DocIndex, history: list[ChatMessage], member_id: str | None) -> DocIndex:
    """Documents attached anywhere in this conversation, and documents the Assistant worked on in
    recent turns, stay in scope ahead of search hits (a follow-up need not find them again)."""
    from app.chat.context import carried_documents

    ids: list[str] = []
    for msg in history:
        for f in msg.files or []:
            if f.document_id and f.document_id not in ids:
                ids.append(f.document_id)
    carried = [d["document_id"] for d in carried_documents(history) if d["document_id"] not in ids]
    ids += carried
    if not ids:
        return index
    rows = conn.execute(
        f"""
        SELECT d.document_id, d.title
        FROM documents d
        LEFT JOIN permissions p ON p.matter_id = d.matter_id
        WHERE d.document_id = ANY(%(ids)s) AND {ACL_CLAUSE} AND {doc_acl('d')}
        """,
        {"ids": ids, "member_id": member_id},
    ).fetchall()
    titles = {r["document_id"]: r["title"] for r in rows}
    index = add_documents_to_index(index, [(i, titles[i]) for i in carried if i in titles], attached=False)
    return add_documents_to_index(index, [(i, titles[i]) for i in ids if i in titles and i not in carried])


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
            hits = _search(conn, session, req.content)
        except Exception as exc:
            logger.warning(
                "[chat] retrieval failed: %s, request_id=%s",
                exc,
                current_request_id() or "-",
            )
            hits = []

        # Build document index from retrieval hits
        doc_index = _with_attachments(conn, build_doc_index_from_hits(hits), history, session.member_id)
        matter = _matter_scope(conn, session)
        page_note = _page_note(conn, req.files, session.member_id, history)

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
                    matter=matter,
                    page_note=page_note,
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
            hits = _search(conn, session, req.content)
        except Exception:
            hits = []

        doc_index = _with_attachments(conn, build_doc_index_from_hits(hits), history, session.member_id)

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
            matter=_matter_scope(conn, session),
            page_note=_page_note(conn, req.files, session.member_id, history),
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
        "timings": result.get("timings"),
    }


# ---------------------------------------------------------------------------
# Suggested edits: accept / reject, then export as tracked changes
# ---------------------------------------------------------------------------

class EditDecision(BaseModel):
    status: str


def _edit_groups(events: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [e for e in (events or []) if e.get("type") == "edit_proposals"]


def _apply_to_document(conn, group: dict[str, Any], edits: list[dict[str, Any]], member_id: str | None) -> dict | None:
    """Accepting writes the edits into the document as one clean version; each edit records the version it went into
    (``applied_version_id``) or why it could not be placed (``apply_error``)."""
    from app.documents.assistant_apply import apply_accepted
    from app.documents.editing import EditError

    try:
        out = apply_accepted(conn, group["document_id"], member_id, edits, group.get("instruction") or "")
    except EditError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)
    for edit in edits:
        if edit["id"] in out["applied"]:
            edit["applied_version_id"] = out["version_id"]
            edit["applied_version_number"] = out["version_number"]
            edit["applied_from_version_id"] = out["from_version_id"]
            edit.pop("apply_error", None)
        else:
            edit["apply_error"] = out["failed"].get(edit["id"], "it could not be placed")
    return out if out["version_id"] else None


@router.patch("/sessions/{session_id}/messages/{message_id}/edits/{edit_id}")
def decide_edit(
    session_id: str,
    message_id: str,
    edit_id: str,
    body: EditDecision,
    member_id: str | None = Depends(resolve_member),
):
    """Record the lawyer's decision on one suggested edit."""
    if body.status not in EDIT_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(EDIT_STATUSES)}")
    with connect() as conn:
        _owned_session(conn, session_id, member_id)
        msg = get_message(conn, session_id, message_id)
        if msg is None:
            raise HTTPException(status_code=404, detail="Message not found")
        events = list(msg.events or [])
        found = None
        found_group = None
        for group in _edit_groups(events):
            for edit in group.get("edits", []):
                if edit.get("id") == edit_id:
                    found, found_group = edit, group
        if found is None:
            raise HTTPException(status_code=404, detail="Edit not found")
        if found.get("applied_version_id") and body.status != "accepted":
            raise HTTPException(
                status_code=409,
                detail=f"This edit is already in the document (version {found.get('applied_version_number')}). "
                       "Restore an earlier version from History to undo it.")
        version = None
        if body.status == "accepted" and not found.get("applied_version_id") and not found_group.get("read_only"):
            version = _apply_to_document(conn, found_group, [found], member_id)
            if found.get("apply_error"):
                set_message_events(conn, message_id, events)
                raise HTTPException(status_code=409, detail=f"Could not apply this edit: {found['apply_error']}")
        found["status"] = body.status
        set_message_events(conn, message_id, events)
    audit.record("chat.edit_decision", member_id=member_id, object_type="chat_message", object_id=message_id,
                 detail={"edit_id": edit_id, "status": body.status, "version_id": (version or {}).get("version_id")})
    return found


class BulkEditDecision(BaseModel):
    status: str
    document_id: str


@router.patch("/sessions/{session_id}/messages/{message_id}/edits")
def decide_edits_bulk(
    session_id: str,
    message_id: str,
    body: BulkEditDecision,
    member_id: str | None = Depends(resolve_member),
):
    """Accept, reject or reset every edit to one document in this message (document-wide edits
    can number in the thousands)."""
    if body.status not in EDIT_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(EDIT_STATUSES)}")
    with connect() as conn:
        _owned_session(conn, session_id, member_id)
        msg = get_message(conn, session_id, message_id)
        if msg is None:
            raise HTTPException(status_code=404, detail="Message not found")
        events = list(msg.events or [])
        n = 0
        version = None
        failed: dict[str, str] = {}
        for group in _edit_groups(events):
            if group.get("document_id") != body.document_id:
                continue
            edits = group.get("edits", [])
            if body.status == "accepted" and not group.get("read_only"):
                todo = [e for e in edits if not e.get("applied_version_id")]
                if todo:
                    version = _apply_to_document(conn, group, todo, member_id) or version
                failed.update({e["id"]: e["apply_error"] for e in todo if e.get("apply_error")})
                for edit in edits:
                    if not edit.get("apply_error"):
                        edit["status"] = "accepted"
                        n += 1
                continue
            for edit in edits:
                if edit.get("applied_version_id"):
                    continue  # already in the document; History is where it is undone
                edit["status"] = body.status
                n += 1
        if not any(g.get("document_id") == body.document_id for g in _edit_groups(events)):
            raise HTTPException(status_code=404, detail="No edits for that document")
        set_message_events(conn, message_id, events)
        edits_out = [e for g in _edit_groups(events) if g.get("document_id") == body.document_id for e in g.get("edits", [])]
    audit.record("chat.edit_decision_bulk", member_id=member_id, object_type="chat_message", object_id=message_id,
                 detail={"document_id": body.document_id, "status": body.status, "count": n,
                         "version_id": (version or {}).get("version_id"), "failed": len(failed)})
    return {"updated": n, "status": body.status, "failed": failed, "edits": edits_out,
            "version_number": (version or {}).get("version_number")}


def _export_applied_redline(conn, document_id: str, accepted: list[dict], member_id: str | None) -> dict:
    """Edits already in the document: a Word redline of what they changed (before → after), for sharing. It does not
    touch the document."""
    from app.chat.tools.generation_tools import store_generated_bytes
    from app.documents import editing
    from app.editing.document import DOCX_MIME

    first = min(accepted, key=lambda e: e.get("applied_version_number") or 0)
    last = max(accepted, key=lambda e: e.get("applied_version_number") or 0)
    try:
        data, filename = editing.compare_docx(conn, document_id, member_id, first["applied_from_version_id"],
                                              last["applied_version_id"])
    except editing.EditError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail)
    stored = store_generated_bytes(data, filename.rsplit(".", 1)[0], "docx", DOCX_MIME, member_id)
    return {**stored, "applied": len(accepted), "tracked_in_original": False, "redline": True,
            "version_id": last["applied_version_id"], "version_label": None}


def _export_paragraph_edits(conn, document_id: str, groups: list[dict], member_id: str | None) -> dict:
    """Accepted paragraph-anchored edits → tracked changes in the ORIGINAL Word file + a new version."""
    from app.chat.tools.generation_tools import store_generated_bytes
    from app.documents import create_version
    from app.drafting.docx_redline_generator import DocxRedlineGenerator
    from app.drafting.docx_tracked import apply_tracked_changes
    from app.editing.document import DOCX_MIME, load_editable
    from app.editing.engine import apply_plan

    doc = load_editable(conn, document_id, member_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    stale = [g for g in groups if g.get("version_id") and doc.version_id and g["version_id"] != doc.version_id]
    if stale:
        raise HTTPException(status_code=409, detail="The document has changed since these edits were proposed; ask again")
    ops = [{"op": e.get("op", "replace"), "pid": int(e["pid"]), "text": e.get("proposed") or ""}
           for g in groups for e in g.get("edits", []) if e.get("status") == "accepted" and isinstance(e.get("pid"), int)]
    if not ops:
        raise HTTPException(status_code=409, detail="Accept at least one edit first")
    title = f"{doc.title} (suggested edits)"
    if doc.source == "docx" and doc.docx:
        data, stats = apply_tracked_changes(doc.docx, ops, author="Precentis Assistant")
        applied = stats["replaced"] + stats["replaced_whole"] + stats["deleted"] + stats["inserted"]
    else:
        data = DocxRedlineGenerator().create_tracked_diff_docx(
            "\n\n".join(doc.paragraphs), "\n\n".join(apply_plan(doc.paragraphs, ops)), title=title)
        applied = len(ops)
    stored = store_generated_bytes(data, title, "docx", DOCX_MIME, member_id)
    storage_uri = None
    if doc.source == "docx":
        # The new version keeps a clean Word file of its own (changes accepted, formatting kept), so the
        # next edit reads paragraphs that match this version.
        from app.drafting.docx_tracked import accept_all
        from app.storage.object_store import get_object_store

        storage_uri = get_object_store().put(f"assistant_edits/{document_id}/{uuid.uuid4().hex}.docx",
                                             accept_all(data), content_type=DOCX_MIME)
    version = create_version(
        document_id, "\n\n".join(apply_plan(doc.paragraphs, ops)), source="assistant_edit",
        version_status="developing", storage_uri=storage_uri,
        change_summary=f"{applied} Assistant edits accepted: {groups[0].get('instruction', '')[:120]}",
    )
    return {**stored, "applied": applied, "tracked_in_original": doc.source == "docx",
            "version_id": version.get("version_id"), "version_label": version.get("version_label")}


@router.post("/sessions/{session_id}/messages/{message_id}/edits/export")
def export_edits(
    session_id: str,
    message_id: str,
    document_id: str = Query(..., description="The edited document"),
    member_id: str | None = Depends(resolve_member),
):
    """Build a Word file showing the accepted edits as tracked changes."""
    from app.chat.tools.generation_tools import store_generated_bytes
    from app.drafting.docx_redline_generator import DocxRedlineGenerator

    with connect() as conn:
        _owned_session(conn, session_id, member_id)
        msg = get_message(conn, session_id, message_id)
        if msg is None:
            raise HTTPException(status_code=404, detail="Message not found")
        groups = [g for g in _edit_groups(msg.events) if g.get("document_id") == document_id]
        from app.documents.text_origin import source_info

        if source_info(conn, document_id)["format"] == "pdf":
            raise HTTPException(
                status_code=409,
                detail="This document is a PDF, which is read-only, so these suggestions are recommendations and "
                       "cannot be exported as tracked changes. Apply them in the Word original.")
        accepted = [e for g in groups for e in g.get("edits", []) if e.get("status") == "accepted"]
        if accepted and all(e.get("applied_version_id") for e in accepted):
            out = _export_applied_redline(conn, document_id, accepted, member_id)
            audit.record("chat.edit_export", member_id=member_id, object_type="chat_message", object_id=message_id,
                         detail={"document_id": document_id, "applied": out["applied"], "redline": True})
            return out
        if groups and all(g.get("anchoring") == "paragraph" for g in groups):
            out = _export_paragraph_edits(conn, document_id, groups, member_id)
            audit.record("chat.edit_export", member_id=member_id, object_type="chat_message", object_id=message_id,
                         detail={"document_id": document_id, "applied": out["applied"], "version_id": out["version_id"]})
            return out
        edits = [e for g in groups for e in g.get("edits", [])]
        if not any(e.get("status") == "accepted" for e in edits):
            raise HTTPException(status_code=409, detail="Accept at least one edit first")
        row = conn.execute("SELECT title FROM documents WHERE document_id = %s", (document_id,)).fetchone()
        pages = fetch_document_pages(conn, document_id)
    if not pages:
        raise HTTPException(status_code=404, detail="Document text not available")

    original = strip_page_markers(paged_text(pages))
    revised, applied = apply_accepted_edits(original, edits)
    if applied == 0:
        raise HTTPException(status_code=409, detail="None of the accepted edits could be placed in the document")
    title = f"{(row or {}).get('title') or document_id} (suggested edits)"
    data = DocxRedlineGenerator().create_tracked_diff_docx(original, revised, title=title)
    stored = store_generated_bytes(
        data, title, "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        member_id,
    )
    audit.record("chat.edit_export", member_id=member_id, object_type="chat_message", object_id=message_id,
                 detail={"document_id": document_id, "applied": applied})
    return {**stored, "applied": applied}
