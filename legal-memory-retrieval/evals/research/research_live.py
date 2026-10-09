"""Live research check through the running API (POST /api/chat, research mode).

    HF_HUB_OFFLINE=1 uvicorn app.api.main:app --port 8021      # no --reload
    python evals/research/research_live.py --base http://127.0.0.1:8021

For each held-out question: which research tools the assistant used, and a
cite-check of its final answer against the firm's collections. Any citation to
a held collection (PCIJ, UNSC) that does not verify is a fabricated or wrong
citation in a real answer.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.db.connection import connect  # noqa: E402
from app.research.legal_systems import Forum  # noqa: E402
from app.research.verify import verify_citations  # noqa: E402

MEMBER = "MEM-00001"
QUESTIONS = [
    ("q1", "What did the Security Council decide about non-State actors and weapons of mass destruction, and is that decision binding on States?",
     ["unsc:1540"]),
    ("q2", "Under the Permanent Court's case law, can restrictions on the independence of States be presumed?", ["pcij:A:10"]),
    ("q3", "Is an oral declaration by a foreign minister binding on his State? Give the controlling authority.", ["pcij:A/B:53"]),
    ("q4", "Has the Security Council referred situations to the International Criminal Court, and were those referrals binding?",
     ["unsc:1593", "unsc:1970"]),
    ("q5", "Cite-check this for me: S/RES/1540 (2004), para. 1; S/RES/1540 (2005); P.C.I.J., Series A, No. 10, p. 18; "
           "(2008) 4 SCC 755.", []),
    ("q6", "Is the UN mission in Hodeidah still mandated today? Use the Security Council resolutions.", ["unsc:2813"]),
]
RESEARCH_TOOLS = {"search_authority", "read_authority", "resolve_citation", "get_citing_authorities",
                  "check_authority_status", "verify_citations"}


def ask(client: httpx.Client, base: str, question: str) -> dict:
    sid = client.post(f"{base}/api/chat/sessions", json={"title": "research live eval"}).json()["id"]
    tools: list[str] = []
    final, grounding, err = "", None, None
    t = time.perf_counter()
    with client.stream("POST", f"{base}/api/chat/sessions/{sid}/messages",
                       json={"content": question, "mode": "research"}, timeout=400) as resp:
        for line in resp.iter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            ev = json.loads(line[6:])
            if ev.get("type") == "tool_started":
                tools.append(ev.get("tool") or ev.get("name") or "?")
            elif ev.get("type") == "text_final":
                final = ev.get("text") or ev.get("content") or ""
            elif ev.get("type") == "grounding":
                grounding = {k: ev.get(k) for k in ("supported", "removed", "claims", "status") if k in ev}
            elif ev.get("type") == "error":
                err = ev.get("message")
    return {"session": sid, "tools": tools, "final": final, "grounding": grounding, "error": err,
            "seconds": round(time.perf_counter() - t, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8021")
    ap.add_argument("--json")
    args = ap.parse_args()
    rows = []
    with httpx.Client(headers={"X-Member-Id": MEMBER}, timeout=60) as client, connect() as conn:
        for qid, question, expect in QUESTIONS:
            r = ask(client, args.base, question)
            check = verify_citations(conn, r["final"], MEMBER, forum=Forum("international"))
            held = [c for c in check["citations"] if c["key"].split(":")[0] in ("unsc", "pcij")]
            bad = [c["citation"] for c in held if c["verdict"] == "not_verified"]
            if qid == "q5":
                bad = []  # q5 quotes planted errors back on purpose; judged by its report below
            keys = {c["key"] for c in held}
            row = {"id": qid, "seconds": r["seconds"], "error": r["error"],
                   "research_tools": [t for t in r["tools"] if t in RESEARCH_TOOLS], "other_tools": [t for t in r["tools"] if t not in RESEARCH_TOOLS],
                   "authority_citations": len(held), "unverified_held_citations": bad,
                   "expected_cited": all(k in keys for k in expect),
                   "mentions_binding": any(w in r["final"].lower() for w in ("binding", "recommendatory", "persuasive")),
                   "mentions_status": "status" in r["final"].lower(),
                   "has_research_log": "research log" in r["final"].lower(),
                   "grounding": r["grounding"], "answer": r["final"]}
            rows.append(row)
            print(f"{qid}: {r['seconds']}s tools={row['research_tools']} cites={len(held)} unverified={bad} "
                  f"expected={row['expected_cited']} binding={row['mentions_binding']} status={row['mentions_status']} "
                  f"log={row['has_research_log']} err={r['error']}")
    summary = {
        "questions": len(rows),
        "used_research_tools": sum(bool(r["research_tools"]) for r in rows),
        "fabricated_or_wrong_held_citations": sum(len(r["unverified_held_citations"]) for r in rows),
        "expected_authority_cited": sum(r["expected_cited"] for r in rows if r["id"] != "q5"),
        "binding_explained": sum(r["mentions_binding"] for r in rows),
        "research_log": sum(r["has_research_log"] for r in rows),
    }
    print(json.dumps(summary, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, default=str))


if __name__ == "__main__":
    main()
