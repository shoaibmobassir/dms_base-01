"""Live replay of the reported conversation on a copy of the CTO agreement, then Accept all, then read the Word file.

    python evals/history_ui_fixture.py copy DOC-7405413EC8 --member MEM-00001     -> a throwaway copy
    python evals/cto_live_flow.py DOC-<copy> MEM-00001 [--base http://127.0.0.1:8021] [--reference]

Turn 1 and turn 2 are the lawyer's own words from the report. Checks, per turn: did the Assistant propose edit cards,
quote text that is in the file, keep its prose whole (no "statements removed"); then: does accepting change the file,
with no tracked changes or struck-through text left in it.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TURNS = [
    "fix this page 9 i dont wat to keep track of changes but actual change",
    "fix this part, i not want crossed answers changes , just the original answers",
]


def _file_paragraphs(doc_id: str) -> tuple[list[str], bool]:
    from docx import Document
    from docx.oxml.ns import qn

    from app.db.connection import connect
    from app.storage.object_store import get_object_store

    with connect() as conn:
        uri = conn.execute("SELECT v.storage_uri FROM documents d JOIN document_versions v ON v.version_id = d.current_version_id "
                           "WHERE d.document_id = %s", (doc_id,)).fetchone()["storage_uri"]
    d = Document(io.BytesIO(get_object_store().get(uri)))
    body = d.element.body
    return [p.text for p in d.paragraphs], bool(list(body.iter(qn("w:ins"))) or list(body.iter(qn("w:del"))))


def run(doc_id: str, member: str, base: str, reference: bool) -> dict:
    h = {"X-Member-Id": member}
    before, _ = _file_paragraphs(doc_id)
    out: dict = {"before": [p for p in before if p[:2].strip(". ").isdigit() or p.isupper()]}
    with httpx.Client(base_url=base, headers=h, timeout=300) as c:
        sid = c.post("/api/chat/sessions", json={}).json()["id"]
        out["session_id"] = sid
        turns = []
        for i, text in enumerate(TURNS):
            body: dict = {"content": text}
            if i == 0:
                att = {"filename": "Employment Agreement - CTO.docx", "document_id": doc_id}
                if reference:
                    att["reference"] = {"unit": "part", "number": 1, "part_size": 5}
                body["files"] = [att]
            with c.stream("POST", f"/api/chat/sessions/{sid}/messages", json=body) as r:
                for _ in r.iter_lines():
                    pass
            msg = [m for m in c.get(f"/api/chat/sessions/{sid}").json()["messages"] if m["role"] == "assistant"][-1]
            groups = [e for e in msg.get("events") or [] if e.get("type") == "edit_proposals"]
            edits = [e for g in groups for e in g.get("edits", [])]
            turns.append({
                "user": text,
                "answer": msg["content"],
                "statements_removed": "removed because the cited sources" in msg["content"],
                "cards": [(e["original"], e["proposed"]) for e in edits],
                "cards_quoting_text_not_in_file": [e["original"] for e in edits if e["original"] and not any(e["original"] in p for p in before)],
                "message_id": msg["id"],
                "groups": groups,
            })
        out["turns"] = [{k: v for k, v in t.items() if k != "groups"} for t in turns]

        # Accept all on the last answer that proposed edits, the way the card's button does.
        last = next((t for t in reversed(turns) if t["groups"]), None)
        if last:
            for g in last["groups"]:
                r = c.patch(f"/api/chat/sessions/{sid}/messages/{last['message_id']}/edits",
                            json={"status": "accepted", "document_id": g["document_id"]})
                out.setdefault("accept", []).append({"status": r.status_code, **({k: r.json().get(k) for k in ("updated", "failed", "version_number")}
                                                                                if r.status_code == 200 else {"detail": r.text[:200]})})
    after, markup = _file_paragraphs(doc_id)
    out["after"] = [p for p in after if p[:2].strip(". ").isdigit() or p.isupper()]
    out["file_changed"] = after != before
    out["tracked_changes_in_file"] = markup
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("document_id")
    ap.add_argument("member")
    ap.add_argument("--base", default="http://127.0.0.1:8021")
    ap.add_argument("--reference", action="store_true", help="attach the page as a dragged reference (Part 1)")
    ap.add_argument("--follow-up", help="a third turn, e.g. the lawyer answering the Assistant's question")
    a = ap.parse_args()
    if a.follow_up:
        TURNS.append(a.follow_up)
    print(json.dumps(run(a.document_id, a.member, a.base, a.reference), indent=2, ensure_ascii=False))
