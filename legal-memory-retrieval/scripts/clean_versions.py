#!/usr/bin/env python3
"""Give existing Word versions a clean stored file (docs/plan/21_documents_search_versioning.md, C2).

    python scripts/clean_versions.py                       # count only (default)
    python scripts/clean_versions.py --apply               # convert
    python scripts/clean_versions.py --apply --document DOC-0123456789 --limit 50

A version with tracked changes gets a clean copy stored beside it; the file it had is kept as its source file.
Nothing is deleted. Re-running is safe. Back up the object store before the first --apply.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.db.connection import connect
from app.documents.clean_versions import clean_versions


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write changes (default: only count)")
    ap.add_argument("--document", help="only this document id")
    ap.add_argument("--limit", type=int, help="at most this many versions")
    args = ap.parse_args()
    with connect() as conn:
        print(json.dumps(clean_versions(conn, apply=args.apply, document_id=args.document, limit=args.limit), indent=2))


if __name__ == "__main__":
    main()
