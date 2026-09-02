"""CLI entry point: python -m app.ingest run --manifest ... --source ... --workers N"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest legal documents")
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="Run bulk ingestion")
    run_parser.add_argument("--source", required=True, help="Directory containing PDFs")
    run_parser.add_argument("--manifest", required=True, help="Path to YAML manifest")
    run_parser.add_argument("--workers", type=int, default=1, help="Number of workers")

    args = parser.parse_args()

    if args.command == "run":
        from app.ingest.pipeline import ingest_bulk
        import json
        result = ingest_bulk(args.source, args.manifest, args.workers)
        print("\n" + json.dumps({k: v for k, v in result.items() if k != "results"}, indent=2))
        if result.get("failed"):
            print("\nFailed files:")
            for r in result.get("results", []):
                if r["status"] == "failed":
                    print(f"  {r['file']}: {r.get('error', 'unknown')}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
