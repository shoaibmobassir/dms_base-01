#!/usr/bin/env python3
"""Minimal firm graph for CI when the PCIJ/UNSC corpus has not been ingested.

Creates the members, client, matters, documents, permissions, arguments, and
deadlines that ``tests/test_security.py`` and ``tests/test_ui_contract.py`` need.
Idempotent. Safe to run on a fully ingested DB — uses CI-prefixed ids that do
not collide with the corpus, plus the four RESTRICTED_MATTERS ids from
``seed_demo.py`` so ethical-wall tests still resolve.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.db.connection import connect
from scripts.seed_demo import FIRM, RESTRICTED_MATTERS, _seed_firm

INSIDER = "MEM-00016"
OUTSIDER = "MEM-00001"
OTHER = "MEM-00002"
CLIENT = "CLI-CI-0001"
OPEN_MATTER = "MTR-CI-OPEN-001"
# Reuse the first restricted id so seed_demo's wall + security walls align.
WALL_MATTER = RESTRICTED_MATTERS[0]


def _upsert_member(cur, member_id: str, name: str, role: str) -> None:
    cur.execute(
        """
        INSERT INTO members (member_id, name, role, practice_areas, specializations, office, is_lawyer, email)
        VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
        -- Never rewrite an existing member: on a database that already holds the corpus
        -- this script used to rename real people (MEM-00001 became "James Okonkwo").
        ON CONFLICT (member_id) DO NOTHING
        """,
        (member_id, name, role, ["Energy"], ["Regulatory"], "The Hague", f"{member_id.lower()}@ci.harbour.test"),
    )


def _ensure_graph(cur) -> None:
    _upsert_member(cur, INSIDER, "Helena Voss", "Partner")
    _upsert_member(cur, OUTSIDER, "James Okonkwo", "Counsel")
    _upsert_member(cur, OTHER, "Priya Nair", "Associate")
    _upsert_member(cur, "MEM-00011", "Clara Dufour", "Knowledge Manager")  # administrator (seed_demo)

    cur.execute(
        """
        INSERT INTO clients (client_id, name, industry, size, headquarters)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (client_id) DO UPDATE SET name = EXCLUDED.name, industry = EXCLUDED.industry
        """,
        (CLIENT, "CI Energy Utility Ltd", "Energy utility", "Large", "New Delhi"),
    )

    for matter_id, code, title, status, court in (
        (OPEN_MATTER, "CI-OPEN-001", "CI Open Tariff Dispute", "Open", "Supreme Court of India"),
        (WALL_MATTER, WALL_MATTER.removeprefix("MTR-"), "CI Restricted Matter", "Open", "Appellate Tribunal for Electricity"),
    ):
        cur.execute(
            """
            INSERT INTO matters (
                matter_id, matter_code, title, client_id, client_name,
                practice_area, matter_type, jurisdiction, court, status, opened_date
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (matter_id) DO UPDATE SET title = EXCLUDED.title, status = EXCLUDED.status
            """,
            (
                matter_id,
                code,
                title,
                CLIENT,
                "CI Energy Utility Ltd",
                "Energy",
                "Litigation",
                "India",
                court,
                status,
                date.today() - timedelta(days=90),
            ),
        )
        cur.execute(
            """
            INSERT INTO permissions (matter_id, restricted, allowed_members)
            VALUES (%s, FALSE, '{}')
            ON CONFLICT (matter_id) DO NOTHING
            """,
            (matter_id,),
        )

    # Open matter: both lawyers. Wall matter: insider only.
    for matter_id, members in (
        (OPEN_MATTER, (INSIDER, OUTSIDER)),
        (WALL_MATTER, (INSIDER,)),
    ):
        for mid in members:
            cur.execute(
                """
                INSERT INTO matter_members (matter_id, member_id, role_on_matter)
                VALUES (%s, %s, %s)
                ON CONFLICT (matter_id, member_id) DO UPDATE SET role_on_matter = EXCLUDED.role_on_matter
                """,
                (matter_id, mid, "Lead" if mid == INSIDER else "Counsel"),
            )

    cur.execute(
        """
        UPDATE permissions SET restricted = TRUE, allowed_members = %s
        WHERE matter_id = %s
        """,
        ([INSIDER], WALL_MATTER),
    )

    for i, matter_id in enumerate((OPEN_MATTER, WALL_MATTER), start=1):
        doc_id = f"DOC-CI-{i:04d}"
        cur.execute(
            """
            INSERT INTO documents (
                document_id, matter_id, matter_code, client_id, title,
                document_type, author_id, author_name, doc_date, status, body
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (document_id) DO UPDATE SET title = EXCLUDED.title, body = EXCLUDED.body
            """,
            (
                doc_id,
                matter_id,
                matter_id.removeprefix("MTR-"),
                CLIENT,
                f"CI filing for {matter_id}",
                "Pleading",
                INSIDER,
                "Helena Voss",
                date.today() - timedelta(days=30),
                "Final",
                "This is a CI fixture document body used for contract and ACL tests.",
            ),
        )
        # One searchable chunk, so text/detail/retrieval paths have something to return.
        cur.execute(
            """
            INSERT INTO chunks (chunk_id, document_id, matter_id, chunk_index, text, tsv)
            VALUES (%(cid)s, %(did)s, %(mid)s, 0, %(text)s, to_tsvector('english', %(text)s))
            ON CONFLICT (chunk_id) DO NOTHING
            """,
            {"cid": f"{doc_id}-C00", "did": doc_id, "mid": matter_id,
             "text": "This is a CI fixture document body used for contract and ACL tests."},
        )

    cur.execute(
        """
        INSERT INTO arguments (argument_id, matter_id, issue, position, argument, outcome)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (argument_id) DO UPDATE SET issue = EXCLUDED.issue, position = EXCLUDED.position
        """,
        (
            "ARG-CI-0001",
            OPEN_MATTER,
            "Maintainability of the petition",
            "The petition is maintainable under Section 111.",
            "Detailed argument body for CI.",
            "Open",
        ),
    )

    cur.execute(
        """
        INSERT INTO court_deadlines
            (deadline_id, matter_id, title, kind, due_date, court, owner_member_id, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (deadline_id) DO UPDATE SET title = EXCLUDED.title, due_date = EXCLUDED.due_date
        """,
        (
            "DL-CI-OPEN-1",
            OPEN_MATTER,
            "CI hearing",
            "hearing",
            date.today() + timedelta(days=14),
            "Supreme Court of India",
            INSIDER,
            "open",
        ),
    )

    cur.execute(
        """
        INSERT INTO client_notes (note_id, client_id, kind, text, source_matter_id, author_member_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (note_id) DO UPDATE SET text = EXCLUDED.text
        """,
        (
            "CN-CLI-CI-0001-1",
            CLIENT,
            "prefers",
            "Wants a one-page tariff-impact summary before any long-form advice.",
            OPEN_MATTER,
            INSIDER,
        ),
    )


def main() -> int:
    with connect() as conn, conn.transaction(), conn.cursor() as cur:
        _seed_firm(cur)
        _ensure_graph(cur)
    print(f"CI fixture ready: firm={FIRM['name']} insider={INSIDER} wall={WALL_MATTER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
