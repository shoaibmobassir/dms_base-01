"""Prepare LegalBench-RAG as a separate benchmark database (plan 14, A2).

LegalBench-RAG (arXiv 2408.10343) ships ``corpus/`` (raw .txt contracts and policies from
ContractNLI, CUAD, MAUD and PrivacyQA) and ``benchmarks/*.json`` (queries with gold
character spans). This script:

  1. converts it to our corpus format (one client, one matter per sub-corpus, one member)
     plus ``queries.jsonl`` and ``doc_map.json`` for the eval;
  2. with ``--load``, creates a *separate* database and runs ingest → migrate → embed there.

It never touches the firm database: ``scripts/ingest.py`` starts with DROP TABLE, so the
target database name must contain "bench" and differ from the configured firm database.

Licence gate: record the four source datasets in docs/legal/DEPENDENCY_AUDIT.md and get
approval before downloading. The data stays under data/benchmarks/ (git-ignored), never in
the firm corpus.

    python evals/legalbench_rag_prepare.py --data-dir data/benchmarks/legalbenchrag \\
        --out data/benchmarks/legalbenchrag_prepared --per-benchmark 194 --load
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MEMBER = "MEM-LB-0001"
CLIENT = "CLI-LB-0001"
BENCH_DB = "legalbench_rag"
BENCH_REDIS_DB = 9  # the retrieval cache key does not include the database; keep caches apart


def load_tests(bench_dir: Path) -> dict[str, list[dict]]:
    """{benchmark name: [{"query", "snippets": [{"file_path", "span": [s, e]}]}]}"""
    out: dict[str, list[dict]] = {}
    for path in sorted(bench_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        tests = data.get("tests") if isinstance(data, dict) else data
        out[path.stem] = [
            {"query": t["query"],
             "snippets": [{"file_path": s["file_path"], "span": [int(s["span"][0]), int(s["span"][1])]}
                          for s in t.get("snippets") or []]}
            for t in tests or [] if t.get("query") and t.get("snippets")
        ]
    return out


def sample(tests: dict[str, list[dict]], per_benchmark: int, seed: int) -> dict[str, list[dict]]:
    if per_benchmark <= 0:
        return tests
    rng = random.Random(seed)
    return {name: (rng.sample(rows, per_benchmark) if len(rows) > per_benchmark else rows)
            for name, rows in tests.items()}


def build(data_dir: Path, out: Path, per_benchmark: int, seed: int, corpus_scope: str) -> dict:
    corpus = data_dir / "corpus"
    tests = sample(load_tests(data_dir / "benchmarks"), per_benchmark, seed)
    wanted: set[str] | None = None
    if corpus_scope == "referenced":
        # The "mini" setting: only documents some sampled query points at (easier; report it as such).
        wanted = {s["file_path"] for rows in tests.values() for t in rows for s in t["snippets"]}
    files = sorted(p.relative_to(corpus).as_posix() for p in corpus.rglob("*.txt"))
    if wanted is not None:
        files = [f for f in files if f in wanted]

    groups = sorted({f.split("/", 1)[0] for f in files})
    matter_of = {g: f"MTR-LB-{i + 1:04d}" for i, g in enumerate(groups)}
    matters = [{
        "matter_id": mid, "matter_code": f"LB/{g.upper()}", "title": f"LegalBench-RAG — {g}",
        "client_id": CLIENT, "client_name": "LegalBench-RAG", "practice_area": "Benchmark",
        "matter_type": "Benchmark corpus", "status": "Open",
        "matter_members": [{"member_id": MEMBER, "role_on_matter": "Reviewer"}],
    } for g, mid in matter_of.items()]

    out.mkdir(parents=True, exist_ok=True)
    doc_map: dict[str, str] = {}
    with (out / "documents.jsonl").open("w", encoding="utf-8") as fh:
        for i, rel in enumerate(files, 1):
            doc_id = f"DOC-LB-{i:06d}"
            doc_map[doc_id] = rel
            fh.write(json.dumps({
                "document_id": doc_id, "matter_id": matter_of[rel.split("/", 1)[0]], "client_id": CLIENT,
                "title": Path(rel).stem.replace("_", " "), "document_type": "Contract", "status": "Final",
                "source_path": rel, "text": (corpus / rel).read_text(encoding="utf-8"),
            }, ensure_ascii=False) + "\n")

    def dump(name: str, obj) -> None:
        (out / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")

    dump("members.json", [{"member_id": MEMBER, "name": "Benchmark Reviewer", "role": "Associate",
                           "practice_areas": ["Benchmark"], "is_lawyer": True}])
    dump("clients.json", [{"client_id": CLIENT, "name": "LegalBench-RAG", "industry": "Benchmark"}])
    dump("matters.json", matters)
    dump("permissions.json", [{"matter_id": m["matter_id"], "classification": "Benchmark", "restricted": False,
                               "allowed_members": [MEMBER], "practice_area": "Benchmark"} for m in matters])
    dump("doc_map.json", doc_map)
    for name in ("relationships.jsonl", "arguments.jsonl"):
        (out / name).write_text("", encoding="utf-8")
    kept_files = set(files)
    with (out / "queries.jsonl").open("w", encoding="utf-8") as fh:
        n = 0
        for bench, rows in tests.items():
            for j, t in enumerate(rows):
                if all(s["file_path"] in kept_files for s in t["snippets"]):
                    n += 1
                    fh.write(json.dumps({"id": f"{bench}-{j:04d}", "benchmark": bench, **t}, ensure_ascii=False) + "\n")
    return {"documents": len(files), "matters": len(matters), "queries": n,
            "per_benchmark": {b: len(r) for b, r in tests.items()}, "corpus_scope": corpus_scope}


def bench_urls(firm_db_url: str, redis_url: str) -> tuple[str, str]:
    """The benchmark database and Redis cache URLs next to the firm ones."""
    db = urlparse(firm_db_url)
    if BENCH_DB == db.path.lstrip("/"):
        raise SystemExit("benchmark database name collides with the firm database")
    r = urlparse(redis_url)
    return urlunparse(db._replace(path=f"/{BENCH_DB}")), urlunparse(r._replace(path=f"/{BENCH_REDIS_DB}"))


def assert_bench_env(db_url: str, firm_db_url: str) -> None:
    name = urlparse(db_url).path.lstrip("/")
    if "bench" not in name or name == urlparse(firm_db_url).path.lstrip("/"):
        raise SystemExit(f"refusing to run against database {name!r}: benchmark databases must contain 'bench'")


def load(out: Path) -> None:
    import psycopg

    from app.config import settings

    db_url, redis_url = bench_urls(settings.database_url, settings.redis_url)
    assert_bench_env(db_url, settings.database_url)
    admin = urlunparse(urlparse(settings.database_url)._replace(path="/postgres"))
    with psycopg.connect(admin, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (BENCH_DB,)).fetchone():
            conn.execute(f'CREATE DATABASE "{BENCH_DB}"')
    env = {**os.environ, "DATABASE_URL": db_url, "REDIS_URL": redis_url, "CORPUS_DIR": str(out.resolve())}
    for script in ("scripts/ingest.py", "scripts/migrate.py", "scripts/embed.py"):
        print(f"→ {script} on {BENCH_DB}", flush=True)
        subprocess.run([sys.executable, str(ROOT / script)], cwd=ROOT, env=env, check=True)
    print(f"loaded. Run the eval with:\n  DATABASE_URL={db_url} REDIS_URL={redis_url} "
          f"python evals/legalbench_rag_eval.py --prepared {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True, help="folder holding corpus/ and benchmarks/")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--per-benchmark", type=int, default=0, help="sample N queries per benchmark (0 = all)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--corpus", choices=("full", "referenced"), default="full",
                    help="full corpus (default, harder) or only documents the sampled queries reference")
    ap.add_argument("--load", action="store_true", help="create the benchmark DB and ingest + embed into it")
    args = ap.parse_args()
    print(json.dumps(build(args.data_dir, args.out, args.per_benchmark, args.seed, args.corpus), indent=1))
    if args.load:
        load(args.out)


if __name__ == "__main__":
    main()
