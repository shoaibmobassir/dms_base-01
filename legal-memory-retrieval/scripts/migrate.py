#!/usr/bin/env python3
"""Apply app/db/migrations/*.sql in filename order.

Each file is applied once and recorded in ``schema_migrations``. Migration files
are written to be idempotent, so re-applying after a partial failure is safe.

Usage:
    python scripts/migrate.py            # apply pending migrations
    python scripts/migrate.py --status   # list applied / pending
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.db.connection import connect

MIGRATIONS_DIR = ROOT / "app" / "db" / "migrations"
SCHEMA = ROOT / "app" / "db" / "schema.sql"

CREATE_LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def pending_and_applied(conn) -> tuple[list[Path], set[str]]:
    conn.execute(CREATE_LEDGER)
    applied = {r["filename"] for r in conn.execute("SELECT filename FROM schema_migrations")}
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    return [f for f in files if f.name not in applied], applied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="show status and exit")
    args = parser.parse_args()

    with connect() as conn:
        # A brand-new database has no base schema (schema.sql is otherwise applied by
        # scripts/ingest.py). Bootstrap it only when the core tables are absent, so an
        # existing database is never touched by schema.sql's DROP statements.
        if conn.execute("SELECT to_regclass('members') IS NULL AS empty").fetchone()["empty"]:
            if args.status:
                print("pending  base schema (app/db/schema.sql)")
            else:
                print("bootstrapping base schema (empty database) …", flush=True)
                with conn.transaction():
                    conn.execute(SCHEMA.read_text(encoding="utf-8"))
        pending, applied = pending_and_applied(conn)
        conn.commit()
        if args.status:
            for name in sorted(applied):
                print(f"applied  {name}")
            for f in pending:
                print(f"pending  {f.name}")
            return 0

        for f in pending:
            print(f"applying {f.name} …", flush=True)
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (f.name,))
        print(f"done: {len(pending)} applied, {len(applied)} already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
