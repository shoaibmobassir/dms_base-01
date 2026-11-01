"""A turn that goes round in circles is stopped, narration stays out of the answer, and earlier answers say what
they did (plan 21, G-B). The model is scripted."""
from __future__ import annotations

import json

from app.chat import agent
from app.chat.agent import build_llm_messages, run_chat_agent_sync
from app.chat.models import ChatMessage, MessageRole
from app.chat.tools.document_tools import DocEntry


def _call(i: int, name: str, **args) -> dict:
    return {"id": f"c{i}", "function": {"name": name, "arguments": json.dumps(args)}}


def _index():
    return {"doc-0": DocEntry("doc-0", "DOC-0", "CTO.docx", text="[Page 1]\n1. Parties\n\n5. Remuneration")}


def _scripted(rounds: list[dict], seen: list):
    it = iter(rounds)

    def call(messages, *_a, **_k):
        seen.append([dict(m) for m in messages])
        return next(it)
    return call


def test_narration_goes_to_the_steps_and_the_answer_is_the_last_round(monkeypatch):
    monkeypatch.setattr(agent.settings, "grounding_enabled", False)
    seen: list = []
    monkeypatch.setattr(agent, "_call_llm", _scripted([
        {"content": "Let me read the document first.", "tool_calls": [_call(0, "get_outline", doc_id="doc-0")]},
        {"content": "Let me check the current text of the remaining sections.", "tool_calls": [_call(1, "get_outline", doc_id="doc-0", x=1)]},
        {"content": "The agreement has two sections.", "tool_calls": []},
    ], seen))
    out = run_chat_agent_sync(None, "what is in it", [], _index())
    assert out["full_text"] == "The agreement has two sections."
    narration = [e["text"] for e in out["events"] if e["type"] == "reasoning" and e.get("mode") == "narration"]
    assert narration == ["Let me read the document first.", "Let me check the current text of the remaining sections."]


def test_the_same_call_again_and_again_is_nudged_then_stopped(monkeypatch):
    monkeypatch.setattr(agent.settings, "grounding_enabled", False)
    seen: list = []
    same = {"content": "Let me check the current text of the remaining sections.",
            "tool_calls": [_call(0, "get_outline", doc_id="doc-0")]}
    monkeypatch.setattr(agent, "_call_llm", _scripted([same, same, same,
                                                        {"content": "I could not finish the edits.", "tool_calls": []}], seen))
    out = run_chat_agent_sync(None, "add these changes", [], _index())
    assert out["timings"].get("stopped_no_progress") is True
    assert len(seen) == 4, "two repeats: one nudge, then tools stop and the answer is wrapped up"
    assert any("repeating steps without progress" in str(m.get("content")) for m in seen[2])
    assert "WHAT ACTUALLY HAPPENED" in str(seen[-1]) and "No document was changed" in str(seen[-1])
    assert out["full_text"].startswith("I could not finish"), repr(out["full_text"])


def test_an_earlier_answer_tells_the_model_what_it_did():
    history = [
        ChatMessage(id="u1", session_id="s", role=MessageRole.user, content="renumber"),
        ChatMessage(id="a1", session_id="s", role=MessageRole.assistant, content="I renumbered the sections.",
                    events=[{"type": "edits_applied", "document_id": "DOC-0", "filename": "CTO.docx",
                             "version_number": 5, "changes": [{}, {}, {}, {}]}]),
    ]
    msgs = build_llm_messages(history, "undo these changes", _index(), "nonce")
    assistant = [m for m in msgs if m["role"] == "assistant"][0]["content"]
    assert "[Changed CTO.docx → v5: 4 change(s), in the document]" in assistant


def test_a_claimed_undo_without_the_tool_is_removed_from_the_answer(monkeypatch):
    monkeypatch.setattr(agent.settings, "grounding_enabled", False)
    seen: list = []
    monkeypatch.setattr(agent, "_call_llm", _scripted([
        {"content": "The proposed edits have been undone. Here are my suggestions: add a notice clause.", "tool_calls": []},
    ], seen))
    out = run_chat_agent_sync(None, "undo these changes and suggest improvements", [], _index())
    assert "have been undone" not in out["full_text"] and "No change was made to the document" in out["full_text"]
    assert "add a notice clause" in out["full_text"]
