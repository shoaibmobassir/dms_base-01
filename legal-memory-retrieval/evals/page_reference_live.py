"""Live check: a page dragged into the Assistant is used as the page the lawyer means.

    python evals/page_reference_live.py DOC-... MEM-... [--base http://127.0.0.1:8021]

Sends "fix the numbering on this page" with the document attached and pointing at Part 1, through the real streaming
endpoint and model, then reads the stored answer: the Assistant should read the document and propose edit cards (not
ask which page or document), and its summary must not be cut up by "statements removed" (it reports its own actions).
"""
from __future__ import annotations

import argparse
import json

import httpx


def run(doc_id: str, member: str, base: str) -> dict:
    h = {"X-Member-Id": member}
    with httpx.Client(base_url=base, headers=h, timeout=280) as c:
        sid = c.post("/api/chat/sessions", json={}).json()["id"]
        body = {"content": "fix the numbering on this page, I want the actual change, not tracked changes",
                "files": [{"filename": "Employment Agreement - History check.docx", "document_id": doc_id,
                           "reference": {"unit": "part", "number": 1, "part_size": 5}}]}
        with c.stream("POST", f"/api/chat/sessions/{sid}/messages", json=body) as r:
            for _ in r.iter_lines():
                pass
        stored = c.get(f"/api/chat/sessions/{sid}").json()["messages"]
    answer = next(m for m in reversed(stored) if m["role"] == "assistant")
    groups = [e for e in answer.get("events") or [] if e.get("type") == "edit_proposals"]
    return {
        "session_id": sid,
        "answer": answer["content"],
        "statements_removed_note": "removed because the cited sources" in answer["content"],
        "edit_cards": [[(e["original"], e["proposed"]) for e in g.get("edits", [])] for g in groups],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("document_id")
    ap.add_argument("member")
    ap.add_argument("--base", default="http://127.0.0.1:8021")
    a = ap.parse_args()
    print(json.dumps(run(a.document_id, a.member, a.base), indent=2, ensure_ascii=False))
