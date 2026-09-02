#!/usr/bin/env python3
"""Seed projects / workstreams from ingested matters (idempotent)."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from psycopg.rows import dict_row

from app.db.connection import connect

_WORKSTREAMS: list[tuple[str, str]] = [
    ("Legal Due Diligence", "Document room review, red-flag memo, and closing checklist."),
    ("SPA Negotiation & Execution", "Drafting, mark-up, and finalisation of transaction documents."),
    ("Regulatory Filing (CCI/SEBI)", "Competition / securities filings and authority correspondence."),
    ("Arbitration Pleadings", "Statement of claim, defence, and witness statements."),
    ("NCLT Insolvency Proceedings", "Section 7/9 petitions, CoC strategy, and resolution plan review."),
    ("Employment Compliance Audit", "Policy review, POSH compliance, and restructuring advice."),
    ("Tax Structuring & Ruling", "Indirect tax analysis, ruling application, and opinion."),
    ("Court Hearing Preparation", "Chronology, draft submissions, and hearing bundle."),
]

_STATUSES = ("In Progress", "In Progress", "In Progress", "Completed", "On Hold")


def _pick(items: list, seed: str):
    h = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    return items[h % len(items)]


def _milestones(seed: str, deadline: date) -> list[dict]:
    titles = [
        "Kickoff with client / GC",
        "Document collection & review",
        "Draft deliverable circulation",
        "Partner sign-off",
        "Final delivery",
    ]
    n = 3 + (int(hashlib.sha256(seed.encode()).hexdigest()[:2], 16) % 3)
    out: list[dict] = []
    for i, title in enumerate(titles[:n]):
        due = deadline - timedelta(days=max(7, (n - i) * 14))
        done = i < max(0, n - 2)
        out.append({"title": title, "done": done, "due": due.isoformat()})
    return out


def ensure_projects_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            matter_id TEXT NOT NULL REFERENCES matters (matter_id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            practice_team TEXT NOT NULL,
            lead_member_id TEXT REFERENCES members (member_id),
            lead_lawyer TEXT,
            status TEXT NOT NULL DEFAULT 'In Progress',
            progress INT NOT NULL DEFAULT 0,
            deadline DATE,
            scope TEXT,
            milestones JSONB NOT NULL DEFAULT '[]'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_matter ON projects (matter_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_status ON projects (status)")


def seed_projects(conn, max_projects: int = 240) -> int:
    ensure_projects_table(conn)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT COUNT(*) AS n FROM projects")
        existing = cur.fetchone()["n"]
        if existing:
            print(json.dumps({"projects": existing, "skipped": True}))
            return existing

        cur.execute(
            """
            SELECT m.matter_id, m.matter_code, m.title, m.client_id, m.client_name,
                   m.practice_area, m.matter_type, m.status, m.claim_amount,
                   m.opened_date
            FROM matters m
            WHERE m.status IS NULL OR m.status NOT ILIKE '%%closed%%'
            ORDER BY m.opened_date DESC NULLS LAST
            LIMIT %(limit)s
            """,
            {"limit": max_projects},
        )
        matters = list(cur.fetchall())

        rows: list[tuple] = []
        for i, m in enumerate(matters):
            seed = m["matter_id"]
            ws_title, ws_scope = _pick(_WORKSTREAMS, seed)
            proj_status = _pick(list(_STATUSES), seed + "status")
            opened = m.get("opened_date") or date.today()
            if isinstance(opened, str):
                opened = date.fromisoformat(opened[:10])
            deadline = opened + timedelta(days=60 + (i % 120))
            milestones = _milestones(seed, deadline)
            done = sum(1 for x in milestones if x["done"])
            progress = round(100 * done / len(milestones)) if milestones else 0
            if proj_status == "Completed":
                progress = 100
                for ms in milestones:
                    ms["done"] = True

            cur.execute(
                """
                SELECT mm.member_id, mem.name
                FROM matter_members mm
                JOIN members mem ON mem.member_id = mm.member_id
                WHERE mm.matter_id = %(mid)s
                ORDER BY CASE WHEN mm.role_on_matter ILIKE '%%lead%%' THEN 0 ELSE 1 END
                LIMIT 1
                """,
                {"mid": m["matter_id"]},
            )
            lead = cur.fetchone()
            lead_id = lead["member_id"] if lead else None
            lead_name = lead["name"] if lead else "Unassigned"

            project_id = f"PRJ-{m['matter_id'].split('-')[-1]}-{i % 3:01d}"
            rows.append(
                (
                    project_id,
                    m["matter_id"],
                    f"{ws_title} — {(m['client_name'] or m['title'][:40])}",
                    m["practice_area"] or "General",
                    lead_id,
                    lead_name,
                    proj_status,
                    progress,
                    deadline,
                    f"{ws_scope} Matter: {m['title']}.",
                    json.dumps(milestones),
                )
            )

        cur.executemany(
            """
            INSERT INTO projects (
                project_id, matter_id, title, practice_team, lead_member_id,
                lead_lawyer, status, progress, deadline, scope, milestones
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (project_id) DO NOTHING
            """,
            rows,
        )
        conn.commit()
        print(json.dumps({"projects_seeded": len(rows)}))
        return len(rows)


def main() -> None:
    with connect() as conn:
        n = seed_projects(conn)
    print(json.dumps({"ok": True, "projects": n}))


if __name__ == "__main__":
    main()
