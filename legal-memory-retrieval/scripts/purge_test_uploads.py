#!/usr/bin/env python3
"""Remove documents left in the database by the upload and source-sync tests.

A batch is removed only when every file in it matches a name the tests use
(for example ``Transaction Documents/Agreements/SPA_1a2b3c.txt``), so real
uploads are never touched. Dry run by default.

Usage:
    python scripts/purge_test_uploads.py           # list what would be removed
    python scripts/purge_test_uploads.py --apply   # remove it
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.db.connection import connect
from app.ingest.purge import purge_documents, purge_upload_batches

# File names written by tests/test_firmos_upload_batch.py and tests/test_structure_and_version_chunks.py.
TEST_FILE = re.compile(
    r"^(Transaction Documents/(Agreements|Schedules)/(SPA|Schedule|notes)_[0-9a-f]{6}"
    r"|Agreements/SPA_[0-9a-f]{6}"
    r"|Good/doc_[0-9a-f]{6}"
    r"|Bad/fail_[0-9a-f]{6})\.txt$"
)


def test_batches(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT batch_id, created_at, array_agg(relative_path) AS paths FROM upload_batches b "
        "JOIN upload_batch_files f USING (batch_id) GROUP BY batch_id, created_at ORDER BY created_at"
    ).fetchall()
    return [r for r in rows if r["paths"] and all(TEST_FILE.match(p or "") for p in r["paths"])]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="delete (default: dry run)")
    args = parser.parse_args()

    with connect() as conn:
        batches = test_batches(conn)
    files = sum(len(b["paths"]) for b in batches)
    print(f"{len(batches)} test upload batches, {files} files")
    for b in batches[:10]:
        print(f"  {b['created_at']:%Y-%m-%d %H:%M}  {', '.join(b['paths'])}")
    if len(batches) > 10:
        print(f"  … and {len(batches) - 10} more")
    with connect() as conn:
        # Documents whose stored file lives in a pytest temporary folder (source-sync tests).
        temp_docs = [
            r["document_id"]
            for r in conn.execute(
                "SELECT document_id FROM documents WHERE source_uri LIKE %s", ("%/pytest-of-%",)
            ).fetchall()
        ]
    print(f"{len(temp_docs)} documents stored in pytest temporary folders")
    if not args.apply:
        print("dry run: nothing removed (use --apply)")
        return 0
    removed = purge_upload_batches([b["batch_id"] for b in batches])
    print(f"removed {removed} documents from {len(batches)} batches")
    with connect() as conn, conn.transaction():
        print(f"removed {purge_documents(conn, temp_docs)} documents from pytest temporary folders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
