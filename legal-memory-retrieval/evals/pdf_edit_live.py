"""Live check: ask the Assistant to improve a real PDF and list what it proposes.

    OBJECT_STORE_ROOT=<data/object_store> uvicorn app.api.main:app --port 8021     # no --reload
    python evals/pdf_edit_live.py --base http://127.0.0.1:8021 --runs 3

Reproduces the report that the Assistant "corrected" `knowledgeand` -> `knowledge and` in a PDF whose printed page is
fine. For each run it prints every edit card, flags cards that change only spacing or one letter, and says whether the
answer calls spacing an error.
"""
from __future__ import annotations

import argparse
import json
import re
import time

import httpx

DOC = "DOC-F5E089EA53"
NAME = "Rejoinder to reply of IA.pdf"
PROMPT = "Suggest edits that improve this document. Show them as tracked changes I can accept or reject."
SPACE_WORDS = re.compile(r"knowledge\s*and|missing space|extra space|spacing|whitespace", re.I)
# Reading artifacts of the scanned page 16 (the Verification), which the printed page does not have.
ARTIFACTS = re.compile(r"knowledgeand|thcrein", re.I)
# Real defects on the born-digital pages: the tribunal name is spelled "ELECTRCITY" on pages 1-2, and "the
# Electricity, 2003" lacks "Act" on page 3. Finding them is what a good review should do.
REAL = re.compile(r"ELECTRCITY|Electricity, 2003|Electricity Act", re.I)


def squash(s: str) -> str:
    return re.sub(r"\s+|­", "", s).lower()


def run(client: httpx.Client, base: str) -> dict:
    sid = client.post(f"{base}/api/chat/sessions", json={"title": "pdf edit live check"}).json()["id"]
    events, final = [], ""
    t = time.perf_counter()
    with client.stream("POST", f"{base}/api/chat/sessions/{sid}/messages", timeout=400,
                       json={"content": PROMPT, "mode": "review",
                             "files": [{"filename": NAME, "document_id": DOC, "content_type": "application/pdf"}]}) as r:
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                try:
                    ev = json.loads(line[6:])
                except ValueError:
                    continue
                events.append(ev)
                if ev.get("type") == "text_final":
                    final = ev.get("text", "")
    cards = [e for ev in events if ev.get("type") == "edit_proposals" for e in ev.get("edits", [])]
    read_only = [ev.get("read_only") for ev in events if ev.get("type") == "edit_proposals"]
    spacing_cards = [c for c in cards if squash(c["original"]) == squash(c["proposed"])]
    tools = [ev.get("tool") for ev in events if ev.get("type") == "tool_started"]
    return {"session": sid, "seconds": round(time.perf_counter() - t, 1), "tools": tools, "cards": cards,
            "read_only": read_only, "spacing_cards": spacing_cards, "final": final,
            "answer_mentions_spacing": bool(SPACE_WORDS.search(final)),
            "artifact_claims": sorted({m.group(0).lower() for m in ARTIFACTS.finditer(final)}),
            "real_defect_found": bool(REAL.search(final))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8021")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--json")
    args = ap.parse_args()
    results = []
    with httpx.Client(headers={"X-Member-Id": "MEM-00001"}, timeout=60) as client:
        for i in range(args.runs):
            r = run(client, args.base)
            results.append(r)
            print(f"\n--- run {i + 1}: {r['seconds']}s, tools={r['tools']}, cards={len(r['cards'])}, read_only={r['read_only']}, "
                  f"spacing-only cards={len(r['spacing_cards'])}, artifact claims in prose={r['artifact_claims']}, "
                  f"found a real defect={r['real_defect_found']}")
            for c in r["cards"]:
                print(f"   p{c.get('page')}: {c['original'][:70]!r} -> {c['proposed'][:70]!r}")
            print("   answer:", r["final"][:600].replace("\n", " "))
    summary = {"runs": len(results), "spacing_only_cards": sum(len(r["spacing_cards"]) for r in results),
               "cards_total": sum(len(r["cards"]) for r in results),
               "answers_with_artifact_claims": sum(bool(r["artifact_claims"]) for r in results),
               "answers_finding_a_real_defect": sum(r["real_defect_found"] for r in results)}
    print("\n", json.dumps(summary))
    if args.json:
        with open(args.json, "w") as fh:
            json.dump({"summary": summary, "runs": results}, fh, indent=2, default=str)


if __name__ == "__main__":
    main()
