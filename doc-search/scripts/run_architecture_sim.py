#!/usr/bin/env python3
"""CLI: run the architecture simulator and print metrics."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from doc-search/ or repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from architecture_sim.pipeline import SimConfig, run_pipeline


def main() -> int:
    p = argparse.ArgumentParser(description="FirmOS document intelligence architecture sim")
    p.add_argument("--docs", type=int, default=50, help="Number of SPA documents")
    p.add_argument("--pages", type=int, default=20, help="Approx pages per document")
    p.add_argument("--matters", type=int, default=8)
    p.add_argument("--versions", type=int, default=2)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--json", action="store_true", help="Print JSON summary only")
    args = p.parse_args()

    cfg = SimConfig(
        n_documents=args.docs,
        pages_per_doc=args.pages,
        n_matters=args.matters,
        versions_per_doc=args.versions,
        max_workers=args.workers,
    )
    result = run_pipeline(cfg)
    summary = result.summary()

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print("=== FirmOS Architecture Simulator ===")
        print(f"Wall time:          {summary['wall_time_s']}s")
        print(f"Documents:          {summary['documents']}")
        print(f"Versions:           {summary['versions']}")
        print(f"Folders:            {summary['folders']}")
        print(f"Matters:            {summary['matters']}")
        print(f"Blocks:             {summary['blocks']}")
        print(f"Chunks:             {summary['chunks']}")
        print(f"Pages represented:  {summary['pages_represented']}")
        print(f"Ingest processed:   {summary['ingest']['processed']}/{summary['ingest']['total_files']}")
        print(f"Ingest errors:      {len(summary['ingest']['errors'])}")
        print(f"Review findings:    {summary['review'].get('findings_verified')}")
        print(f"Map tasks:          {summary['review'].get('map_tasks')}")
        print(f"Cache:              {summary['review'].get('cache')}")
        print(f"Anchor resolution:  {summary['anchor_resolution']}")
        print()
        print("--- Review report (head) ---")
        print("\n".join(result.review_report.splitlines()[:40]))
    return 0 if not summary["ingest"]["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
