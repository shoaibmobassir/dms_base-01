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
        projects = [r["project_id"] for r in conn.execute("SELECT project_id FROM projects WHERE title LIKE %s", (PREFIX + "%",))]
        shas = [r["content_sha256"] for r in conn.execute(
            """SELECT DISTINCT f.content_sha256 FROM upload_batch_files f JOIN upload_batches b USING (batch_id)
               WHERE b.container_kind = 'project' AND b.container_id = ANY(%s)""", (projects,))]
    # Projects (plan 22): their own documents, links, folders, members; then stored files nothing uses any more.
    from datetime import timedelta

    from app.ingest.purge import purge_projects
    from app.storage.blobs import collect

    purge_projects(projects)
    # Firm templates and library documents the specs made (their titles start with the prefix).
    from app.ingest.purge import purge_documents

    with connect() as conn, conn.transaction():
        stray = [r["document_id"] for r in conn.execute(
            "SELECT document_id FROM documents WHERE home_kind IN ('firm', 'library') AND title LIKE %s", (PREFIX + "%",))]
        if stray:
            shas = [r["content_sha256"] for r in conn.execute(
                "SELECT DISTINCT content_sha256 FROM documents WHERE document_id = ANY(%s) AND content_sha256 IS NOT NULL", (stray,))]
            purge_documents(conn, stray)
            projects_shas = shas
        else:
            projects_shas = []
    if projects_shas:
        with connect() as conn:
            collect(conn, grace=timedelta(0), only=projects_shas)
    with connect() as conn:
        conn.execute("DELETE FROM workbench_state WHERE scope_key = ANY(%s)", ([f"project:{p}" for p in projects],))
        conn.commit()
        if shas:
            collect(conn, grace=timedelta(0), only=shas)
    print(f"e2e cleanup: {len(matters)} matters, {len(clients)} clients, {len(checks)} conflict checks, {len(people)} people, "
          f"{len(projects)} projects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
