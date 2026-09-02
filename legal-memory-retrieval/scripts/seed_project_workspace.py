#!/usr/bin/env python3
"""Seed project workspaces with folders, versioned documents, and activity.

Idempotent: skips projects that already have folders seeded.
Run after migrate_project_schema.py.
"""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from psycopg.rows import dict_row

from app.db.connection import connect
from app.documents import content_sha256

# Fallback showcase IDs; seed script also picks accessible matters for MEM-00001
SHOWCASE_PROJECTS = ("PRJ-00075-0", "PRJ-00741-1", "PRJ-00542-0")
DEMO_MEMBER = "MEM-00001"

FOLDER_TEMPLATE = [
    ("Drafts & Working Copies", None),
    ("Due Diligence", None),
    ("Submissions", None),
    ("Executed / Final", None),
]

VERSION_CHAIN = [
    ("draft", "v1.0 Draft", "Draft", "\n\n[DRAFT — Internal circulation only. Not for reliance.]"),
    ("developing", "v2.0 Developing", "Developing", "\n\n[DEVELOPING — Active mark-up in progress. Subject to partner review.]"),
    ("review", "v3.0 Partner Review", "Under Review", "\n\n[UNDER PARTNER REVIEW — Comments incorporated from diligence team.]"),
    ("final", "v4.0 Executed", "Executed", "\n\n[EXECUTED — Final form for closing binder and institutional memory.]"),
]

LIGHT_VERSION_CHAIN = [
    ("draft", "v1.0 Draft", "Draft", "\n\n[DRAFT]"),
    ("developing", "v2.0 Developing", "Developing", "\n\n[DEVELOPING — counsel mark-up]"),
    ("final", "v3.0 Final", "Final", "\n\n[FINAL]"),
]


def _sha(text: str) -> str:
    return content_sha256(text)


def _pick_docs(cur, matter_id: str, limit: int) -> list[dict]:
    cur.execute(
        """
        SELECT document_id, title, body, document_type, author_name, matter_code, client_id
        FROM documents
        WHERE matter_id = %(mid)s AND body IS NOT NULL AND LENGTH(body) > 80
        ORDER BY doc_date DESC NULLS LAST, document_id
        LIMIT %(limit)s
        """,
        {"mid": matter_id, "limit": limit},
    )
    return list(cur.fetchall())


def _ensure_folders(cur, project_id: str, member_id: str | None) -> dict[str, str]:
    cur.execute(
        "SELECT folder_id, name FROM project_folders WHERE project_id = %(pid)s",
        {"pid": project_id},
    )
    existing = {r["name"]: r["folder_id"] for r in cur.fetchall()}
    if existing:
        return existing

    folder_ids: dict[str, str] = {}
    for name, _parent in FOLDER_TEMPLATE:
        fid = f"FLD-{uuid.uuid4().hex[:8].upper()}"
        cur.execute(
            """
            INSERT INTO project_folders (folder_id, project_id, name, parent_folder_id, created_by)
            VALUES (%(fid)s, %(pid)s, %(name)s, NULL, %(creator)s)
            """,
            {"fid": fid, "pid": project_id, "name": name, "creator": member_id},
        )
        folder_ids[name] = fid
        cur.execute(
            """
            INSERT INTO project_activity (project_id, action, actor_id, target_id, target_title)
            VALUES (%(pid)s, 'folder.created', %(actor)s, %(fid)s, %(name)s)
            """,
            {"pid": project_id, "actor": member_id, "fid": fid, "name": name},
        )
    return folder_ids


def _insert_version(
    cur,
    *,
    document_id: str,
    version_number: int,
    title: str,
    body: str,
    author_name: str | None,
    source: str,
    version_status: str,
    version_label: str,
    created_at: datetime,
) -> str:
    version_id = f"VER-{uuid.uuid4().hex[:10].upper()}"
    cur.execute(
        """
        INSERT INTO document_versions (
            version_id, document_id, version_number, title, body, content_sha256,
            author_name, source, version_status, version_label, created_at
        ) VALUES (
            %(vid)s, %(doc_id)s, %(vnum)s, %(title)s, %(body)s, %(sha)s,
            %(author)s, %(source)s, %(vstatus)s, %(vlabel)s, %(created_at)s
        )
        """,
        {
            "vid": version_id,
            "doc_id": document_id,
            "vnum": version_number,
            "title": title,
            "body": body,
            "sha": _sha(body),
            "author": author_name,
            "source": source,
            "vstatus": version_status,
            "vlabel": version_label,
            "created_at": created_at,
        },
    )
    return version_id


