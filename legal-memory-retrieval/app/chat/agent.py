"""
Chat agent: Multi-round tool-use agent loop with SSE streaming.
Orchestrates the LLM, tool calls, citation extraction, and verification.

Clean-room independent implementation for FirmOS legal assistant chatbot.
"""

from __future__ import annotations

import json
import logging
import random
import re
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
from app.chat.system_prompt import build_system_prompt
from app.chat.tools.document_tools import (
    DocIndex,
    DocStore,
    build_doc_availability,
    build_doc_index_from_hits,
    fetch_documents,
    find_in_document,
    get_outline,
    page_at,
    read_document,
    resolve_document_text,
    search_firm_records,
)
from app.chat.tools.batch_tools import review_documents_tool
from app.chat.tools.comment_tools import comment_on_document_tool
from app.chat.tools.edit_tools import edit_document_tool
from app.chat.context import carried_documents, fit_context, working_set, working_set_note
from app.chat.tools.firm_tools import (
    ask_firm_tool,
    find_people_tool,
    get_matter_profile_tool,
    resolve_matter_tool,
)
from app.chat.tools.generation_tools import generate_docx, generate_excel
from app.chat.tools.review_tools import propose_edits
from app.chat.tools.schema import ALL_TOOLS
from app.chat.verify_citations import verify_document_citation
from app.config import settings
from app.grounding import Source, ground_answer, verifier_llms
from app.db.connection import connect
from app.llm.bedrock_client import bedrock_configured, chat_complete
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
    "review_documents",
    "edit_document",
    "comment_on_document",
    "ask_firm",
    "resolve_matter",
    "get_matter_profile",
    "find_people",
    "read_document",
    "get_outline",
    "review_documents",
    "edit_document",
    "search_firm_records",
    "fetch_documents",
    "find_in_document",
    "propose_edits",
})
_KNOWN_TOOLS = _DB_TOOLS | frozenset({
    "generate_docx",
    "generate_excel",
    "ask_inputs",
    "list_workflows",
    "read_workflow",
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
    matter: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Execute a single tool call and return (result, events).
    Events are SSE-serializable dicts emitted to the client.

    ``matter`` ({matter_id, matter_code}) is the conversation's matter: search
    tools then look only inside it, whatever scope the model asks for.
    """
    events: list[dict[str, Any]] = []
    if matter and name == "ask_firm":
        arguments = {**arguments, "scope": matter["matter_code"]}

    if name == "read_document":
        cursor = arguments.get("cursor")
        result = read_document(
            arguments.get("doc_id", ""),
            doc_index, doc_store, conn, nonce,
            member_id=member_id,
            section_id=arguments.get("section_id") or None,
            pages=str(arguments["pages"]) if arguments.get("pages") else None,
            cursor=int(cursor) if isinstance(cursor, (int, float, str)) and str(cursor).isdigit() else None,
        )
        if "event" in result:
            events.append(result.pop("event"))
        return result, events

    elif name == "get_outline":
        return get_outline(arguments.get("doc_id", ""), doc_index, doc_store, conn, member_id=member_id), events

    elif name == "search_firm_records":
        result = search_firm_records(
            arguments.get("query", ""),
            doc_index,
            conn,
            member_id=member_id,
            k=arguments.get("k", 8),
            matter_id=matter["matter_id"] if matter else None,
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
            owner_member_id=member_id,
        )
        if "event" in result:
            events.append(result.pop("event"))
        return result, events

    elif name == "generate_excel":
        result = generate_excel(
            arguments.get("title", "Workbook"),
            arguments.get("sheets", []),
            owner_member_id=member_id,
        )
        if "event" in result:
            events.append(result.pop("event"))
        return result, events

    elif name == "edit_document":
        result, edit_events = edit_document_tool(arguments, doc_index, conn, member_id)
        events.extend(edit_events)
        return result, events

    elif name == "comment_on_document":
        result, comment_events = comment_on_document_tool(arguments, doc_index, conn, member_id)
        events.extend(comment_events)
        return result, events

    elif name == "review_documents":
        result, review_events = review_documents_tool(arguments, doc_index, conn, member_id, matter)
        events.extend(review_events)
        return result, events

    elif name == "propose_edits":
        result = propose_edits(
            arguments.get("doc_id", ""),
            arguments.get("edits", []),
            doc_index, doc_store, conn,
            member_id=member_id,
        )
        if "event" in result:
            events.append(result.pop("event"))
        return result, events

    elif name in _FIRM_TOOLS:
        result = _FIRM_TOOLS[name](arguments, doc_index, conn, member_id)
        if "event" in result:
            events.append(result.pop("event"))
        if name == "ask_firm":
            _load_passage_documents(result, doc_index, doc_store, conn, member_id)
        return result, events

    elif name == "list_workflows":
        from app.workflows.catalog_loader import get_catalog_loader

        return {"workflows": [
            {"id": wf.id, "title": wf.title, "description": wf.description, "category": wf.category}
            for wf in get_catalog_loader().list_workflows()
        ]}, events

    elif name == "read_workflow":
        from app.workflows.catalog_loader import get_catalog_loader

        wf = get_catalog_loader().get_workflow(str(arguments.get("workflow_id") or ""))
        if wf is None:
            return {"error": f"Unknown workflow: {arguments.get('workflow_id')}"}, events
        return {
            "id": wf.id, "title": wf.title, "description": wf.description, "inputs": wf.inputs,
            "steps": [
                {k: v for k, v in (("id", st.id), ("type", st.type), ("title", st.title), ("query", st.query), ("prompt", st.prompt)) if v}
                for st in wf.steps
            ],
        }, events

    elif name == "ask_inputs":
        items = _named_items(arguments.get("items", []), doc_index)
        event = {"type": "ask_inputs", "items": items}
        events.append(event)
        return {"status": "waiting_for_user_input", "items": items}, events

    else:
        return {"error": f"Unknown tool: {name}"}, events


def _load_passage_documents(
    result: dict[str, Any],
    doc_index: DocIndex,
    doc_store: DocStore,
    conn: Any,
    member_id: str | None,
) -> None:
    """Put the full text of every document ask_firm quoted into the turn's store.

    Without this, a citation to an ask_firm passage had no source text and was shown
    without any check at all.
    """
    for slug in dict.fromkeys(p.get("doc_id") for p in result.get("passages") or []):
        entry = doc_index.get(slug) if slug else None
        if entry is None or slug in doc_store:
            continue
        try:
            resolve_document_text(entry, doc_store, conn, member_id)
        except Exception as exc:  # the answer can still be checked against the passage text
            logger.warning("[chat/agent] could not load %s for verification: %s", entry.document_id, exc)
            text = "\n\n".join(p.get("text") or "" for p in result.get("passages") or [] if p.get("doc_id") == slug)
            if text:
                doc_store[slug] = text


_RECORD_TOOLS = frozenset({"ask_firm", "resolve_matter", "get_matter_profile", "find_people", "review_documents"})


def _record_text(value: Any, indent: str = "") -> str:
    """Flatten a firm-record tool result into readable "key: value" lines."""
    if isinstance(value, dict):
        lines = []
        for k, v in value.items():
            if k in {"passages", "draft_answer", "key_finding", "note", "event"} or v in (None, "", [], {}):
                continue
            if isinstance(v, (dict, list)):
                lines.append(f"{indent}{k}:\n{_record_text(v, indent + '  ')}")
            else:
                lines.append(f"{indent}{k}: {v}")
        return "\n".join(lines)
    if isinstance(value, list):
        return "\n".join(_record_text(v, indent) for v in value)
    return f"{indent}{value}"


def grounding_sources(doc_index: DocIndex, doc_store: DocStore, records: list[str]) -> list[Source]:
    sources = []
    for slug, text in doc_store.items():
        entry = doc_index.get(slug)
        if entry is None or not text or text == "Document could not be read.":
            continue
        sources.append(Source(key=slug, document_id=entry.document_id, title=entry.filename, text=text))
    for i, text in enumerate(records):
        sources.append(Source(key=f"record:{i}", document_id=None, title="Firm records", text=text))
    return sources


def ground_chat_text(
    full_text: str,
    doc_index: DocIndex,
    doc_store: DocStore,
    records: list[str],
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Verify every statement of the final answer; return (text, citations, report)."""
    prose = extract_citations_text(full_text)
    by_ref = {c.ref: c for c in parse_citations(full_text)}

    def refs(unit) -> list[Any]:
        return [by_ref[int(r)] for r in unit.refs if int(r) in by_ref]

    grounded = ground_answer(
        prose,
        ref_style="markers",
        cited_keys=lambda u: [c.doc_id for c in refs(u)],
        offered_quotes=lambda u: [q.quote for c in refs(u) for q in (getattr(c, "quotes", None) or [])],
        sources=grounding_sources(doc_index, doc_store, records),
        llm=verifier_llms(),
    )
    citations = []
    for c in grounded.citations:
        entry = doc_index.get(c["doc_id"])
        if entry is not None:
            c = {**c, "document_id": entry.document_id, "title": entry.filename}
        citations.append(c)
    return name_documents(grounded.text, doc_index), citations, {**grounded.report(), "timings": grounded.timings}


_FIRM_TOOLS = {
    "ask_firm": lambda a, idx, conn, mid: ask_firm_tool(
        str(a.get("question") or ""), a.get("scope") or None, idx, conn, mid,
    ),
    "resolve_matter": lambda a, idx, conn, mid: resolve_matter_tool(str(a.get("query") or ""), conn, mid),
    "get_matter_profile": lambda a, idx, conn, mid: get_matter_profile_tool(
        str(a.get("matter") or ""), idx, conn, mid,
    ),
    "find_people": lambda a, idx, conn, mid: find_people_tool(
        str(a.get("query") or ""), a.get("matter") or None, conn, mid,
    ),
}


def _named_items(items: Any, doc_index: DocIndex) -> list[dict[str, Any]]:
    """Clarifying questions are shown to the lawyer: replace internal doc labels with names."""
    if not isinstance(items, list):
        return []
    named: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        if isinstance(item.get("question"), str):
            item["question"] = name_documents(item["question"], doc_index)
        if isinstance(item.get("options"), list):
            item["options"] = [
                {**o, "value": name_documents(str(o.get("value", "")), doc_index)} if isinstance(o, dict) else o
                for o in item["options"]
            ]
        named.append(item)
    return named


def tool_step_label(name: str, arguments: dict[str, Any], doc_index: DocIndex) -> str:
    """Plain-English description of a tool call for the step timeline. No tool names."""
    entry = doc_index.get(str(arguments.get("doc_id") or ""))
    doc_name = entry.filename if entry else "a document"
    query = str(arguments.get("query") or "").strip()
    if name == "search_firm_records":
        return f"Searching firm records for “{query}”" if query else "Searching firm records"
    if name == "read_document":
        part = arguments.get("section_id") or (f"pages {arguments['pages']}" if arguments.get("pages") else "")
        return f"Reading {doc_name}" + (f" ({part})" if part else "")
    if name == "get_outline":
        return f"Opening the contents of {doc_name}"
    if name == "edit_document":
        return f"Planning edits to {doc_name}"
    if name == "comment_on_document":
        return f"Adding comments to {doc_name}"
    if name == "review_documents":
        n = len(arguments.get("doc_ids") or [])
        what = f"{n} documents" if n else (f"the documents of {arguments['matter']}" if arguments.get("matter") else "the documents")
        return f"Reviewing {what} ({len(arguments.get('questions') or [])} questions each)"
    if name == "fetch_documents":
        count = len(arguments.get("doc_ids") or [])
        return f"Reading {count} document{'s' if count != 1 else ''}"
    if name == "find_in_document":
        return f"Looking for “{query}” in {doc_name}"
    if name == "generate_docx":
        return f"Drafting {arguments.get('title') or 'a Word document'}"
    if name == "generate_excel":
        return f"Building {arguments.get('title') or 'a spreadsheet'}"
    if name == "propose_edits":
        return f"Preparing suggested edits to {doc_name}"
    if name == "ask_inputs":
        return "Asking you to clarify"
    if name == "ask_firm":
        question = str(arguments.get("question") or "").strip()
        return f"Checking the firm's records: “{question}”" if question else "Checking the firm's records"
    if name == "resolve_matter":
        return f"Identifying the matter for “{query}”" if query else "Identifying the matter"
    if name == "get_matter_profile":
        return f"Opening the matter record for {arguments.get('matter') or 'the matter'}"
    if name == "find_people":
        if arguments.get("matter"):
            return f"Looking up the team on {arguments['matter']}"
        return f"Finding colleagues for “{query}”" if query else "Finding colleagues"
    if name in {"list_workflows", "read_workflow"}:
        return "Checking firm workflows"
    return "Working"


def tool_deadline_seconds(name: str) -> float:
    """Wall-clock bound for one tool. Find-in-document is shorter than retrieve."""
    if name == "find_in_document":
        return settings.chat_find_timeout_seconds
    if name in ("review_documents", "edit_document"):  # many model calls in parallel
        return settings.review_tool_timeout_seconds
    if name == "ask_firm":  # retrieval plus its own grounded LLM answer
        return max(settings.chat_tool_timeout_seconds, 75.0)
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
    matter: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Run a tool on a connection this worker created, so the request conn stays put."""
    if name not in _DB_TOOLS:
        return dispatch_tool_call(
            name, arguments, doc_index, doc_store, None, nonce, member_id=member_id, matter=matter,
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
            name, arguments, doc_index, doc_store, tool_conn, nonce, member_id=member_id, matter=matter,
        )


def dispatch_tool_call_bounded(
    name: str,
    arguments: dict[str, Any],
    doc_index: DocIndex,
    doc_store: DocStore,
    nonce: str,
    member_id: str | None = None,
    timeout: float | None = None,
    matter: dict[str, str] | None = None,
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
        matter,
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


_DOC_LABEL_RE = re.compile(r"\(?\bdoc-(\d+)\b\)?")


def name_documents(text: str, doc_index: DocIndex) -> str:
    """Replace chat-local labels such as "doc-3" in prose with the document's name."""
    def swap(match: re.Match[str]) -> str:
        entry = doc_index.get(f"doc-{match.group(1)}")
        if entry is None:
            return match.group(0)
        name = entry.filename
        return f"({name})" if match.group(0).startswith("(") and match.group(0).endswith(")") else name
    return _DOC_LABEL_RE.sub(swap, text) if text else text


def correct_quote_pages(citation: dict[str, Any], source_text: str) -> dict[str, Any]:
    """Replace the model's page guess with the page where a verified quote was found."""
    quotes = []
    for q in citation.get("quotes") or []:
        start = (q.get("verification") or {}).get("start_char")
        found = page_at(source_text, start) if isinstance(start, int) else None
        quotes.append({**q, "page": found} if found else q)
    if not quotes:
        return citation
    return {**citation, "quotes": quotes, "page": quotes[0].get("page", citation.get("page"))}


def citation_result_label(citation: dict[str, Any], had_source: bool) -> str:
    if not had_source:
        return "no_source"
    if citation.get("verified") is True:
        return "verified"
    return "unverified"


# ---------------------------------------------------------------------------
# Build LLM messages from chat history + context
# ---------------------------------------------------------------------------

def reasoning_status(mode: str | None, document_count: int) -> str:
    """One plain sentence the lawyer sees while the answer is prepared."""
    scope = (
        f"{document_count} document{'s' if document_count != 1 else ''} in scope"
        if document_count
        else "no documents in scope yet"
    )
    lines = {
        "reason": f"Reasoning over {scope}.",
        "research": f"Researching authorities across {scope}.",
        "review": f"Reviewing the documents in {scope}.",
        "cite": f"Preparing citations from {scope}.",
    }
    return lines.get(mode or "", f"Reading {scope}.")


def build_llm_messages(
    history: list[ChatMessage],
    user_message: str,
    doc_index: DocIndex,
    nonce: str,
    max_pairs: int | None = None,
    mode: str | None = None,
    matter: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build the LLM message array: system + windowed history + current user."""
    doc_availability = build_doc_availability(doc_index)
    attached = [d for d in doc_availability if d.get("attached")]
    found = [d for d in doc_availability if not d.get("attached")]

    system_content = build_system_prompt(mode)
    if matter:
        system_content += (
            f"\n\nTHIS CONVERSATION IS LIMITED TO ONE MATTER: {matter['matter_code']}"
            f" ({matter.get('title') or matter['matter_id']}). Searches return only this matter's records."
            " If the question needs other matters, say so and suggest widening the search to all matters."
        )
    if attached:
        system_content += (
            "\n\nDOCUMENTS THE USER ATTACHED (when the user says \"this document\", \"this note\", "
            "or similar, they mean these; work on these, not on similarly named search results):\n"
            + "\n".join(f"- {d['doc_id']}: {d['filename']}" for d in attached)
        )
    if found:
        heading = "OTHER DOCUMENTS FOUND BY SEARCH" if attached else "AVAILABLE DOCUMENTS"
        system_content += f"\n\n{heading}:\n" + "\n".join(f"- {d['doc_id']}: {d['filename']}" for d in found)

    carried = carried_documents(history)
    if carried:
        system_content += working_set_note(carried, {e.document_id: slug for slug, e in doc_index.items()})

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
    Call the LLM with tool support.
    Preference: Bedrock → Gemini → Groq → local stub.
    """
    if bedrock_configured():
        return _call_bedrock(messages, tools, model)
    if settings.gemini_api_key:
        return _call_gemini(messages, tools, model)
    if settings.groq_api_key:
        return _call_groq(messages, tools, model)
    return {
        "content": "I apologise, but I cannot process your request at the moment. No LLM API key is configured.",
        "tool_calls": [],
    }


def _call_bedrock(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    model: str | None = None,
) -> dict[str, Any]:
    """Call Amazon Bedrock Mantle with OpenAI-compatible tool calling."""
    model_id = model or settings.bedrock_model or "zai.glm-5"
    # Mantle expects OpenAI-style messages; drop unsupported fields carefully but
    # keep the tool-calling linkage, or the round after a tool call is rejected (400).
    clean_messages: list[dict[str, Any]] = []
    for msg in messages:
        role = str(msg.get("role") or "user")
        content = msg.get("content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            content = json.dumps(content)
        clean: dict[str, Any] = {"role": role, "content": content}
        if role == "assistant" and msg.get("tool_calls"):
            clean["tool_calls"] = msg["tool_calls"]
        if role == "tool":
            clean["tool_call_id"] = msg.get("tool_call_id") or str(uuid.uuid4())
            if msg.get("name"):
                clean["name"] = msg["name"]
        clean_messages.append(clean)

    def call() -> dict[str, Any]:
        return chat_complete(
            clean_messages,
            model=model_id,
            temperature=0.3,
            max_tokens=8192,
            tools=tools or None,
            timeout=120.0,
        )

    try:
        result = call()
    except httpx.HTTPStatusError as exc:
        # The model occasionally emits a malformed tool call ("Unterminated string"), which
        # the endpoint rejects as a 400. Sampling again usually produces a valid one.
        if exc.response is None or exc.response.status_code != 400 or "Unterminated" not in exc.response.text:
            raise
        logger.warning("[chat/agent] malformed tool call from %s; retrying once", model_id)
        result = call()
    return {
        "content": result.get("content") or "",
        "tool_calls": result.get("tool_calls") or [],
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

# Read-only tools that may run side by side within one round (no index or session writes).
PARALLEL_SAFE_TOOLS = frozenset({
    "read_document", "get_outline", "find_in_document", "fetch_documents",
    "resolve_matter", "get_matter_profile", "find_people",
})
WRAP_UP_PROMPT = (
    "Stop using tools now. Answer the request from the information already gathered above, with citations "
    "for what you rely on, and say plainly which parts you could not check."
)


def _record_working_set(all_events: list[dict[str, Any]]) -> None:
    """Persist (with the message, not streamed) which documents this turn read or searched."""
    docs = working_set(all_events)
    if docs:
        all_events.append({"type": "working_set", "documents": docs})


def run_chat_agent(
    conn,
    user_message: str,
    history: list[ChatMessage],
    doc_index: DocIndex,
    model: str | None = None,
    member_id: str | None = None,
    mode: str | None = None,
    hit_count: int | None = None,
    matter: dict[str, str] | None = None,
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
    document_count = hit_count if hit_count is not None else len(doc_index)
    opening = {
        "type": "reasoning",
        "text": reasoning_status(mode, document_count),
        "mode": mode or "answer",
    }
    all_events.append(opening)
    yield sse_event("reasoning", {"text": opening["text"], "mode": opening["mode"]})
    messages = build_llm_messages(history, user_message, doc_index, nonce, mode=mode, matter=matter)
    tools = ALL_TOOLS
    request_id = current_request_id() or "-"

    full_text = ""
    records: list[str] = []
    grounding = settings.grounding_enabled
    started_at = time.perf_counter()
    # Per-stage wall time for this turn (returned to callers; read by evals/grounding_eval.py).
    timings: dict[str, Any] = {"llm_ms": [], "tool_ms": [], "tool_calls_per_round": []}

    def finish_timings() -> dict[str, Any]:
        timings["rounds"] = len(timings["llm_ms"])
        timings["total_ms"] = round((time.perf_counter() - started_at) * 1000, 1)
        return timings

    turn_deadline = started_at + settings.chat_turn_deadline_seconds
    paused_tools: set[str] = set()
    answered = False
    for round_num in range(MAX_TOOL_ROUNDS):
        logger.info(
            "[chat/agent] round %d, messages=%d, request_id=%s",
            round_num + 1,
            len(messages),
            request_id,
        )

        evicted = fit_context(messages, settings.chat_context_max_chars)
        if evicted:
            timings["evicted_tool_outputs"] = timings.get("evicted_tool_outputs", 0) + evicted
            logger.info("[chat/agent] stubbed %d old tool outputs to fit context, request_id=%s", evicted, request_id)
        remaining = turn_deadline - time.perf_counter()
        if remaining < 5:
            timings["deadline_hit"] = True
            break
        try:
            t = time.perf_counter()
            response = run_with_deadline(_call_llm, remaining, messages, tools, model)
            timings["llm_ms"].append(round((time.perf_counter() - t) * 1000, 1))
            if response is DEADLINE_EXCEEDED:
                timings["deadline_hit"] = True
                logger.warning("[chat/agent] turn deadline reached in an LLM call, request_id=%s", request_id)
                break
        except Exception as exc:
            logger.error(
                "[chat/agent] LLM call failed: %s, request_id=%s",
                exc,
                request_id,
            )
            CHAT_TURNS.labels(outcome="llm_error").inc()
            yield sse_event("error", {"message": "Failed to generate response. Please try again."})
            yield sse_done()
            return {"full_text": "", "events": all_events, "citations": [], "timings": finish_timings()}

        content = response.get("content", "")
        tool_calls = response.get("tool_calls", [])

        # Stream text content. Separate rounds so narration before a tool call
        # does not run into the next sentence.
        if content:
            if full_text and not full_text.endswith("\n"):
                content = "\n\n" + content.lstrip()
            full_text += content
            clean_text = name_documents(extract_citations_text(content), doc_index)
            # With grounding on, the final answer is shown only after it is verified.
            if clean_text and not (grounding and not tool_calls):
                yield sse_event("text_delta", {"text": clean_text})

        # If no tool calls, we're done
        if not tool_calls:
            answered = True
            break
        timings["tool_calls_per_round"].append(len(tool_calls))

        # Process tool calls
        messages.append({
            "role": "assistant",
            "content": content or "",
            "tool_calls": tool_calls,
        })

        calls = []
        for tc in tool_calls:
            func = tc.get("function", {})
            try:
                args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}
            calls.append((tc, func.get("name", ""), args, str(tc.get("id") or uuid.uuid4())))
            logger.info("[chat/agent] tool call: %s(%s), request_id=%s", calls[-1][1], list(args.keys()), request_id)

        def run_call(call) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
            _tc, name, args, _cid = call
            if name in paused_tools:
                return {"error": f"{name} is paused for this turn after a timeout"}, [], False
            bound = min(tool_deadline_seconds(name), max(1.0, turn_deadline - time.perf_counter()))
            return dispatch_tool_call_bounded(name, args, doc_index, doc_store, nonce, member_id=member_id,
                                              timeout=bound, matter=matter)

        # Independent read-only calls in one round run side by side; their steps are still
        # reported in the order the model asked for them.
        parallel = len(calls) > 1 and all(c[1] in PARALLEL_SAFE_TOOLS for c in calls)
        outcomes: dict[int, tuple[dict[str, Any], list[dict[str, Any]], bool]] = {}
        if parallel:
            for _tc, name, args, cid in calls:
                started = {"type": "tool_started", "call_id": cid, "tool": name, "label": tool_step_label(name, args, doc_index)}
                all_events.append(started)
                yield sse_event("tool_started", started)
            t = time.perf_counter()
            with ThreadPoolExecutor(max_workers=min(len(calls), 8), thread_name_prefix="chat-round") as pool:
                for i, out in enumerate(pool.map(run_call, calls)):
                    outcomes[i] = out
            wall = round((time.perf_counter() - t) * 1000, 1)
            timings["tool_ms"].append({"tool": "+".join(c[1] for c in calls), "ms": wall, "parallel": len(calls)})

        for i, call in enumerate(calls):
            tc, tool_name, args, call_id = call
            if not parallel:
                started = {"type": "tool_started", "call_id": call_id, "tool": tool_name,
                           "label": tool_step_label(tool_name, args, doc_index)}
                all_events.append(started)
                yield sse_event("tool_started", started)
                t = time.perf_counter()
                outcomes[i] = run_call(call)
                timings["tool_ms"].append({"tool": tool_name, "ms": round((time.perf_counter() - t) * 1000, 1)})
            result, events, timed_out = outcomes[i]
            if timed_out:
                paused_tools.add(tool_name)

            # Stream tool events, then close the step
            for event in events:
                event.setdefault("call_id", call_id)
                all_events.append(event)
                yield sse_event(event.get("type", "tool_event"), event)
            finished = {
                "type": "tool_finished",
                "call_id": call_id,
                "tool": tool_name,
                "ok": not result.get("error"),
            }
            if result.get("error"):
                finished["error"] = str(result["error"])[:200]
            all_events.append(finished)
            yield sse_event("tool_finished", finished)

            # If ask_inputs was called, stop the loop
            if tool_name == "ask_inputs" and not result.get("error"):
                CHAT_TURNS.labels(outcome="waiting_input").inc()
                yield sse_done()
                return {
                    "full_text": full_text,
                    "events": all_events,
                    "citations": [],
                    "waiting_for_input": True,
                    "timings": finish_timings(),
                }

            if tool_name in _RECORD_TOOLS and not result.get("error"):
                records.append(_record_text(result))

            # Add tool result to messages
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", str(uuid.uuid4())),
                "name": tool_name,
                "content": json.dumps(result, default=str),
            })

    if not answered:
        # Out of time or rounds while still gathering: one tool-free call answers from what is in hand.
        timings["wrap_up"] = True
        messages.append({"role": "user", "content": WRAP_UP_PROMPT})
        t = time.perf_counter()
        try:
            response = run_with_deadline(_call_llm, settings.chat_wrap_up_seconds, messages, [], model)
        except Exception as exc:
            logger.error("[chat/agent] wrap-up call failed: %s, request_id=%s", exc, request_id)
            response = DEADLINE_EXCEEDED
        timings["llm_ms"].append(round((time.perf_counter() - t) * 1000, 1))
        content = "" if response is DEADLINE_EXCEEDED else str(response.get("content") or "")
        if not content:
            content = ("I ran out of time before finishing this task. The steps above show what was checked; "
                       "please narrow the request or ask me to continue.")
        full_text = (full_text + "\n\n" if full_text and not full_text.endswith("\n") else full_text) + content
        if not grounding:
            yield sse_event("text_delta", {"text": name_documents(extract_citations_text(content), doc_index)})

    if grounding and full_text.strip():
        step = {"type": "reasoning", "text": "Checking each statement against its source", "mode": mode or "answer"}
        all_events.append(step)
        yield sse_event("reasoning", {"text": step["text"], "mode": step["mode"]})
        t = time.perf_counter()
        try:
            clean_text, verified_citations, report = ground_chat_text(full_text, doc_index, doc_store, records)
        except Exception as exc:  # never show an unchecked answer as if it were checked
            logger.error("[chat/agent] grounding failed: %s, request_id=%s", exc, request_id)
            clean_text = ("The answer could not be checked against its sources, so it is not shown. "
                          "Please try again.")
            verified_citations, report = [], {"error": "grounding_failed"}
        timings["grounding_ms"] = round((time.perf_counter() - t) * 1000, 1)
        timings["grounding"] = report.pop("timings", {})
        all_events.append({"type": "grounding", **report})
        yield sse_event("grounding", report)
        yield sse_event("text_final", {"text": clean_text})
        for cit in verified_citations:
            CHAT_CITATION_RESULTS.labels(result="verified").inc()
            yield sse_event("citation_data", cit)
        CHAT_TURNS.labels(outcome="completed").inc()
        _record_working_set(all_events)
        yield sse_done()
        return {"full_text": clean_text, "events": all_events, "citations": verified_citations,
                "timings": finish_timings()}

    # Parse and verify citations
    citations = parse_citations(full_text)
    verified_citations: list[dict[str, Any]] = []
    for cit in citations:
        cit_dict = cit.to_dict()
        doc_id = cit_dict.get("doc_id", "")
        source_text = doc_store.get(doc_id, "")
        had_source = bool(source_text)
        if had_source:
            verified = correct_quote_pages(verify_document_citation(cit_dict, source_text), source_text)
        else:
            verified = cit_dict
        CHAT_CITATION_RESULTS.labels(
            result=citation_result_label(verified, had_source),
        ).inc()
        # doc_id is a per-turn alias ("doc-0"); attach the real document for the UI.
        entry = doc_index.get(doc_id)
        if entry is not None:
            verified = {**verified, "document_id": entry.document_id, "title": entry.filename}
        verified_citations.append(verified)
        # Stream citation data
        yield sse_event("citation_data", verified)

    # Clean response text (strip CITATIONS block, never show internal doc labels)
    clean_text = name_documents(extract_citations_text(full_text), doc_index)

    CHAT_TURNS.labels(outcome="completed").inc()
    _record_working_set(all_events)
    yield sse_done()
    return {
        "full_text": clean_text,
        "events": all_events,
        "citations": verified_citations,
        "timings": finish_timings(),
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
    mode: str | None = None,
    hit_count: int | None = None,
    matter: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Run the agent loop synchronously, collecting all SSE events.
    Returns the final result dict with full_text, events, citations,
    and the collected sse_events list.
    """
    sse_events: list[str] = []
    gen = run_chat_agent(
        conn,
        user_message,
        history,
        doc_index,
        model,
        member_id=member_id,
        mode=mode,
        hit_count=hit_count,
        matter=matter,
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
