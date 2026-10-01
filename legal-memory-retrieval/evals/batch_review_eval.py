"""Batch review benchmark: many documents × several questions, over live HTTP (plan 15, C1).

Document sets are drawn from the Security Council resolutions in the corpus. Gold answers are
read from each document's own text by pattern, and a document is used only when its gold is
unambiguous (one resolution number, one adoption meeting, one adoption date):

  number   — "resolution 1234 (1998)" in the title
  meeting  — "at its 3549th meeting" / "at the 1243rd meeting"
  date     — "Resolution 212 (1965) of 20 September 1965" / "meeting, on 27 June 2023"

A screening task checks the zero-model pass: in a set where a few resolutions concern one
country, are those ranked first?

Metrics per set size: per-cell accuracy (overall and per question), not-found rate, quote
verified rate, time to first row, wall time, model calls; then a cached re-run's wall time.

    python evals/batch_review_eval.py --base-url http://127.0.0.1:8001 --sizes 100,300
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "evals"

QUESTIONS = {
    "number": "What is the resolution number?",
    "meeting": "At which Security Council meeting (its number) was the resolution adopted?",
    "date": "On what date was the resolution adopted?",
}
_MONTHS = {m: i for i, m in enumerate("january february march april may june july august september october november december".split(), 1)}
_NUM_RE = re.compile(r"resolution\s+(\d+)\s*\((\d{4})\)", re.I)
_MEETING_RE = re.compile(r"at (?:its|the) (\d[\d,]*)(?:st|nd|rd|th) meeting", re.I)
_DATE_RES = [
    re.compile(r"Resolution \d+ \(\d{4}\)\s+of (\d{1,2} [A-Z][a-z]+ \d{4})"),
    re.compile(r"meeting,? on (\d{1,2} [A-Z][a-z]+ \d{4})"),
]
_ANY_DATE = re.compile(r"(\d{1,2})\s+([A-Za-z]+)\s*,?\s+(\d{4})|(\d{4})-(\d{2})-(\d{2})|([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})")


def norm_date(text: str) -> str | None:
    for m in _ANY_DATE.finditer(text or ""):
        if m.group(1):
            mon = _MONTHS.get(m.group(2).lower())
            if mon:
                return f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"
        elif m.group(4):
            return f"{m.group(4)}-{m.group(5)}-{m.group(6)}"
        elif m.group(7):
            mon = _MONTHS.get(m.group(7).lower())
            if mon:
                return f"{m.group(9)}-{mon:02d}-{int(m.group(8)):02d}"
    return None


def gold_for(title: str, body: str) -> dict | None:
    body = " ".join((body or "").split())  # non-breaking spaces and line breaks would hide the adoption line
    num = _NUM_RE.search(title or "")
    meetings = {m.replace(",", "") for m in _MEETING_RE.findall(body or "")}
    dates = {norm_date(d) for r in _DATE_RES for d in r.findall(body or "")}
    if not num or len(meetings) != 1 or len(dates) != 1 or None in dates:
        return None
    return {"number": num.group(1), "meeting": meetings.pop(), "date": dates.pop()}


def correct(kind: str, answer: str, gold: str) -> bool:
    if not answer:
        return False
    if kind in ("number", "meeting"):
        return gold in re.findall(r"\d+", answer.replace(",", ""))[:2]
    return norm_date(answer) == gold


def load_candidates() -> tuple[list[dict], list[dict]]:
    """(documents with unambiguous gold, every resolution) — the second is the screening pool."""
    from app.db.connection import connect

    with connect() as conn:
        rows = conn.execute(
            "SELECT document_id, title, body FROM documents WHERE document_type = 'Security Council Resolution' ORDER BY document_id"
        ).fetchall()
    out = []
    for r in rows:
        g = gold_for(r["title"], r["body"])
        if g:
            out.append({"document_id": r["document_id"], "title": r["title"], "gold": g})
    return out, [{"document_id": r["document_id"], "title": r["title"]} for r in rows]


def run_full(client: httpx.Client, base: str, docs: list[dict], use_cache: bool) -> tuple[dict, float]:
    t = time.perf_counter()
    r = client.post(f"{base}/api/reviews/batch", json={
        "document_ids": [d["document_id"] for d in docs], "questions": list(QUESTIONS.values()),
        "use_cache": use_cache,
    })
    r.raise_for_status()
    return r.json(), time.perf_counter() - t


def score(resp: dict, docs: list[dict]) -> dict:
    gold = {d["document_id"]: d["gold"] for d in docs}
    per_q = {k: [0, 0] for k in QUESTIONS}
    not_found = verified = cells = 0
    misses: list[dict] = []
    for row in resp["rows"]:
        for kind, cell in zip(QUESTIONS, row["cells"]):
            cells += 1
            ok = correct(kind, cell["answer"], gold[row["document_id"]][kind])
            per_q[kind][0] += ok
            per_q[kind][1] += 1
            not_found += cell["not_found"]
            verified += cell["verified"]
            if not ok and len(misses) < 15:
                misses.append({"doc": row["document_id"], "q": kind, "answer": cell["answer"], "gold": gold[row["document_id"]][kind]})
    return {
        "documents": len(resp["rows"]),
        "cell_accuracy": round(sum(v[0] for v in per_q.values()) / max(1, cells), 4),
        "per_question": {k: round(v[0] / max(1, v[1]), 4) for k, v in per_q.items()},
        "not_found_rate": round(not_found / max(1, cells), 4),
        "quote_verified_rate": round(verified / max(1, cells), 4),
        "misses": misses,
    }


def screening(client: httpx.Client, base: str, pool: list[dict], rng: random.Random, size: int) -> dict:
    """Plant a handful of one country's resolutions in a set; are they ranked first?"""
    countries = ["Cyprus", "Somalia", "Haiti", "Lebanon", "Angola", "Sudan", "Iraq", "Liberia"]
    out = {}
    for country in countries[:4]:
        about = [d for d in pool if country.lower() in d["title"].lower()]
        other = [d for d in pool if not any(c.lower() in d["title"].lower() for c in countries)]
        if len(about) < 5:
            continue
        chosen = rng.sample(about, min(10, len(about))) + rng.sample(other, size - min(10, len(about)))
        rng.shuffle(chosen)
        r = client.post(f"{base}/api/reviews/batch", json={
            "document_ids": [d["document_id"] for d in chosen], "questions": [f"Does this resolution concern {country}?"],
            "mode": "screen",
        })
        r.raise_for_status()
        body = r.json()
        gold = {d["document_id"] for d in chosen if country.lower() in d["title"].lower()}
        top = [row["document_id"] for row in body["rows"][: len(gold)]]
        out[country] = {"gold": len(gold), "precision_at_gold": round(len(gold & set(top)) / len(gold), 3),
                        "ms": body["timings"]["total_ms"]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--sizes", default="100,300")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--member", default="MEM-00011")
    ap.add_argument("--tag", default="batch_review")
    args = ap.parse_args()

    pool, all_resolutions = load_candidates()
    rng = random.Random(args.seed)
    client = httpx.Client(headers={"X-Member-Id": args.member}, timeout=900)
    report: dict = {"candidates_with_gold": len(pool), "sizes": {}}
    for size in [int(s) for s in args.sizes.split(",")]:
        docs = rng.sample(pool, min(size, len(pool)))
        cold, cold_s = run_full(client, args.base_url, docs, use_cache=False)
        warm, warm_s = run_full(client, args.base_url, docs, use_cache=True)
        report["sizes"][size] = {
            **score(cold, docs),
            "wall_s": round(cold_s, 1), "first_row_s": round((cold["timings"].get("first_row_ms") or 0) / 1000, 1),
            "screen_ms": cold["timings"].get("screen_ms"), "model_calls": cold["stats"]["model_calls"],
            "errors": cold["stats"]["errors"],
            "cached_rerun_s": round(warm_s, 2), "cached_rows": warm["stats"]["cached"],
        }
        print(json.dumps({size: {k: v for k, v in report["sizes"][size].items() if k != "misses"}}), flush=True)
        (OUT / f"last_{args.tag}.json").write_text(json.dumps(report, indent=1))
    report["screening"] = screening(client, args.base_url, all_resolutions, rng, 200)
    print(json.dumps({"screening": report["screening"]}))
    (OUT / f"last_{args.tag}.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
