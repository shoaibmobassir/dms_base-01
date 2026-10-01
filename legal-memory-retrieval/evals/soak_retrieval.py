"""Soak the live retrieval endpoint and watch Postgres connections.

Regression check for the stranded-connection bug: sync endpoints used to run
the async engine with a fresh asyncio.run() loop per request against a pool
bound to another loop, so connections leaked until channels stalled for the
30 s pool timeout. This hammers POST /api/retrieval sequentially and
concurrently and fails if any request is slow, any channel times out, or the
server's connection count keeps growing.

    python evals/soak_retrieval.py --base-url http://localhost:8000 --sequential 200 --concurrent 20
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

TERMS = ["jurisdiction", "treaty", "reparation", "mandate", "sanctions", "boundary", "canal", "minority",
         "tariff", "petition", "indemnity", "warranty", "arbitration", "advisory", "resolution", "closing"]


def pg_connections(container: str) -> int:
    out = subprocess.run(
        ["docker", "exec", container, "psql", "-U", "legal", "-d", "legal_memory", "-At", "-c",
         "SELECT count(*) FROM pg_stat_activity WHERE datname = 'legal_memory'"],
        capture_output=True, text=True, check=False,
    )
    try:
        return int(out.stdout.strip())
    except ValueError:
        return -1


def one(base: str, i: int, member: str) -> tuple[float, int, list[str]]:
    q = f"{TERMS[i % len(TERMS)]} {TERMS[(i * 7) % len(TERMS)]} {i}"  # unique → bypasses the cache
    t0 = time.perf_counter()
    for _ in range(6):
        r = httpx.post(f"{base}/api/retrieval", json={"query": q, "k": 10},
                       headers={"X-Member-Id": member}, timeout=120)
        if r.status_code != 429:
            break
        time.sleep(float(r.headers.get("retry-after") or 5))
    dt = time.perf_counter() - t0
    timeouts: list[str] = []
    if r.status_code == 200:
        lat = r.json().get("latency_ms") or {}
        timeouts = list(lat.get("channel_timeouts") or [])
    return dt, r.status_code, timeouts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--sequential", type=int, default=200)
    ap.add_argument("--concurrent", type=int, default=20)
    ap.add_argument("--rounds", type=int, default=5, help="concurrent bursts")
    ap.add_argument("--container", default="legal-memory-retrieval-postgres-1")
    ap.add_argument("--max-seconds", type=float, default=15.0)
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    members = [f"MEM-{n:05d}" for n in range(1, 17)]  # spread over members: the endpoint is rate limited per member

    conn_before = pg_connections(args.container)
    results: list[tuple[float, int, list[str]]] = []
    conns: list[int] = []
    for i in range(args.sequential):
        results.append(one(base, i, members[i % len(members)]))
        if i % 25 == 0:
            conns.append(pg_connections(args.container))
    with ThreadPoolExecutor(max_workers=args.concurrent) as pool:
        for r in range(args.rounds):
            start = 10_000 + r * args.concurrent
            results += list(pool.map(lambda i: one(base, i, members[i % len(members)]), range(start, start + args.concurrent)))
            conns.append(pg_connections(args.container))
    conn_after = pg_connections(args.container)

    secs = sorted(r[0] for r in results)
    bad_status = [r[1] for r in results if r[1] != 200]
    timeouts = [t for r in results for t in r[2]]
    report = {
        "requests": len(results),
        "p50_s": round(statistics.median(secs), 3),
        "p95_s": round(secs[int(0.95 * (len(secs) - 1))], 3),
        "max_s": round(secs[-1], 3),
        "non_200": len(bad_status),
        "channel_timeouts": len(timeouts),
        "pg_connections": {"before": conn_before, "after": conn_after, "max_seen": max(conns + [conn_after])},
    }
    print(json.dumps(report, indent=2))
    ok = not bad_status and not timeouts and secs[-1] <= args.max_seconds and report["pg_connections"]["max_seen"] < 90
    print("SOAK", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
