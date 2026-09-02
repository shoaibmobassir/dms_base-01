#!/usr/bin/env python3
"""Seed real PDF filings from repo /docs/ into Postgres via the production ingest pipeline."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.ingest.pipeline import ingest_bulk


def main() -> None:
    docs_dir = (ROOT.parent / "docs").resolve()
    manifest = ROOT / "ingest" / "manifests" / "real_filings.yaml"
    if not docs_dir.is_dir():
        print(json.dumps({"error": f"docs directory not found: {docs_dir}"}))
        sys.exit(1)
    if not manifest.is_file():
        print(json.dumps({"error": f"manifest not found: {manifest}"}))
        sys.exit(1)

    print(f"Ingesting PDFs from {docs_dir}")
    print(f"Manifest: {manifest}")
    result = ingest_bulk(str(docs_dir), str(manifest), workers=2)
    summary = {k: v for k, v in result.items() if k != "results"}
    print(json.dumps(summary, indent=2))
    if result.get("failed"):
        sys.exit(1)


if __name__ == "__main__":
    main()
