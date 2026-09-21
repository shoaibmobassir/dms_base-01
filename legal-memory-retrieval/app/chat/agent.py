"""
Chat agent: Multi-round tool-use agent loop with SSE streaming.
Orchestrates the LLM, tool calls, citation extraction, and verification.

Clean-room independent implementation for FirmOS legal assistant chatbot.
"""

from __future__ import annotations

import json
import logging
import random
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Generator

import httpx

from app.chat.citations import (
    ParsedCitation,
    extract_citations_text,
    parse_citations,
    parse_partial_citations,
)
from app.chat.models import (
    ChatMessage,
    MessageRole,
    SSEEventType,
)
from app.chat.spotlight import generate_nonce, spotlight
from app.chat.system_prompt import SYSTEM_PROMPT
from app.chat.tools.document_tools import (
    DocIndex,
    DocStore,
    build_doc_availability,
    build_doc_index_from_hits,
    fetch_documents,
    find_in_document,
    read_document,
    search_firm_records,
)
from app.chat.tools.generation_tools import generate_docx, generate_excel
from app.chat.tools.schema import ALL_TOOLS
from app.chat.verify_citations import verify_document_citation
from app.config import settings
from app.db.connection import connect
from app.observability.metrics import (
    CHAT_CITATION_RESULTS,
    CHAT_TOOL_CALLS,
    CHAT_TOOL_TIMEOUTS,
    CHAT_TURNS,
)
from app.observability.request_id import current_request_id

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 10
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_DB_TOOLS = frozenset({
    "read_document",
    "search_firm_records",
    "fetch_documents",
    "find_in_document",
})
_KNOWN_TOOLS = _DB_TOOLS | frozenset({
    "generate_docx",
    "generate_excel",
    "ask_inputs",
})


class _DeadlineExceeded:
    """Sentinel: the tool did not finish before the wall clock."""


DEADLINE_EXCEEDED = _DeadlineExceeded()


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

def sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format a single SSE event string."""
    payload = json.dumps({"type": event_type, **data}, default=str)
    return f"data: {payload}\n\n"


def sse_done() -> str:
    return "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def dispatch_tool_call(
    name: str,
    arguments: dict[str, Any],
    doc_index: DocIndex,
    doc_store: DocStore,
    conn: Any,
    nonce: str,
    member_id: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Execute a single tool call and return (result, events).
    Events are SSE-serializable dicts emitted to the client.
    """
    events: list[dict[str, Any]] = []

    if name == "read_document":
        result = read_document(
            arguments.get("doc_id", ""),
            doc_index, doc_store, conn, nonce,
            member_id=member_id,
        )
        if "event" in result:
            events.append(result.pop("event"))
        return result, events

    elif name == "search_firm_records":
        result = search_firm_records(
            arguments.get("query", ""),
            doc_index,
            conn,
            member_id=member_id,
            k=arguments.get("k", 8),
        )
        if "event" in result:
            events.append(result.pop("event"))
        return result, events

    elif name == "fetch_documents":
        result = fetch_documents(
            arguments.get("doc_ids", []),
            doc_index, doc_store, conn, nonce,
            member_id=member_id,
        )
        events.extend(result.pop("events", []))
        return result, events

    elif name == "find_in_document":
        result = find_in_document(
            arguments.get("doc_id", ""),
            arguments.get("query", ""),
            doc_index, doc_store, conn,
            max_results=arguments.get("max_results", 20),
            context_chars=arguments.get("context_chars", 80),
            member_id=member_id,
        )
        if "event" in result:
            events.append(result.pop("event"))
        return result, events

    elif name == "generate_docx":
        result = generate_docx(
            arguments.get("title", "Document"),
            arguments.get("sections", []),
        )
        if "event" in result:
            events.append(result.pop("event"))
        return result, events

    elif name == "generate_excel":
        result = generate_excel(
            arguments.get("title", "Workbook"),
            arguments.get("sheets", []),
        )
        if "event" in result:
            events.append(result.pop("event"))
        return result, events

    elif name == "ask_inputs":
        items = arguments.get("items", [])
        event = {"type": "ask_inputs", "items": items}
        events.append(event)
        return {"status": "waiting_for_user_input", "items": items}, events

    else:
        return {"error": f"Unknown tool: {name}"}, events


def tool_deadline_seconds(name: str) -> float:
    """Wall-clock bound for one tool. Find-in-document is shorter than retrieve."""
    if name == "find_in_document":
        return settings.chat_find_timeout_seconds
    return settings.chat_tool_timeout_seconds


