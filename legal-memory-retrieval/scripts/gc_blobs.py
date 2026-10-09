"""Delete stored files (content-addressed blobs) that nothing references any more (plan 22, W0).

    python scripts/gc_blobs.py            # dry run: list what would be removed
    python scripts/gc_blobs.py --apply    # remove them (only blobs older than --grace-hours, default 24)
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.connection import connect  # noqa: E402
from app.storage.blobs import collect  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="delete (default is a dry run)")
    parser.add_argument("--grace-hours", type=float, default=24.0)
    args = parser.parse_args()
    with connect() as conn:
        hashes = collect(conn, grace=timedelta(hours=args.grace_hours), dry_run=not args.apply)
    print(f"{'removed' if args.apply else 'would remove'} {len(hashes)} unreferenced blobs")
    for h in hashes[:50]:
        print(" ", h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
