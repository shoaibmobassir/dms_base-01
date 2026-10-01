#!/usr/bin/env python3
"""Logical backup and a verified restore drill.

    python scripts/backup.py backup --out backups/            # db.dump + objects.tar.gz + manifest.json
    python scripts/backup.py restore-drill --from backups/<stamp>

``restore-drill`` restores into a scratch database, then checks the restored copy
against the manifest: row counts of the core tables, the audit hash chain (intact
and ending at the same head), and the SHA-256 of every stored original. It prints
the elapsed time (evidence for the RTO in docs/runbooks/backup-restore.md), drops
the scratch database, and exits non-zero on any mismatch.

On a managed database (RDS/Aurora, Azure Flexible Server) automated snapshots and
point-in-time recovery are the primary backup; this script is the logical copy and
the rehearsal. Postgres client tools must match the server's major version: if the
local ones are older, the script runs them inside the Compose ``postgres`` container.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import psycopg
from psycopg.rows import dict_row

from app.audit.events import verify_chain
from app.config import settings

CORE_TABLES = (
    "members", "clients", "matters", "permissions", "documents", "document_versions",
    "chunks", "court_deadlines", "client_notes", "chat_sessions", "chat_messages",
    "audit_events", "api_keys", "upload_batches",
)


def _conninfo(dbname: str | None = None) -> str:
    url = urlparse(settings.database_url)
    return url._replace(path=f"/{dbname}").geturl() if dbname else settings.database_url


def _server_major() -> int:
    with psycopg.connect(settings.database_url) as conn:
        return int(conn.execute("SHOW server_version_num").fetchone()[0]) // 10000


def _local_major() -> int:
    if not shutil.which("pg_dump"):
        return 0
    out = subprocess.run(["pg_dump", "--version"], capture_output=True, text=True).stdout
    match = re.search(r"\b(\d+)\.\d+", out)  # "pg_dump (PostgreSQL) 14.20 (Homebrew)"
    return int(match.group(1)) if match else 0


def _container() -> str | None:
    out = subprocess.run(["docker", "compose", "ps", "-q", "postgres"], cwd=ROOT, capture_output=True, text=True)
    return out.stdout.strip() or None


def _pg(tool: str, args: list[str], *, stdin=None, stdout=None) -> None:
    """Run a Postgres client tool locally if its version fits, else inside the container."""
    url = urlparse(settings.database_url)
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    if _local_major() >= _server_major():
        cmd = [tool, "-h", url.hostname or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres", *args]
    else:
        container = os.environ.get("PG_CONTAINER") or _container()
        if not container:
            raise SystemExit(f"local {tool} is older than the server and no postgres container was found")
        cmd = ["docker", "exec", "-i", "-e", f"PGPASSWORD={url.password or ''}", container, tool,
               "-U", url.username or "postgres", *args]
    subprocess.run(cmd, stdin=stdin, stdout=stdout, env=env, check=True)


def _counts(conninfo: str) -> dict[str, int]:
    with psycopg.connect(conninfo) as conn:
        out = {}
        for t in CORE_TABLES:
            exists = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (t,)).fetchone()[0]
            out[t] = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] if exists else -1
        return out


def _audit_head(conninfo: str) -> dict:
    with psycopg.connect(conninfo, row_factory=dict_row) as conn:
        head = conn.execute("SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        return {"seq": head["seq"], "hash": head["hash"]} if head else {"seq": 0, "hash": None}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backup(out_dir: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = out_dir / stamp
    target.mkdir(parents=True, exist_ok=False)
    dbname = urlparse(settings.database_url).path.lstrip("/")

    with (target / "db.dump").open("wb") as f:
        _pg("pg_dump", ["-Fc", "--no-owner", "-d", dbname], stdout=f)

    objects: dict[str, str] = {}
    store_root = Path(settings.object_store_root)
    if settings.object_store_backend == "local" and store_root.is_dir():
        with tarfile.open(target / "objects.tar.gz", "w:gz") as tar:
            for path in sorted(p for p in store_root.rglob("*") if p.is_file()):
                rel = path.relative_to(store_root).as_posix()
                objects[rel] = _sha256(path)
                tar.add(path, arcname=rel)

    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "database": dbname,
        "counts": _counts(settings.database_url),
        "audit_head": _audit_head(settings.database_url),
        "objects": objects,
        "files": {name: _sha256(target / name) for name in ("db.dump", "objects.tar.gz") if (target / name).exists()},
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"backup": str(target), "objects": len(objects), "counts": manifest["counts"]}, indent=2))
    return target


def restore_drill(source: Path) -> int:
    started = time.monotonic()
    manifest = json.loads((source / "manifest.json").read_text())
    problems: list[str] = []
    for name, digest in manifest["files"].items():
        if _sha256(source / name) != digest:
            problems.append(f"{name} checksum mismatch (backup file damaged)")

    scratch = f"restore_drill_{int(time.time())}"
    admin = _conninfo("postgres")
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{scratch}"')
    try:
        with (source / "db.dump").open("rb") as f:
            _pg("pg_restore", ["--no-owner", "--exit-on-error", "-d", scratch], stdin=f)
        restored = _conninfo(scratch)

        counts = _counts(restored)
        for table, expected in manifest["counts"].items():
            if counts.get(table) != expected:
                problems.append(f"{table}: {counts.get(table)} rows restored, {expected} in backup")

        with psycopg.connect(restored, row_factory=dict_row) as conn:
            chain = verify_chain(conn)
        if not chain["intact"]:
            problems.append(f"audit chain broken at seq {chain['first_broken_seq']}")
        if _audit_head(restored) != manifest["audit_head"]:
            problems.append("audit chain head differs from the backup")

        if manifest["objects"]:
            with tempfile.TemporaryDirectory() as tmp:
                with tarfile.open(source / "objects.tar.gz") as tar:
                    tar.extractall(tmp, filter="data")
                for rel, digest in manifest["objects"].items():
                    path = Path(tmp) / rel
                    if not path.is_file() or _sha256(path) != digest:
                        problems.append(f"object {rel} missing or altered")
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')

    report = {
        "backup": str(source),
        "backup_created_at": manifest["created_at"],
        "restore_seconds": round(time.monotonic() - started, 1),
        "tables_checked": len(manifest["counts"]),
        "objects_checked": len(manifest["objects"]),
        "audit_events": manifest["audit_head"]["seq"],
        "result": "PASS" if not problems else "FAIL",
        "problems": problems,
    }
    print(json.dumps(report, indent=2))
    return 0 if not problems else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--out", type=Path, default=ROOT / "backups")
    r = sub.add_parser("restore-drill")
    r.add_argument("--from", dest="source", type=Path, required=True)
    args = parser.parse_args()
    if args.cmd == "backup":
        backup(args.out)
        return 0
    return restore_drill(args.source)


if __name__ == "__main__":
    raise SystemExit(main())
