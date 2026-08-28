#!/usr/bin/env python3
"""
Seed an api_keys table and print one key per member.

Usage:
    python scripts/issue_keys.py [--members data/members.json]

Creates the table if absent, then inserts one key per member.
Safe to re-run: uses ON CONFLICT DO NOTHING so existing keys are preserved.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.db.connection import connect

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS api_keys (
    member_id TEXT NOT NULL REFERENCES members (member_id),
    key_hash  TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def main() -> None:
    corpus_dir = Path(os.getenv("CORPUS_DIR", str(ROOT.parent / "dummy-firm" / "data")))
    members_file = corpus_dir / "members.json"
    if not members_file.exists():
        print(f"members.json not found at {members_file}", file=sys.stderr)
        sys.exit(1)

    members = json.loads(members_file.read_text(encoding="utf-8"))

    with connect() as conn:
        conn.execute(CREATE_TABLE)

        print(f"{'MEMBER_ID':<15}  {'NAME':<30}  API_KEY")
        print("-" * 90)
        for m in members:
            mid = m["member_id"]
            raw_key = secrets.token_urlsafe(32)
            hashed = hashlib.sha256(raw_key.encode()).hexdigest()
            conn.execute(
                "INSERT INTO api_keys (member_id, key_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (mid, hashed),
            )
            print(f"{mid:<15}  {m['name']:<30}  {raw_key}")


if __name__ == "__main__":
    main()
