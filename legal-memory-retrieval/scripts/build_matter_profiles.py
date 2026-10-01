"""Rebuild matter_profiles (text + embedding) used by the Ask-the-Firm resolver.

    python scripts/build_matter_profiles.py              # all matters
    python scripts/build_matter_profiles.py MTR-2026-00901
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.db.connection import connect  # noqa: E402
from app.km.profiles import rebuild  # noqa: E402


def main() -> None:
    ids = sys.argv[1:] or None
    t0 = time.perf_counter()
    with connect() as conn:
        n = rebuild(conn, ids)
    print(f"built {n} matter profiles in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
