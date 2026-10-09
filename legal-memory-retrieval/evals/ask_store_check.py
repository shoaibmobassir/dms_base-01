"""Black-box check of Ask the Firm answer storage over HTTP (plan 19 §3)."""
import json
import sys
import time
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8021"  # a running API, no --reload
INSIDER = {"X-Member-Id": "MEM-00001"}
q = f"Appeal No. 163 of 2018, have we prepared a brief note of arguments? check {uuid.uuid4().hex[:8]}"


def stream(headers, body):
    t = time.perf_counter()
    events = []
    with httpx.stream("POST", f"{BASE}/api/answers/stream", headers=headers, json=body, timeout=300) as r:
        status = r.status_code
        for line in r.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                events.append(json.loads(line[6:]))
    return status, events, round(time.perf_counter() - t, 1)


def final(events):
    return next((e for e in events if e["type"] == "final"), None)


results = {}
st, ev, s1 = stream(INSIDER, {"query": q, "k": 10})
f1 = final(ev)
results["1 first ask"] = {"http": st, "seconds": s1, "types": sorted({e["type"] for e in ev}),
                          "saved_flag": f1 and f1.get("saved"), "saved_id": f1 and f1["result"].get("saved_id"),
                          "deltas": sum(e["type"] == "delta" for e in ev)}
sid = f1["result"].get("saved_id") if f1 else None

st, ev, s2 = stream(INSIDER, {"query": q, "k": 10})
f2 = final(ev)
results["2 same question again"] = {"http": st, "seconds": s2, "saved_flag": f2 and f2.get("saved"),
                                    "same_id": f2 and f2["result"].get("saved_id") == sid,
                                    "deltas": sum(e["type"] == "delta" for e in ev),
                                    "same_answer": f2 and f1 and f2["result"]["answer"] == f1["result"]["answer"]}

with httpx.Client(base_url=BASE, headers=INSIDER, timeout=60) as c:
    r = c.get(f"/api/answers/saved/{sid}")
    body = r.json() if r.status_code == 200 else {}
    results["3 GET by id"] = {"http": r.status_code, "has_answer": bool(body.get("answer")), "has_panel": bool(body.get("panel")),
                              "citations": len(body.get("citations") or []), "query_echoed": body.get("query") == q}
    r = c.get("/api/answers/history?limit=50")
    items = r.json().get("items", []) if r.status_code == 200 else []
    mine = next((i for i in items if i.get("id") == sid), None)
    results["4 history lists the id"] = {"http": r.status_code, "found": bool(mine), "keys": sorted(mine) if mine else None}
    r = c.get("/api/answers/saved", params={"q": q})
    results["5 GET by query (legacy)"] = {"http": r.status_code}
    r = c.get("/api/answers/saved/does-not-exist")
    results["6 unknown id"] = {"http": r.status_code}

    # ACL: an answer saved for one member must not open for another, even with the id.
    r = httpx.get(f"{BASE}/api/answers/saved/{sid}", headers={"X-Member-Id": "MEM-00002"}, timeout=30)
    results["7 other member opens my id"] = {"http": r.status_code, "leaked_answer": r.status_code == 200 and bool(r.json().get("answer"))}

    # Refresh recomputes and keeps working.
    st, ev, s3 = stream(INSIDER, {"query": q, "k": 10, "refresh": True})
    f3 = final(ev)
    results["8 refresh=true"] = {"http": st, "seconds": s3, "saved_flag": f3 and f3.get("saved"),
                                 "deltas": sum(e["type"] == "delta" for e in ev), "id_after": f3 and f3["result"].get("saved_id")}

    # Non-streaming API must behave the same.
    r = c.post("/api/answers", json={"query": q, "k": 10})
    j = r.json() if r.status_code == 200 else {}
    results["9 POST /api/answers"] = {"http": r.status_code, "saved": j.get("saved"), "saved_id": j.get("saved_id")}

    # Cleanup so the test leaves no rows behind.
    if sid:
        c.delete(f"/api/answers/history/{sid}")
    r = c.get(f"/api/answers/saved/{sid}")
    results["10 deleted id gone"] = {"http": r.status_code}

print(json.dumps(results, indent=2, default=str))
