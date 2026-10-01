"""Keep an agent turn inside its context budget without losing track of what was read.

Every tool result is appended to the conversation as the turn goes on; reading several long
documents would otherwise grow the prompt until the model call fails. When the messages
exceed ``settings.chat_context_max_chars``, the oldest tool outputs (never those of the latest
round) are replaced by a stub naming the tool and its arguments. Reads are addressable
(section / pages / cursor, see ``app/chat/doc_nav.py``), so the model can reopen exactly the
part it needs. Citation checking is unaffected: it uses the full texts in ``doc_store``.
"""
from __future__ import annotations

import json
from typing import Any

STUB_NOTE = "Output removed to keep the conversation within its size limit. Call the tool again with the same arguments if you still need it."


def _size(messages: list[dict[str, Any]]) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)


def _arguments(messages: list[dict[str, Any]], call_id: str | None) -> dict[str, Any]:
    for m in messages:
        for tc in m.get("tool_calls") or []:
            if tc.get("id") == call_id:
                try:
                    return json.loads((tc.get("function") or {}).get("arguments") or "{}")
                except json.JSONDecodeError:
                    return {}
    return {}


def fit_context(messages: list[dict[str, Any]], max_chars: int) -> int:
    """Stub the oldest tool outputs until the messages fit; returns how many were stubbed."""
    total = _size(messages)
    if total <= max_chars:
        return 0
    last_round = max((i for i, m in enumerate(messages) if m.get("role") == "assistant" and m.get("tool_calls")), default=-1)
    evicted = 0
    for i, m in enumerate(messages[:last_round]):
        if m.get("role") != "tool" or str(m.get("content") or "").startswith('{"evicted"'):
            continue
        stub = json.dumps({"evicted": True, "tool": m.get("name"),
                           "arguments": _arguments(messages, m.get("tool_call_id")), "note": STUB_NOTE})
        total -= len(str(m.get("content") or "")) - len(stub)
        m["content"] = stub
        evicted += 1
        if total <= max_chars:
            break
    return evicted


# ---------------------------------------------------------------------------
# Working set: what this conversation already opened, carried into the next turn
# ---------------------------------------------------------------------------

def working_set(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Documents read or searched during a turn, from its doc_read / doc_find events."""
    docs: dict[str, dict[str, Any]] = {}
    for e in events:
        if e.get("type") not in ("doc_read", "doc_find") or not e.get("document_id"):
            continue
        d = docs.setdefault(e["document_id"], {"document_id": e["document_id"], "filename": e.get("filename"),
                                                "parts": [], "searches": []})
        if e["type"] == "doc_read":
            part = e.get("part") or "whole document"
            if part not in d["parts"]:
                d["parts"].append(part)
        elif e.get("query") and e["query"] not in d["searches"]:
            d["searches"].append(e["query"])
    return list(docs.values())


def carried_documents(history: list[Any], turns: int = 3) -> list[dict[str, Any]]:
    """Working-set documents of the last ``turns`` assistant messages, most recent first."""
    out: dict[str, dict[str, Any]] = {}
    seen_turns = 0
    for msg in reversed(history):
        if getattr(getattr(msg, "role", None), "value", getattr(msg, "role", None)) != "assistant":
            continue
        seen_turns += 1
        for e in getattr(msg, "events", None) or []:
            if e.get("type") == "working_set":
                for d in e.get("documents") or []:
                    out.setdefault(d["document_id"], d)
        if seen_turns >= turns:
            break
    return list(out.values())


def working_set_note(carried: list[dict[str, Any]], slug_of: dict[str, str]) -> str:
    lines = []
    for d in carried:
        slug = slug_of.get(d["document_id"])
        if not slug:
            continue
        what = []
        if d.get("parts"):
            what.append("read: " + ", ".join(d["parts"][:8]))
        if d.get("searches"):
            what.append("searched: " + ", ".join(f"“{q}”" for q in d["searches"][:5]))
        lines.append(f"- {slug}: {d.get('filename') or d['document_id']}" + (f" ({'; '.join(what)})" if what else ""))
    if not lines:
        return ""
    return ("\n\nDOCUMENTS YOU WORKED ON EARLIER IN THIS CONVERSATION (same documents, new ids for this turn; "
            "their text is not repeated here, reopen only the parts you need):\n" + "\n".join(lines))
