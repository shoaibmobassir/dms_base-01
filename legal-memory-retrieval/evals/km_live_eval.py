"""Ask-the-Firm KM eval through the real HTTP stack.

Unlike the retrieval benchmarks (which call ``retrieve()`` in-process), this
posts to ``/api/answers`` exactly as the UI does, so connection-pool,
event-loop, scope-parsing, context-packing and LLM-grounding failures all
show up. Answers are graded against gold built from Postgres by
``evals/build_km_live.py``.

Usage:
    python evals/km_live_eval.py --base-url http://localhost:8000
    python evals/km_live_eval.py --inproc                 # FastAPI TestClient
    python evals/km_live_eval.py --scope-mode prefix      # legacy "CODE: q" form
    python evals/km_live_eval.py --only scoped_fact,negative --workers 4
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DATASET = Path(__file__).with_name("km_live.jsonl")
SLOW_CHANNEL_MS = 5000.0
_NO_MATCH_RE = re.compile(
    r"no (matching )?(matter|record|document)s?|could not (find|locate|identify)|"
    r"not (find|locate|identify) any|does not appear|no .{0,40}in (the|your) (accessible )?records",
    re.I,
)


def _tokens(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"(?<=\d),(?=\d)", "", text.lower())
    return " " + " ".join(re.sub(r"[^a-z0-9]+", " ", text).split()) + " "


_NUMBER_WORDS = {str(i): w for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}


def contains(haystack: str, needle: str) -> bool:
    n = _tokens(needle).strip()
    hay = _tokens(haystack)
    if n in _NUMBER_WORDS and f" {_NUMBER_WORDS[n]} " in hay:  # "5" ≙ "five"
        return True
    return bool(n) and f" {n} " in hay


def person_mentioned(haystack: str, name: str) -> bool:
    parts = _tokens(name).split()
    return bool(parts) and (contains(haystack, name) or contains(haystack, parts[-1]))


class Client:
    def __init__(self, base_url: str | None, inproc: bool):
        self.base_url = (base_url or "").rstrip("/")
        self._tc = None
        if inproc:
            from dotenv import load_dotenv

            load_dotenv(ROOT / ".env")
            from fastapi.testclient import TestClient

            from app.api.main import app

            self._tc = TestClient(app)

    def ask(self, body: dict, member: str, timeout: float) -> tuple[int, dict]:
        headers = {"content-type": "application/json", "X-Member-Id": member}
        if self._tc is not None:
            for _ in range(8):
                r = self._tc.post("/api/answers", json=body, headers=headers)
                if r.status_code != 429:
                    break
                time.sleep(float(r.headers.get("retry-after") or 8))
            return r.status_code, (r.json() if r.content else {})
        import httpx

        for _ in range(8):  # the ask endpoint is rate limited per member; back off on 429
            r = httpx.post(f"{self.base_url}/api/answers", json=body, headers=headers, timeout=timeout)
            if r.status_code != 429:
                break
            time.sleep(float(r.headers.get("retry-after") or 8))
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"raw": r.text[:500]}


def build_body(row: dict, scope_mode: str) -> dict:
    scope = row.get("scope")
    body: dict = {"query": row["query"], "k": 10}
    if scope:
        if scope_mode == "prefix":
            body["query"] = f"{scope['value']}: {row['query']}"
        else:
            body["scope"] = scope
    return body


def response_matters(resp: dict) -> tuple[list[str], list[str]]:
    lat = resp.get("latency_ms") or {}
    ms = lat.get("matter_scope") if isinstance(lat.get("matter_scope"), dict) else {}
    resolved = list((resp.get("resolved_scope") or {}).get("matter_ids") or ms.get("matter_ids") or [])
    seen: list[str] = []
    for h in resp.get("hits") or []:
        mid = h.get("matter_id")
        if mid and mid not in seen:
            seen.append(mid)
    for m in resp.get("matchedMatters") or []:
        mid = m.get("matter_id")
        if mid and mid not in seen:
            seen.append(mid)
    return resolved, seen


def grade(row: dict, status: int, resp: dict) -> dict:
    answer = " ".join(
        str(resp.get(k) or "") for k in ("key_finding", "answer")
    )
    people_txt = " ".join(
        f"{p.get('name', '')} {p.get('role', '')}" for p in (resp.get("people") or [])
    )
    provider = str(resp.get("provider") or "")
    grounded = status == 200 and not resp.get("abstained") and not provider.startswith("extractive") and provider != "none"
    resolved, seen = response_matters(resp)
    lat = resp.get("latency_ms") or {}
    # Retrieval stalls: engine channel timeouts, or evidence gathering (DB + ranking,
    # excluding the LLM) over the threshold. Legacy responses expose raw channel timers.
    engine = lat.get("engine") if isinstance(lat.get("engine"), dict) else {}
    slow = list(lat.get("channel_timeouts") or engine.get("channel_timeouts") or [])
    if isinstance(lat.get("evidence_ms"), (int, float)) and lat["evidence_ms"] > SLOW_CHANNEL_MS:
        slow.append("evidence_ms")
    if "evidence_ms" not in lat:
        slow += sorted(
            k for k, v in lat.items()
            if isinstance(v, (int, float)) and not k.endswith("_count")
            and k not in {"llm", "parallel_wall_ms", "total_ms", "llm_ms"} and v > SLOW_CHANNEL_MS
        )
    checks: dict[str, bool] = {"http_200": status == 200}
    cat = row["category"]

    if "gold_matter" in row:
        top = seen[0] if seen else None
        checks["matter"] = row["gold_matter"] in resolved or top == row["gold_matter"]
    if cat in {"scoped_overview", "scoped_fact", "people_on_matter", "lead_unscoped", "paraphrase_lowercase", "client_matters", "people_expertise"}:
        checks["grounded"] = grounded
    if row.get("gold_all"):
        checks["facts_all"] = all(contains(answer, g) for g in row["gold_all"])
    if row.get("gold_any"):
        checks["facts_any"] = any(g and contains(answer, g) for g in row["gold_any"])
    if row.get("gold_people"):
        found = [p for p in row["gold_people"] if person_mentioned(answer + " " + people_txt, p)]
        recall = len(found) / len(row["gold_people"])
        checks["people"] = recall >= (0.75 if len(row["gold_people"]) > 2 else 1.0)
    if row.get("gold_matters_any"):
        gold = row["gold_matters_any"]
        hit = [m for m in gold if m in seen or m in resolved]
        checks["matters_recall"] = len(hit) / len(gold) >= 0.8
    if cat == "negative":
        checks["clean_negative"] = bool(resp.get("abstained")) or bool(_NO_MATCH_RE.search(answer)) or resp.get("reason") == "no_matching_matter"
        checks["no_dump"] = not provider.startswith("extractive")
    if cat == "ethical_wall":
        forbidden = row["forbidden_matter"]
        leaked = forbidden in seen or forbidden in resolved or forbidden in json.dumps(resp.get("people") or [])
        checks["no_leak"] = not leaked
    checks["no_slow_channel"] = not slow

    return {
        "id": row["id"],
        "category": cat,
        "query": row["query"],
        "pass": all(checks.values()),
        "checks": checks,
        "provider": provider,
        "reason": resp.get("reason"),
        "resolved": resolved,
        "top_matters": seen[:5],
        "slow_channels": slow,
        "latency": {k: lat.get(k) for k in ("scope_ms", "resolver_ms", "evidence_ms", "llm_ms", "total_ms") if k in lat},
        "answer": answer[:400],
    }


def run(args) -> dict:
    rows = [json.loads(line) for line in args.dataset.read_text().splitlines() if line.strip()]
    if args.only:
        wanted = set(args.only.split(","))
        rows = [r for r in rows if r["category"] in wanted or r["id"] in wanted]
    if args.limit:
        rows = rows[: args.limit]
    client = Client(args.base_url, args.inproc)

    def one(row: dict) -> dict:
        t0 = time.perf_counter()
        try:
            status, resp = client.ask(build_body(row, args.scope_mode), row.get("as_member", "MEM-00011"), args.timeout)
        except Exception as exc:  # network / server crash is a failure, not a skip
            status, resp = 0, {"error": repr(exc)}
        out = grade(row, status, resp)
        out["seconds"] = round(time.perf_counter() - t0, 2)
        if args.verbose:
            mark = "PASS" if out["pass"] else "FAIL"
            failed = [k for k, v in out["checks"].items() if not v]
            print(f"{mark} {out['seconds']:>5}s {row['id']:<28} {failed} {out['provider']} :: {out['answer'][:110]!r}", flush=True)
        return out

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        results = list(pool.map(one, rows))

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)
    secs = sorted(r["seconds"] for r in results)

    def pct(p: float) -> float:
        return secs[min(len(secs) - 1, int(round(p * (len(secs) - 1))))] if secs else 0.0

    summary = {
        "n": len(results),
        "pass_rate": round(sum(r["pass"] for r in results) / max(1, len(results)), 4),
        "p50_s": pct(0.5),
        "p95_s": pct(0.95),
        "mean_s": round(statistics.fmean(secs), 2) if secs else 0.0,
        "scope_mode": args.scope_mode,
        "categories": {
            c: {
                "n": len(rs),
                "pass_rate": round(sum(r["pass"] for r in rs) / len(rs), 4),
                "check_fail_counts": {
                    k: sum(1 for r in rs if k in r["checks"] and not r["checks"][k])
                    for k in sorted({k for r in rs for k in r["checks"]})
                },
            }
            for c, rs in sorted(by_cat.items())
        },
    }
    return {"summary": summary, "results": results}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--inproc", action="store_true")
    ap.add_argument("--dataset", type=Path, default=DATASET)
    ap.add_argument("--scope-mode", choices=["structured", "prefix"], default="structured")
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--out", type=Path, default=Path(__file__).with_name("last_km_live.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    report = run(args)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