def tool_metric_label(name: str) -> str:
    return name if name in _KNOWN_TOOLS else "unknown"


def run_with_deadline(fn, timeout: float, *args, **kwargs):
    """Run fn on a worker thread and stop waiting after timeout seconds.

    shutdown(wait=False) so a hung tool does not block the SSE response.
    The worker is not cancelled; callers must not share mutable DB state with it.
    """
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chat-tool")
    future = executor.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeoutError:
        return DEADLINE_EXCEEDED
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _invoke_tool(
    name: str,
    arguments: dict[str, Any],
    doc_index: DocIndex,
    doc_store: DocStore,
    nonce: str,
    member_id: str | None,
    timeout: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run a tool on a connection this worker created, so the request conn stays put."""
    if name not in _DB_TOOLS:
        return dispatch_tool_call(
            name, arguments, doc_index, doc_store, None, nonce, member_id=member_id,
        )
    with connect() as tool_conn:
        try:
            tool_conn.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                (str(int(timeout * 1000)),),
            ).fetchone()
        except Exception:
            logger.debug("statement_timeout not set for tool %s", name)
        return dispatch_tool_call(
            name, arguments, doc_index, doc_store, tool_conn, nonce, member_id=member_id,
        )


def dispatch_tool_call_bounded(
    name: str,
    arguments: dict[str, Any],
    doc_index: DocIndex,
    doc_store: DocStore,
    nonce: str,
    member_id: str | None = None,
    timeout: float | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    """Execute a tool with a wall-clock deadline. Does not retry the tool."""
    bound = tool_deadline_seconds(name) if timeout is None else timeout
    label = tool_metric_label(name)
    CHAT_TOOL_CALLS.labels(tool=label).inc()
    outcome = run_with_deadline(
        _invoke_tool,
        bound,
        name,
        arguments,
        doc_index,
        doc_store,
        nonce,
        member_id,
        bound,
    )
    if outcome is DEADLINE_EXCEEDED:
        CHAT_TOOL_TIMEOUTS.labels(tool=label).inc()
        logger.warning(
            "[chat/agent] tool %s timed out after %.0fs, request_id=%s",
            name,
            bound,
            current_request_id() or "-",
        )
        return (
            {"error": f"Tool {name} timed out after {bound:.0f}s", "timed_out": True},
            [],
            True,
        )
    result, events = outcome
    return result, events, False


def select_history_messages(
    history: list[ChatMessage],
    user_message: str,
    max_pairs: int | None = None,
) -> list[ChatMessage]:
    """Drop the duplicated current user turn and keep the last N pairs."""
    pairs = settings.chat_history_max_pairs if max_pairs is None else max_pairs
    kept: list[ChatMessage] = []
    for msg in history:
        if msg.role == MessageRole.system:
            continue
        if msg.role == MessageRole.assistant and not (msg.content or "").strip():
            continue
        kept.append(msg)
    if (
        user_message
        and kept
        and kept[-1].role == MessageRole.user
        and kept[-1].content == user_message
    ):
        kept = kept[:-1]
    limit = max(0, pairs) * 2
    if len(kept) > limit:
        kept = kept[-limit:]
    return kept


def citation_result_label(citation: dict[str, Any], had_source: bool) -> str:
    if not had_source:
        return "no_source"
    if citation.get("verified") is True:
        return "verified"
    return "unverified"


# ---------------------------------------------------------------------------
# Build LLM messages from chat history + context
# ---------------------------------------------------------------------------

def build_llm_messages(
    history: list[ChatMessage],
    user_message: str,
    doc_index: DocIndex,
    nonce: str,
    max_pairs: int | None = None,
) -> list[dict[str, Any]]:
    """Build the LLM message array: system + windowed history + current user."""
    doc_availability = build_doc_availability(doc_index)
    doc_list_str = "\n".join(
        f"- {d['doc_id']}: {d['filename']}" for d in doc_availability
    )

    system_content = SYSTEM_PROMPT
    if doc_availability:
        system_content += f"\n\nAVAILABLE DOCUMENTS:\n{doc_list_str}"

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_content},
    ]

    for msg in select_history_messages(history, user_message, max_pairs=max_pairs):
        messages.append({
            "role": msg.role.value,
            "content": msg.content,
        })

    messages.append({
        "role": "user",
        "content": spotlight(user_message, nonce) if user_message else "",
    })

    return messages


# ---------------------------------------------------------------------------
# LLM call abstraction
# ---------------------------------------------------------------------------

def _http_post(url: str, **kwargs: Any) -> httpx.Response:
    """POST once, and once more on 429/5xx. Does not retry tool calls."""
    timeout = kwargs.pop("timeout", 120.0)
    resp = httpx.post(url, timeout=timeout, **kwargs)
    if resp.status_code in _RETRYABLE_STATUS:
        time.sleep(0.2 + random.random() * 0.4)
        resp = httpx.post(url, timeout=timeout, **kwargs)
    resp.raise_for_status()
    return resp


def _call_llm(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str | None = None,
) -> dict[str, Any]:
    """
    Call the LLM with tool support. Returns the raw response dict.
    Supports Gemini (via google-genai) and falls back to Groq.
    """
    # Try Gemini first
    if settings.gemini_api_key:
        return _call_gemini(messages, tools, model)
    # Fallback to Groq
    if settings.groq_api_key:
        return _call_groq(messages, tools, model)
    # No API key — return a basic response
    return {
        "content": "I apologise, but I cannot process your request at the moment. No LLM API key is configured.",
        "tool_calls": [],
    }


def _call_gemini(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str | None = None,
) -> dict[str, Any]:
    """Call Gemini via the REST API with function-calling support."""
    api_key = settings.gemini_api_key
    model_id = model or settings.gemini_model or "gemini-1.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"

    # Convert messages to Gemini format
    contents = []
    system_instruction = None
    for msg in messages:
        role = msg["role"]
        if role == "system":
            system_instruction = msg["content"]
            continue
        gemini_role = "user" if role == "user" else "model"
        parts = [{"text": msg["content"]}]
        # Handle tool results
        if role == "tool":
            parts = [{"functionResponse": {"name": msg.get("name", ""), "response": {"result": msg["content"]}}}]
            gemini_role = "user"
        contents.append({"role": gemini_role, "parts": parts})

    # Build request
    body: dict[str, Any] = {"contents": contents}
    if system_instruction:
        body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
    if tools:
        gemini_tools = []
        for tool in tools:
            func = tool.get("function", {})
            gemini_tools.append({
                "name": func.get("name"),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {}),
            })
        body["tools"] = [{"functionDeclarations": gemini_tools}]

    body["generationConfig"] = {
        "temperature": 0.3,
        "maxOutputTokens": 8192,
    }

    resp = _http_post(url, json=body, timeout=120.0)
    data = resp.json()

    # Parse response
    candidates = data.get("candidates", [])
    if not candidates:
        return {"content": "", "tool_calls": []}

    parts = candidates[0].get("content", {}).get("parts", [])
    content_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for part in parts:
        if "text" in part:
            content_parts.append(part["text"])
        elif "functionCall" in part:
            fc = part["functionCall"]
            tool_calls.append({
                "id": str(uuid.uuid4()),
                "type": "function",
                "function": {
                    "name": fc.get("name", ""),
                    "arguments": json.dumps(fc.get("args", {})),
                },
            })

    return {
        "content": "\n".join(content_parts),
        "tool_calls": tool_calls,
    }


def _call_groq(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str | None = None,
) -> dict[str, Any]:
    """Call Groq with tool support."""
    api_key = settings.groq_api_key
    model_id = model or settings.groq_model or "llama3-70b-8192"

    body: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 8192,
    }
    if tools:
        body["tools"] = tools

    resp = _http_post(
        "https://api.groq.com/openai/v1/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=120.0,
    )
    data = resp.json()

    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})
    return {
        "content": message.get("content", ""),
        "tool_calls": message.get("tool_calls", []),
    }


# ---------------------------------------------------------------------------
# Main agent loop (streaming generator)
# ---------------------------------------------------------------------------

def run_chat_agent(
    conn,
    user_message: str,
    history: list[ChatMessage],
    doc_index: DocIndex,
    model: str | None = None,
    member_id: str | None = None,
) -> Generator[str, None, dict[str, Any]]:
    """
    Execute the multi-round tool-use agent loop.
    Yields SSE event strings. Returns the final result dict
    with {full_text, events, citations}.

    Tool calls open their own database connection so a timeout cannot race
    the request connection. `conn` is accepted for caller compatibility.
    """
    if conn is None:
        logger.debug("[chat/agent] no request connection, request_id pending")
    nonce = generate_nonce()
    doc_store: DocStore = {}
    all_events: list[dict[str, Any]] = []
    messages = build_llm_messages(history, user_message, doc_index, nonce)
    tools = ALL_TOOLS
    request_id = current_request_id() or "-"
    tools_paused = False

    full_text = ""

    for round_num in range(MAX_TOOL_ROUNDS):
        logger.info(
            "[chat/agent] round %d, messages=%d, request_id=%s",
            round_num + 1,
            len(messages),
            request_id,
        )

        try:
            response = _call_llm(messages, tools, model)
        except Exception as exc:
            logger.error(
                "[chat/agent] LLM call failed: %s, request_id=%s",
                exc,
                request_id,
            )
            CHAT_TURNS.labels(outcome="llm_error").inc()
            yield sse_event("error", {"message": "Failed to generate response. Please try again."})
            yield sse_done()
            return {"full_text": "", "events": all_events, "citations": []}

        content = response.get("content", "")
        tool_calls = response.get("tool_calls", [])

        # Stream text content
        if content:
            full_text += content
            # Check for partial citations during stream
            clean_text = extract_citations_text(content)
            if clean_text:
                yield sse_event("text_delta", {"text": clean_text})

        # If no tool calls, we're done
        if not tool_calls:
            break

        # Process tool calls
        messages.append({
            "role": "assistant",
            "content": content or "",
            "tool_calls": tool_calls,
        })

        for tc in tool_calls:
            func = tc.get("function", {})
            tool_name = func.get("name", "")
            try:
                args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}

            logger.info(
                "[chat/agent] tool call: %s(%s), request_id=%s",
                tool_name,
                list(args.keys()),
                request_id,
            )

            if tools_paused:
                result, events, timed_out = (
                    {"error": "Tool execution paused after a timeout"},
                    [],
                    False,
                )
            else:
                result, events, timed_out = dispatch_tool_call_bounded(
                    tool_name,
                    args,
                    doc_index,
                    doc_store,
                    nonce,
                    member_id=member_id,
                )
                if timed_out:
                    tools_paused = True

            # Stream tool events
            for event in events:
                all_events.append(event)
                yield sse_event(event.get("type", "tool_event"), event)

            # If ask_inputs was called, stop the loop
            if tool_name == "ask_inputs" and not result.get("error"):
                CHAT_TURNS.labels(outcome="waiting_input").inc()
                yield sse_done()
                return {
                    "full_text": full_text,
                    "events": all_events,
                    "citations": [],
                    "waiting_for_input": True,
                }

            # Add tool result to messages
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", str(uuid.uuid4())),
                "name": tool_name,
                "content": json.dumps(result, default=str),
            })

    # Parse and verify citations
    citations = parse_citations(full_text)
    verified_citations: list[dict[str, Any]] = []
    for cit in citations:
        cit_dict = cit.to_dict()
        doc_id = cit_dict.get("doc_id", "")
        source_text = doc_store.get(doc_id, "")
        had_source = bool(source_text)
        if had_source:
            verified = verify_document_citation(cit_dict, source_text)
        else:
            verified = cit_dict
        CHAT_CITATION_RESULTS.labels(
            result=citation_result_label(verified, had_source),
        ).inc()
        verified_citations.append(verified)
        # Stream citation data
        yield sse_event("citation_data", verified)

    # Clean response text (strip CITATIONS block)
    clean_text = extract_citations_text(full_text)

    CHAT_TURNS.labels(outcome="completed").inc()
    yield sse_done()
    return {
        "full_text": clean_text,
        "events": all_events,
        "citations": verified_citations,
    }


# ---------------------------------------------------------------------------
# Synchronous wrapper for non-streaming use
# ---------------------------------------------------------------------------

def run_chat_agent_sync(
    conn,
    user_message: str,
    history: list[ChatMessage],
    doc_index: DocIndex,
    model: str | None = None,
    member_id: str | None = None,
) -> dict[str, Any]:
    """
    Run the agent loop synchronously, collecting all SSE events.
    Returns the final result dict with full_text, events, citations,
    and the collected sse_events list.
    """
    sse_events: list[str] = []
    gen = run_chat_agent(
        conn, user_message, history, doc_index, model, member_id=member_id,
    )

    result = {"full_text": "", "events": [], "citations": []}
    try:
        while True:
            sse_chunk = next(gen)
            sse_events.append(sse_chunk)
    except StopIteration as e:
        result = e.value or result

    result["sse_events"] = sse_events
    return result
