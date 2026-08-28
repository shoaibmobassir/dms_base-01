#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generator.pipeline import generate_firm


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a coherent synthetic law-firm universe.")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "firm.yaml")
    parser.add_argument("--out", type=Path, default=ROOT / "data")
    parser.add_argument("--profile", choices=["starter", "v1", "v2"], default=None)
    args = parser.parse_args()
    summary = generate_firm(args.config, args.out, profile=args.profile)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
