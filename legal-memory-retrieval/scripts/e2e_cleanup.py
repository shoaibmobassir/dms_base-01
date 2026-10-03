#!/usr/bin/env python3
"""Remove what end-to-end tests created (records whose name starts with ``E2E-TMP``).

Run by Playwright's global teardown. Only touches rows carrying that prefix, so it is safe
to run against the demo database.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.connection import connect  # noqa: E402

PREFIX = "E2E-TMP"
MATTER_TABLES = ("matter_links", "matter_events", "arguments", "matter_members", "matter_grants", "matter_screens",
                 "access_requests", "member_pins", "court_deadlines", "matter_profiles", "matter_access", "permissions")


def main() -> int:
    with connect() as conn:
        matters = [r["matter_id"] for r in conn.execute("SELECT matter_id FROM matters WHERE title LIKE %s", (PREFIX + "%",))]
        for mid in matters:
            if conn.execute("SELECT 1 FROM documents WHERE matter_id = %s LIMIT 1", (mid,)).fetchone():
                continue  # never delete a matter that holds documents
            for t in MATTER_TABLES:
                conn.execute(f"DELETE FROM {t} WHERE matter_id = %s", (mid,))
            conn.execute("DELETE FROM matter_links WHERE related_matter_id = %s", (mid,))
            conn.execute("DELETE FROM matters WHERE matter_id = %s", (mid,))
        clients = conn.execute(
            "DELETE FROM clients c WHERE c.name LIKE %s AND NOT EXISTS (SELECT 1 FROM matters m WHERE m.client_id = c.client_id) "
            "RETURNING client_id", (PREFIX + "%",)).fetchall()
        checks = conn.execute("DELETE FROM conflict_checks WHERE EXISTS (SELECT 1 FROM unnest(names) n WHERE n LIKE %s) RETURNING check_id",
                              (PREFIX + "%",)).fetchall()
        people = [r["member_id"] for r in conn.execute("SELECT member_id FROM members WHERE name LIKE %s", (PREFIX + "%",))]
        for pid in people:
            for t in ("matter_members", "member_roles", "team_members", "api_keys"):
                conn.execute(f"DELETE FROM {t} WHERE member_id = %s", (pid,))
            conn.execute("DELETE FROM members WHERE member_id = %s", (pid,))
        conn.commit()
    print(f"e2e cleanup: {len(matters)} matters, {len(clients)} clients, {len(checks)} conflict checks, {len(people)} people")
    return 0


if __name__ == "__main__":
    sys.exit(main())
