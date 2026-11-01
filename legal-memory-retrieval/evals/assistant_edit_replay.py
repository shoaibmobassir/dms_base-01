"""Live replay of the reported "undo / suggest improvements / yes proceed" conversation on a copy of the CTO agreement.

    python evals/history_ui_fixture.py copy DOC-7405413EC8 --member MEM-00001   -> a throwaway copy
    python evals/assistant_edit_replay.py DOC-<copy> MEM-00001 [--base http://127.0.0.1:8021]

Turns (the lawyer's words from the report, after one earlier edit):
  0. "renumber the sections so they run in order"
  1. "undo these changes and suggest improvements with references of this matter"
  2. "yes proceed, add these changes listed above on the doc"
then Undo on turn 2 through the API.

Checks: edits land without asking; undo is real (tool) or not claimed; no loops (tool calls, narration); statements
removed; the Word file after turn 2: headings numbered 1..N in order, no duplicated paragraphs, no tracked markup;
Undo restores the text from before turn 2 exactly.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TURNS = [
    "renumber the sections so they run in order",
    "undo these changes and suggest improvements with references of this matter",
    "yes proceed, add these changes listed above on the doc",
]
_HEADING = re.compile(r"^(\d{1,2})\.\s+\S")


def _file(doc_id: str) -> tuple[list[str], bool, int]:
    from docx import Document
    from docx.oxml.ns import qn

    from app.db.connection import connect
    from app.storage.object_store import get_object_store

    with connect() as conn:
        row = conn.execute("SELECT v.storage_uri, v.version_number FROM documents d JOIN document_versions v "
                           "ON v.version_id = d.current_version_id WHERE d.document_id = %s", (doc_id,)).fetchone()
    d = Document(io.BytesIO(get_object_store().get(row["storage_uri"])))
    body = d.element.body
    return [p.text for p in d.paragraphs], bool(list(body.iter(qn("w:ins"))) or list(body.iter(qn("w:del")))), row["version_number"]


def _structure(paras: list[str]) -> dict:
    nums = [int(_HEADING.match(p).group(1)) for p in paras if _HEADING.match(p) and len(p) < 120]
    long = [" ".join(p.split()) for p in paras if len(p) > 40]
    return {"heading_numbers": nums, "in_order": nums == list(range(1, len(nums) + 1)),
            "duplicate_paragraphs": len(long) - len(set(long))}


def run(doc_id: str, member: str, base: str) -> dict:
    h = {"X-Member-Id": member}
    from app.db.connection import connect

    with connect() as conn:
        matter = conn.execute("SELECT matter_id FROM documents WHERE document_id = %s", (doc_id,)).fetchone()["matter_id"]
    out: dict = {"turns": []}
    with httpx.Client(base_url=base, headers=h, timeout=400) as c:
        sid = c.post("/api/chat/sessions", json={"matter_id": matter}).json()["id"]
        out["session_id"] = sid
        before_turn: list[str] = []
        for i, text in enumerate(TURNS):
            before_turn = _file(doc_id)[0]
            body: dict = {"content": text}
            if i == 0:
                body["files"] = [{"filename": "Employment Agreement - CTO.docx", "document_id": doc_id}]
            with c.stream("POST", f"/api/chat/sessions/{sid}/messages", json=body) as r:
                for _ in r.iter_lines():
                    pass
            msg = [m for m in c.get(f"/api/chat/sessions/{sid}").json()["messages"] if m["role"] == "assistant"][-1]
            ev = msg.get("events") or []
            tools = [e.get("tool") for e in ev if e.get("type") == "tool_started"]
            applied = [e for e in ev if e.get("type") == "edits_applied"]
            grounding = next((e for e in ev if e.get("type") == "grounding"), {})
            paras, markup, version = _file(doc_id)
            out["turns"].append({
                "user": text,
                "answer": msg["content"][:1500],
                "tool_calls": tools,
                "narration_lines": sum(1 for e in ev if e.get("type") == "reasoning" and e.get("mode") == "narration"),
                "applied": [{"version": a["version_number"], "changes": len(a["changes"]), "failed": len(a.get("failed") or [])}
                            for a in applied],
                "undone_by_tool": any(e.get("type") == "edits_undone" for e in ev),
                "claims_undo": bool(re.search(r"\b(undone|reverted|rolled back)\b", msg["content"], re.I)),
                "no_change_note": "No change was made to the document" in msg["content"],
                "statements_removed": grounding.get("removed", 0),
                "cards_left": sum(1 for e in ev if e.get("type") == "edit_proposals"),
                "file": {"version": version, "tracked_markup": markup, **_structure(paras)},
                "message_id": msg["id"],
            })
        last = out["turns"][-1]
        if last["applied"]:
            r = c.post(f"/api/chat/sessions/{sid}/messages/{last['message_id']}/edits/undo", json={"document_id": doc_id})
            after_undo = _file(doc_id)[0]
            out["undo_last"] = {"status": r.status_code, "restores_exactly": after_undo == before_turn}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("document_id")
    ap.add_argument("member")
    ap.add_argument("--base", default="http://127.0.0.1:8021")
    a = ap.parse_args()
    print(json.dumps(run(a.document_id, a.member, a.base), indent=2, ensure_ascii=False))
