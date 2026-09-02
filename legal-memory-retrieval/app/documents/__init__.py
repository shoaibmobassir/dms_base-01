"""Document versioning: immutable version chain with SHA-256 integrity.

Each edit creates a new version_row. documents.current_version_id
points to the active one. Old versions are never deleted.
"""
from __future__ import annotations

import difflib
import hashlib
import uuid
from datetime import datetime, timezone

from psycopg.rows import dict_row

from app.db.connection import connect


def content_sha256(text: str) -> str:
    """SHA-256 hex digest of document body text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _next_version_number(cur, document_id: str) -> int:
    """Return the next version number for a document (max + 1)."""
    cur.execute(
        "SELECT COALESCE(MAX(version_number), 0) AS mx FROM document_versions WHERE document_id = %(doc_id)s",
        {"doc_id": document_id},
    )
    return cur.fetchone()["mx"] + 1


def create_version(
    document_id: str,
    body: str,
    title: str | None = None,
    author_name: str | None = None,
    source: str = "edit",
    version_status: str = "developing",
    version_label: str | None = None,
) -> dict:
    """Create a new immutable version for an existing document.

    Returns the newly created version row.
    """
    version_id = f"VER-{uuid.uuid4().hex[:10].upper()}"
    sha = content_sha256(body)

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Verify document exists
            cur.execute(
                "SELECT document_id, title, matter_id FROM documents WHERE document_id = %(doc_id)s",
                {"doc_id": document_id},
            )
            doc = cur.fetchone()
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            ver_title = title or doc["title"]
            ver_num = _next_version_number(cur, document_id)
            label = version_label or f"v{ver_num}.0"
            status_map = {
                "draft": "Draft",
                "developing": "Developing",
                "review": "Under Review",
                "final": "Final",
                "executed": "Executed",
                "edit": "Developing",
                "upload": "Draft",
            }
            doc_status = status_map.get(version_status, version_status.replace("_", " ").title())

            cur.execute(
                """
                INSERT INTO document_versions (
                    version_id, document_id, version_number, title, body,
                    content_sha256, author_name, source, version_status, version_label
                ) VALUES (
                    %(vid)s, %(doc_id)s, %(vnum)s, %(title)s, %(body)s,
                    %(sha)s, %(author)s, %(source)s, %(vstatus)s, %(vlabel)s
                )
                RETURNING *
                """,
                {
                    "vid": version_id,
                    "doc_id": document_id,
                    "vnum": ver_num,
                    "title": ver_title,
                    "body": body,
                    "sha": sha,
                    "author": author_name,
                    "source": source,
                    "vstatus": version_status,
                    "vlabel": label,
                },
            )
            version = cur.fetchone()

            # Update documents pointer + body
            cur.execute(
                """
                UPDATE documents SET
                    current_version_id = %(vid)s,
                    body = %(body)s,
                    version = %(version_label)s,
                    status = %(status)s,
                    updated_at = NOW()
                WHERE document_id = %(doc_id)s
                """,
                {
                    "vid": version_id,
                    "doc_id": document_id,
                    "body": body,
                    "version_label": label,
                    "status": doc_status,
                },
            )
            conn.commit()

    return dict(version)


def list_versions(document_id: str) -> list[dict]:
    """List all versions for a document, most recent first."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT version_id, version_number, title, content_sha256,
                       author_name, source, version_status, version_label, created_at,
                       LENGTH(body) AS body_length
                FROM document_versions
                WHERE document_id = %(doc_id)s
                ORDER BY version_number DESC
                """,
                {"doc_id": document_id},
            )
            return list(cur.fetchall())


def get_version(document_id: str, version_id: str) -> dict | None:
    """Get a specific version with full body."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM document_versions
                WHERE document_id = %(doc_id)s AND version_id = %(vid)s
                """,
                {"doc_id": document_id, "vid": version_id},
            )
            return cur.fetchone()


def diff_versions(version_id_a: str, version_id_b: str) -> dict:
    """Unified diff between two versions."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT version_id, version_number, title, body FROM document_versions WHERE version_id = %(vid)s",
                {"vid": version_id_a},
            )
            va = cur.fetchone()
            cur.execute(
                "SELECT version_id, version_number, title, body FROM document_versions WHERE version_id = %(vid)s",
                {"vid": version_id_b},
            )
            vb = cur.fetchone()

    if not va or not vb:
        raise ValueError("One or both versions not found")

    text_a = (va["body"] or "").splitlines(keepends=True)
    text_b = (vb["body"] or "").splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        text_a, text_b,
        fromfile=f"v{va['version_number']} — {va['title']}",
        tofile=f"v{vb['version_number']} — {vb['title']}",
        lineterm="",
    ))
    added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))

    return {
        "version_a": {"version_id": va["version_id"], "version_number": va["version_number"], "title": va["title"]},
        "version_b": {"version_id": vb["version_id"], "version_number": vb["version_number"], "title": vb["title"]},
        "added_lines": added,
        "removed_lines": removed,
        "diff": diff_lines,
    }


def seed_initial_version(document_id: str) -> dict | None:
    """Create v1 from the current document body if no versions exist yet.

    Used for migrating existing documents into the versioning system.
    """
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM document_versions WHERE document_id = %(doc_id)s",
                {"doc_id": document_id},
            )
            if cur.fetchone()["n"] > 0:
                return None  # Already has versions

            cur.execute(
                "SELECT document_id, title, body, author_name FROM documents WHERE document_id = %(doc_id)s",
                {"doc_id": document_id},
            )
            doc = cur.fetchone()
            if not doc or not doc.get("body"):
                return None

    return create_version(
        document_id=document_id,
        body=doc["body"],
        title=doc["title"],
        author_name=doc.get("author_name"),
        source="upload",
        version_status="draft",
        version_label="v1.0 Draft",
    )


def create_developing_version(
    document_id: str,
    author_name: str | None = None,
) -> dict:
    """Branch a new developing version from the current document body."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT document_id, title, body, author_name, version FROM documents WHERE document_id = %(doc_id)s",
                {"doc_id": document_id},
            )
            doc = cur.fetchone()
            if not doc:
                raise ValueError(f"Document {document_id} not found")

    body = (doc["body"] or "").rstrip()
    marker = "\n\n[DEVELOPING — New working version branched for counsel mark-up. Not for external circulation.]"
    if marker.strip() not in body:
        body = body + marker

    cur_ver = _next_version_number_standalone(document_id)
    label = f"v{cur_ver}.0 Developing"

    return create_version(
        document_id=document_id,
        body=body,
        title=doc["title"],
        author_name=author_name or doc.get("author_name"),
        source="developing",
        version_status="developing",
        version_label=label,
    )


def _next_version_number_standalone(document_id: str) -> int:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            return _next_version_number(cur, document_id)
