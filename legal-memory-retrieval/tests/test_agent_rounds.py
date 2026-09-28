"""Assistant turn mechanics: parallel read-only tools, per-tool pause, turn deadline and wrap-up."""
from __future__ import annotations

import json
import threading
import time

from app.chat import agent
from app.chat.agent import run_chat_agent_sync
from app.chat.tools.document_tools import DocEntry


def _call(i: int, name: str, **args) -> dict:
    return {"id": f"c{i}", "function": {"name": name, "arguments": json.dumps(args)}}


def _index():
    return {f"doc-{i}": DocEntry(f"doc-{i}", f"DOC-{i}", f"d{i}.docx", text=f"[Page 1]\nText of document {i}.") for i in range(3)}


def _scripted(rounds: list[dict]):
    it = iter(rounds)
    return lambda *_a, **_k: next(it)


def test_read_only_calls_in_one_round_run_in_parallel_and_report_in_order(monkeypatch):
    monkeypatch.setattr(agent.settings, "grounding_enabled", False)
    monkeypatch.setattr(agent, "_call_llm", _scripted([
        {"content": "", "tool_calls": [_call(i, "get_outline", doc_id=f"doc-{i}") for i in range(3)]},
        {"content": "Done.", "tool_calls": []},
    ]))
    active, peak, lock = [0], [0], threading.Lock()
    real = agent.dispatch_tool_call_bounded

    def slow(*args, **kwargs):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.2)
        try:
            return real(*args, **kwargs)
        finally:
            with lock:
                active[0] -= 1

    monkeypatch.setattr(agent, "dispatch_tool_call_bounded", slow)
    t = time.perf_counter()
    out = run_chat_agent_sync(None, "outline all three", [], _index())
    assert peak[0] == 3, "all three calls must be in flight together"
    finished = [e["call_id"] for e in out["events"] if e["type"] == "tool_finished"]
    assert finished == ["c0", "c1", "c2"]
    assert out["timings"]["tool_ms"][0]["parallel"] == 3


def test_a_timed_out_tool_pauses_only_itself(monkeypatch):
    monkeypatch.setattr(agent.settings, "grounding_enabled", False)
    monkeypatch.setattr(agent, "_call_llm", _scripted([
        {"content": "", "tool_calls": [_call(0, "search_firm_records", query="x")]},
        {"content": "", "tool_calls": [_call(1, "search_firm_records", query="y"), ]},
        {"content": "", "tool_calls": [_call(2, "get_outline", doc_id="doc-0")]},
        {"content": "Done.", "tool_calls": []},
    ]))
    real = agent.dispatch_tool_call_bounded

    def fake(name, *args, **kwargs):
        if name == "search_firm_records":
            return {"error": "timed out", "timed_out": True}, [], True
        return real(name, *args, **kwargs)

    monkeypatch.setattr(agent, "dispatch_tool_call_bounded", fake)
    out = run_chat_agent_sync(None, "q", [], _index())
    finished = {e["call_id"]: e for e in out["events"] if e["type"] == "tool_finished"}
    assert "paused" in finished["c1"]["error"]
    assert finished["c2"]["ok"], "other tools keep working after one tool times out"


def test_turn_deadline_stops_tools_and_wraps_up(monkeypatch):
    monkeypatch.setattr(agent.settings, "grounding_enabled", False)
    monkeypatch.setattr(agent.settings, "chat_turn_deadline_seconds", 6.0)
    seen_tools: list = []

    def llm(messages, tools, model=None):
        seen_tools.append(bool(tools))
        if not tools:
            return {"content": "Partial answer from what was read.", "tool_calls": []}
        time.sleep(0.5)
        return {"content": "", "tool_calls": [_call(len(seen_tools), "get_outline", doc_id="doc-0")]}

    monkeypatch.setattr(agent, "_call_llm", llm)
    monkeypatch.setattr(agent, "MAX_TOOL_ROUNDS", 100)
    t = time.perf_counter()
    out = run_chat_agent_sync(None, "keep going", [], _index())
    assert time.perf_counter() - t < 8
    assert seen_tools[-1] is False and out["timings"]["wrap_up"]
    assert "Partial answer" in out["full_text"]


def test_round_limit_without_an_answer_also_wraps_up(monkeypatch):
    monkeypatch.setattr(agent.settings, "grounding_enabled", False)
    monkeypatch.setattr(agent, "MAX_TOOL_ROUNDS", 2)
    monkeypatch.setattr(agent, "_call_llm", lambda m, tools, model=None: (
        {"content": "Summary so far.", "tool_calls": []} if not tools
        else {"content": "", "tool_calls": [_call(9, "get_outline", doc_id="doc-1")]}))
    out = run_chat_agent_sync(None, "q", [], _index())
    assert out["timings"]["wrap_up"] and "Summary so far." in out["full_text"]
