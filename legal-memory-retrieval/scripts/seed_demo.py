#!/usr/bin/env python3
"""Seed the demo data the UI and the ethical wall need, on top of the ingested corpus.

Run after ``scripts/ingest.py`` and ``scripts/migrate.py``. Idempotent: every row has a
deterministic id and is upserted, so running twice leaves identical row counts.

What it writes (and nothing else):
  * firm_profile      — the firm's name/descriptor/office
  * permissions       — RESTRICTED_MATTERS become visible only to their matter team
  * court_deadlines   — hearings/filings on every Open matter, dated from --anchor
  * client_notes      — observed preferences for clients with active matters
  * project_activity  — deletes rows whose project no longer exists (orphans)

Usage:
    python scripts/seed_demo.py                    # anchor = today
    python scripts/seed_demo.py --anchor 2026-09-24
    python scripts/seed_demo.py --reset            # remove seeded rows, lift restrictions

Note: restricting matters is real ACL behaviour — retrieval evals whose ``as_member`` is
outside a restricted team will stop seeing that matter. Use --reset before benchmarking
against historical numbers.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.config import settings
from app.db.connection import connect

FIRM = {
    "name": "Harbour International Chambers",
    "descriptor": "International Disputes & Energy Regulation",
    "office": "The Hague",
}

# Two live Indian-energy matters and two historical PCIJ matters sit behind an ethical wall.
RESTRICTED_MATTERS = (
    "MTR-2026-00169",
    "MTR-2026-00170",
    "MTR-1922-00066",
    "MTR-1922-00067",
)

# (days from anchor, kind, title, status). Negative offsets are past deadlines.
_DEADLINE_PLAN = {
    "Appellate Tribunal for Electricity": [
        (-12, "filing", "File rejoinder to respondent's reply", "done"),
        (6, "hearing", "Final hearing — arguments on maintainability", "open"),
        (21, "filing", "Written submissions due", "open"),
    ],
    "Supreme Court of India": [
        (9, "hearing", "Listing for admission hearing", "open"),
        (30, "filing", "Counter-affidavit due", "open"),
    ],
    "Central Electricity Regulatory Commission": [
        (-5, "filing", "Reply to impleadment application", "done"),
        (14, "hearing", "Hearing on interim relief", "open"),
    ],
    "Punjab State Electricity Regulatory Commission": [
        (3, "filing", "Written submissions (post-hearing) due", "open"),
        (45, "compliance", "Compliance report on tariff directions", "open"),
    ],
    "United Nations Security Council": [
        (11, "compliance", "Sanctions compliance memo to client", "open"),
        (60, "limitation", "Annual reporting window closes", "open"),
    ],
}
_DEFAULT_PLAN = [(10, "filing", "Next procedural filing", "open")]

# Notes per client industry. Each note is attributed to the client's latest matter.
_NOTES_BY_INDUSTRY = {
    "Energy utility": [
        ("prefers", "Wants a one-page tariff-impact summary before any long-form advice."),
        ("prefers", "Expects regulatory filings to cite the specific CERC/SERC regulation clause."),
        ("avoid", "Avoid recommending interim-relief applications without a cost estimate."),
        ("terms", "Fee estimates are approved per stage (pleadings, hearing, appeal)."),
    ],
    "Intergovernmental organisation": [
        ("prefers", "Briefings are organised by resolution number and date adopted."),
        ("avoid", "No commentary on member-state politics in written advice."),
    ],
}


ADMIN_MEMBERS = ("MEM-00011",)  # Knowledge Manager — can read/export the audit stream


def _seed_admins(cur) -> None:
    cur.execute("UPDATE members SET is_admin = (member_id = ANY(%s))", (list(ADMIN_MEMBERS),))


def _seed_firm(cur) -> None:
    cur.execute(
        """
        INSERT INTO firm_profile (id, name, descriptor, office, tenant_id)
        VALUES (TRUE, %(name)s, %(descriptor)s, %(office)s, %(tenant)s)
        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,
            descriptor = EXCLUDED.descriptor, office = EXCLUDED.office,
            tenant_id = EXCLUDED.tenant_id
        """,
        {**FIRM, "tenant": settings.tenant_id},
    )


def _seed_restrictions(cur) -> list[tuple[str, list[str]]]:
    applied = []
    for matter_id in RESTRICTED_MATTERS:
        cur.execute(
            "SELECT array_agg(member_id ORDER BY member_id) AS team"
            " FROM matter_members WHERE matter_id = %s",
            (matter_id,),
        )
        team = cur.fetchone()["team"]
        if not team:
            print(f"  skip {matter_id}: not in corpus or has no team")
            continue
        cur.execute(
            "UPDATE permissions SET restricted = TRUE, allowed_members = %s WHERE matter_id = %s",
            (team, matter_id),
        )
        applied.append((matter_id, team))
    return applied


def _seed_deadlines(cur, anchor: date) -> int:
    cur.execute(
        """
        SELECT m.matter_id, m.court,
               (SELECT mm.member_id FROM matter_members mm
                 WHERE mm.matter_id = m.matter_id
                 ORDER BY (mm.role_on_matter = 'Lead') DESC, mm.member_id LIMIT 1) AS owner
        FROM matters m WHERE m.status = 'Open' ORDER BY m.matter_id
        """
    )
    n = 0
    for m in cur.fetchall():
        for i, (offset, kind, title, status) in enumerate(_DEADLINE_PLAN.get(m["court"], _DEFAULT_PLAN)):
            cur.execute(
                """
                INSERT INTO court_deadlines
                    (deadline_id, matter_id, title, kind, due_date, court, owner_member_id, status)
                VALUES (%(id)s, %(matter_id)s, %(title)s, %(kind)s, %(due)s, %(court)s, %(owner)s, %(status)s)
                ON CONFLICT (deadline_id) DO UPDATE SET title = EXCLUDED.title,
                    kind = EXCLUDED.kind, due_date = EXCLUDED.due_date, court = EXCLUDED.court,
                    owner_member_id = EXCLUDED.owner_member_id, status = EXCLUDED.status
                """,
                {
                    "id": f"DL-{m['matter_id'].removeprefix('MTR-')}-{i + 1}",
                    "matter_id": m["matter_id"],
                    "title": title,
                    "kind": kind,
                    "due": anchor + timedelta(days=offset),
                    "court": m["court"],
                    "owner": m["owner"],
                    "status": status,
                },
            )
            n += 1
    return n


def _seed_client_notes(cur) -> int:
    cur.execute(
        """
        SELECT DISTINCT ON (c.client_id) c.client_id, c.industry, m.matter_id,
               (SELECT mm.member_id FROM matter_members mm
                 WHERE mm.matter_id = m.matter_id
                 ORDER BY (mm.role_on_matter = 'Lead') DESC, mm.member_id LIMIT 1) AS author
        FROM clients c JOIN matters m ON m.client_id = c.client_id
        WHERE c.industry = ANY(%s)
        ORDER BY c.client_id, m.opened_date DESC NULLS LAST, m.matter_id DESC
        """,
        (list(_NOTES_BY_INDUSTRY),),
    )
    n = 0
    for c in cur.fetchall():
        for i, (kind, text) in enumerate(_NOTES_BY_INDUSTRY[c["industry"]]):
            cur.execute(
                """
                INSERT INTO client_notes
                    (note_id, client_id, kind, text, source_matter_id, author_member_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (note_id) DO UPDATE SET kind = EXCLUDED.kind, text = EXCLUDED.text,
                    source_matter_id = EXCLUDED.source_matter_id,
                    author_member_id = EXCLUDED.author_member_id
                """,
                (f"CN-{c['client_id']}-{i + 1}", c["client_id"], kind, text, c["matter_id"], c["author"]),
            )
            n += 1
    return n


def _delete_orphan_activity(cur) -> int:
    cur.execute(
        "DELETE FROM project_activity a"
        " WHERE NOT EXISTS (SELECT 1 FROM projects p WHERE p.project_id = a.project_id)"
    )
    return cur.rowcount


def _reset(cur) -> None:
    cur.execute("DELETE FROM court_deadlines WHERE deadline_id LIKE 'DL-%'")
    cur.execute("DELETE FROM client_notes WHERE note_id LIKE 'CN-%'")
    cur.execute(
        "UPDATE permissions SET restricted = FALSE WHERE matter_id = ANY(%s)",
        (list(RESTRICTED_MATTERS),),
    )
    cur.execute("DELETE FROM firm_profile")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--anchor", type=date.fromisoformat, default=date.today(),
                        help="date deadlines are offset from (default: today)")
    parser.add_argument("--reset", action="store_true", help="remove seeded rows and restrictions")
    args = parser.parse_args()

    with connect() as conn, conn.transaction(), conn.cursor() as cur:
        if args.reset:
            _reset(cur)
            print("reset: seeded deadlines, client notes, firm profile and restrictions removed")
            return 0
        _seed_firm(cur)
        _seed_admins(cur)
        restricted = _seed_restrictions(cur)
        deadlines = _seed_deadlines(cur, args.anchor)
        notes = _seed_client_notes(cur)
        orphans = _delete_orphan_activity(cur)

    print(f"firm profile      : {FIRM['name']}")
    print(f"administrators    : {', '.join(ADMIN_MEMBERS)}")
    for matter_id, team in restricted:
        print(f"restricted matter : {matter_id} → visible to {', '.join(team)}")
    print(f"court deadlines   : {deadlines} (anchor {args.anchor})")
    print(f"client notes      : {notes}")
    print(f"orphan activity   : {orphans} deleted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
