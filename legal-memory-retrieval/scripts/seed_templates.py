#!/usr/bin/env python3
"""Start the firm template library (plan 22, W6.2) from documents the firm already holds.

Copies chosen Word documents from matters into Firm templates (as copies with provenance; the originals are not
changed), in practice-area folders, acting as a knowledge manager (who holds ``km.publish``). Idempotent: a template
whose title is already in that folder is skipped.

    python scripts/seed_templates.py            # copy what is found
    python scripts/seed_templates.py --dry-run  # only list what would be copied
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from psycopg.rows import dict_row  # noqa: E402

from app.db.connection import connect  # noqa: E402
from app.workspaces.documents import copy_document  # noqa: E402

# (title in a matter, template folder, template name)
CANDIDATES = [
    ("Share Purchase Agreement.docx", "Corporate", "Share purchase agreement"),
    ("Disclosure Schedule.docx", "Corporate", "Disclosure schedule"),
    ("Board Resolution.docx", "Corporate", "Board resolution"),
    ("Employment Agreement - CTO.docx", "Employment", "Senior executive employment agreement"),
]


def curator(conn) -> str:
    row = conn.execute(
        """SELECT m.member_id FROM members m
           JOIN member_roles mr ON mr.member_id = m.member_id
           JOIN role_permissions rp ON rp.role_key = mr.role_key
           WHERE rp.permission = 'km.publish' ORDER BY m.member_id LIMIT 1""").fetchone()
    if not row:
        raise SystemExit("Nobody holds km.publish; run the migrations first.")
    return row["member_id"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    with connect() as conn:
        conn.row_factory = dict_row
        actor = curator(conn)
        made = 0
        for title, folder, name in CANDIDATES:
            src = conn.execute(
                """SELECT document_id FROM documents WHERE title = %s AND home_kind = 'matter' AND archived_at IS NULL
                   ORDER BY document_id LIMIT 1""", (title,)).fetchone()
            if not src:
                print(f"skip  {title}: not in any matter")
                continue
            have = conn.execute(
                """SELECT 1 FROM documents WHERE home_kind = 'firm' AND home_id = 'templates' AND archived_at IS NULL
                   AND title = %s AND coalesce(folder_path, '') = %s""", (name, folder)).fetchone()
            if have:
                print(f"have  {folder}/{name}")
                continue
            if args.dry_run:
                print(f"would {folder}/{name} ← {src['document_id']}")
                continue
            out = copy_document(conn, actor, src["document_id"], "firm", "templates", folder, name)
            made += 1
            print(f"made  {folder}/{name} = {out['document_id']}")
        print(f"{made} template(s) added by {actor}")


if __name__ == "__main__":
    main()