def _seed_document_versions(
    cur,
    doc: dict,
    chain: list[tuple[str, str, str, str]],
    base_time: datetime,
) -> str | None:
    """Create version chain; return latest version_id."""
    body_base = (doc.get("body") or "").strip()
    if not body_base:
        return None

    cur.execute(
        "SELECT COUNT(*) AS n FROM document_versions WHERE document_id = %(did)s",
        {"did": doc["document_id"]},
    )
    if cur.fetchone()["n"] > 0:
        cur.execute(
            "SELECT current_version_id FROM documents WHERE document_id = %(did)s",
            {"did": doc["document_id"]},
        )
        row = cur.fetchone()
        return row["current_version_id"] if row else None

    latest_vid: str | None = None
    latest_label = "v1.0"
    latest_status = "Draft"
    latest_body = body_base

    for i, (source, label, status, suffix) in enumerate(chain, start=1):
        body = body_base + suffix
        created_at = base_time + timedelta(days=i)
        latest_vid = _insert_version(
            cur,
            document_id=doc["document_id"],
            version_number=i,
            title=doc["title"],
            body=body,
            author_name=doc.get("author_name"),
            source=source,
            version_status=status.lower().replace(" ", "_") if status != "Under Review" else "review",
            version_label=label,
            created_at=created_at,
        )
        latest_label = label
        latest_status = status
        latest_body = body

    cur.execute(
        """
        UPDATE documents SET
            current_version_id = %(vid)s,
            body = %(body)s,
            version = %(version_label)s,
            status = %(status)s,
            content_sha256 = %(sha)s,
            updated_at = NOW()
        WHERE document_id = %(doc_id)s
        """,
        {
            "vid": latest_vid,
            "body": latest_body,
            "version_label": latest_label,
            "status": latest_status,
            "sha": _sha(latest_body),
            "doc_id": doc["document_id"],
        },
    )
    return latest_vid


def _accessible_showcase_projects(cur, limit: int = 3) -> list[str]:
    """Pick showcase projects on matters visible to the demo persona."""
    cur.execute(
        """
        SELECT pr.project_id
        FROM projects pr
        JOIN matters m ON m.matter_id = pr.matter_id
        LEFT JOIN permissions p ON p.matter_id = pr.matter_id
        WHERE (
            p.restricted IS NOT TRUE
            OR %(member)s = ANY(p.allowed_members)
            OR p.matter_id IS NULL
        )
        ORDER BY pr.deadline DESC NULLS LAST, pr.project_id
        LIMIT %(limit)s
        """,
        {"member": DEMO_MEMBER, "limit": limit},
    )
    ids = [r["project_id"] for r in cur.fetchall()]
    return ids or list(SHOWCASE_PROJECTS)


def seed_project_workspace(conn, *, max_showcase: int = 3, docs_per_showcase: int = 10, force: bool = False) -> dict:
    stats = {
        "projects": 0,
        "folders": 0,
        "documents_versioned": 0,
        "activity": 0,
        "skipped": False,
    }

    with conn.cursor(row_factory=dict_row) as cur:
        showcase_ids = _accessible_showcase_projects(cur, max_showcase)
        cur.execute(
            """
            SELECT pr.project_id, pr.matter_id, pr.title, pr.lead_member_id
            FROM projects pr
            WHERE pr.project_id = ANY(%(showcase)s)
            ORDER BY pr.project_id
            """,
            {"showcase": showcase_ids},
        )
        projects = list(cur.fetchall())

        for pr in projects:
            pid = pr["project_id"]
            is_showcase = True

            if force:
                cur.execute("DELETE FROM project_activity WHERE project_id = %(pid)s", {"pid": pid})
                cur.execute(
                    "UPDATE documents SET folder_id = NULL WHERE matter_id = %(mid)s",
                    {"mid": pr["matter_id"]},
                )
                cur.execute("DELETE FROM project_folders WHERE project_id = %(pid)s", {"pid": pid})
            else:
                cur.execute(
                    "SELECT COUNT(*) AS n FROM project_folders WHERE project_id = %(pid)s",
                    {"pid": pid},
                )
                if cur.fetchone()["n"] > 0:
                    continue

            folders = _ensure_folders(cur, pid, pr.get("lead_member_id"))
            if folders:
                stats["folders"] += len(folders)

            doc_limit = docs_per_showcase if is_showcase else 4
            docs = _pick_docs(cur, pr["matter_id"], doc_limit)
            chain = VERSION_CHAIN if is_showcase else LIGHT_VERSION_CHAIN
            base_time = datetime.now(timezone.utc) - timedelta(days=30)

            folder_names = list(folders.keys())
            for idx, doc in enumerate(docs):
                vid = _seed_document_versions(cur, doc, chain, base_time)
                if not vid:
                    continue
                stats["documents_versioned"] += 1

                # Distribute across folders
                folder_name = folder_names[idx % len(folder_names)]
                folder_id = folders[folder_name]
                cur.execute(
                    "UPDATE documents SET folder_id = %(fid)s WHERE document_id = %(did)s",
                    {"fid": folder_id, "did": doc["document_id"]},
                )
                cur.execute(
                    """
                    INSERT INTO project_activity (
                        project_id, action, actor_id, target_id, target_title, metadata
                    ) VALUES (
                        %(pid)s, 'document.added', %(actor)s, %(did)s, %(title)s,
                        %(meta)s::jsonb
                    )
                    """,
                    {
                        "pid": pid,
                        "actor": pr.get("lead_member_id"),
                        "did": doc["document_id"],
                        "title": doc["title"],
                        "meta": json.dumps({"folder": folder_name, "versions": len(chain)}),
                    },
                )
                stats["activity"] += 1

            stats["projects"] += 1

        conn.commit()

    return stats


def main() -> None:
    import argparse
    import importlib.util

    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-seed showcase projects")
    args = parser.parse_args()

    path = ROOT / "scripts" / "migrate_project_schema.py"
    spec = importlib.util.spec_from_file_location("migrate_project_schema", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    mod.main()

    with connect() as conn:
        stats = seed_project_workspace(conn, force=args.force)
    print(json.dumps({"ok": True, **stats}, indent=2))


if __name__ == "__main__":
    main()
