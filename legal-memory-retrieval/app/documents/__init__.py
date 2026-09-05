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


from app.documents.canonical import (
    DocumentBlock,
    compute_block_hash,
    get_version_blocks,
    parse_canonical_blocks,
    parse_from_extracted,
    save_canonical_blocks,
)
from app.documents.hierarchical_chunks import (
    build_hierarchical_chunks,
    save_version_chunks,
)
from app.documents.anchor import AnchorTarget, ResolvedAnchor, resolve_anchor
from app.documents.diff import (
    MaterialLegalChange,
    VersionDiffResult,
    compute_semantic_diff,
    compute_word_redline,
    diff_document_versions,
)


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
    change_summary: str | None = None,
    storage_uri: str | None = None,
    parent_version_id: str | None = None,
    page_spans: list | None = None,
    folder_path: str | None = None,
) -> dict:
    """Create a new immutable version for an existing document with canonical blocks.

    Returns the newly created version row (includes ``block_count`` / ``chunk_count``).
    """
    version_id = f"VER-{uuid.uuid4().hex[:10].upper()}"
    sha = content_sha256(body)

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Verify document exists
            cur.execute(
                """
                SELECT document_id, title, matter_id, current_version_id, folder_path
                FROM documents WHERE document_id = %(doc_id)s
                """,
                {"doc_id": document_id},
            )
            doc = cur.fetchone()
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            ver_title = title or doc["title"]
            ver_num = _next_version_number(cur, document_id)
            label = version_label or f"v{ver_num}.0"
            parent_vid = parent_version_id or doc.get("current_version_id")
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
            summary = change_summary or ("initial" if ver_num == 1 else f"revision {label}")
            fpath = folder_path if folder_path is not None else (doc.get("folder_path") or "")

            cur.execute(
                """
                INSERT INTO document_versions (
                    version_id, document_id, version_number, title, body,
                    content_sha256, author_name, source, version_status, version_label,
                    parent_version_id, storage_uri, change_summary
                ) VALUES (
                    %(vid)s, %(doc_id)s, %(vnum)s, %(title)s, %(body)s,
                    %(sha)s, %(author)s, %(source)s, %(vstatus)s, %(vlabel)s,
                    %(parent)s, %(storage)s, %(summary)s
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
                    "parent": parent_vid,
                    "storage": storage_uri,
                    "summary": summary,
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

    # Automatically parse & persist canonical AST blocks + hierarchical chunks
    block_count = 0
    chunk_count = 0
    try:
        blocks = parse_canonical_blocks(
            body, document_id, version_id, page_spans=page_spans
        )
        block_count = save_canonical_blocks(blocks)
        hchunks = build_hierarchical_chunks(
            blocks,
            document_id=document_id,
            version_id=version_id,
            matter_id=doc["matter_id"],
            folder_path=fpath or "",
        )
        chunk_count = save_version_chunks(hchunks)
    except Exception as exc:  # noqa: BLE001 — version row must remain even if parser fails
        import logging

        logging.getLogger(__name__).warning(
            "canonical blocks/chunks not saved for %s: %s", version_id, exc
        )

    out = dict(version)
    out["block_count"] = block_count
    out["chunk_count"] = chunk_count
    return out


def list_versions(document_id: str) -> list[dict]:
    """List all versions for a document, most recent first."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT version_id, version_number, title, content_sha256,
                       author_name, source, version_status, version_label, created_at,
                       parent_version_id, storage_uri, change_summary,
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


def create_annotation(
    document_id: str,
    version_id: str,
    quoted_text: str,
    annotation_type: str = "user_highlight",
    block_id: str | None = None,
    page_number: int = 1,
    start_offset: int = 0,
    end_offset: int = 0,
    author_id: str | None = None,
    author_name: str | None = None,
    finding_id: str | None = None,
    content: str | None = None,
) -> dict:
    """Create a durable annotation anchored to content and blocks."""
    annotation_id = f"ANN-{uuid.uuid4().hex[:10].upper()}"
    thash = compute_block_hash(quoted_text)

    # If block_id is missing, attempt to resolve via anchor resolver
    if not block_id:
        resolved = resolve_anchor(
            AnchorTarget(
                version_id=version_id,
                quoted_text=quoted_text,
                text_hash=thash,
                page_number=page_number,
                start_offset=start_offset,
                end_offset=end_offset,
            )
        )
        if resolved.found:
            block_id = resolved.block_id
            page_number = resolved.page_number
            start_offset = resolved.start_offset
            end_offset = resolved.end_offset

    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO annotations (
                    annotation_id, document_id, version_id, block_id, annotation_type,
                    author_id, author_name, finding_id, page_number, start_offset,
                    end_offset, quoted_text, text_hash, content
                ) VALUES (
                    %(aid)s, %(did)s, %(vid)s, %(bid)s, %(atype)s,
                    %(auth_id)s, %(auth_name)s, %(fid)s, %(page)s, %(soff)s,
                    %(eoff)s, %(quote)s, %(thash)s, %(content)s
                )
                RETURNING *
                """,
                {
                    "aid": annotation_id,
                    "did": document_id,
                    "vid": version_id,
                    "bid": block_id,
                    "atype": annotation_type,
                    "auth_id": author_id,
                    "auth_name": author_name,
                    "fid": finding_id,
                    "page": page_number,
                    "soff": start_offset,
                    "eoff": end_offset,
                    "quote": quoted_text,
                    "thash": thash,
                    "content": content,
                },
            )
            row = cur.fetchone()
            conn.commit()
            return dict(row)


def list_annotations(document_id: str, version_id: str | None = None) -> list[dict]:
    """List annotations for a document / version."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if version_id:
                cur.execute(
                    """
                    SELECT * FROM annotations
                    WHERE document_id = %(did)s AND version_id = %(vid)s AND status = 'active'
                    ORDER BY created_at ASC
                    """,
                    {"did": document_id, "vid": version_id},
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM annotations
                    WHERE document_id = %(did)s AND status = 'active'
                    ORDER BY created_at ASC
                    """,
                    {"did": document_id},
                )
            return list(cur.fetchall())


def list_version_findings(document_id: str, version_id: str) -> list[dict]:
    """Retrieve all structured AI findings and their evidence anchors for a document version."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT f.*,
                       COALESCE(
                           json_agg(
                               json_build_object(
                                   'anchor_id', a.anchor_id,
                                   'block_id', a.block_id,
                                   'page_number', a.page_number,
                                   'start_offset', a.start_offset,
                                   'end_offset', a.end_offset,
                                   'quoted_text', a.quoted_text,
                                   'text_hash', a.text_hash,
                                   'confidence', a.anchor_confidence,
                                   'tier', a.resolution_tier
                               )
                           ) FILTER (WHERE a.anchor_id IS NOT NULL), '[]'
                       ) AS evidence_anchors
                FROM findings f
                LEFT JOIN evidence_anchors a ON a.finding_id = f.finding_id
                WHERE f.document_id = %(did)s AND f.version_id = %(vid)s
                GROUP BY f.finding_id
                ORDER BY f.created_at DESC
                """,
                {"did": document_id, "vid": version_id},
            )
            return list(cur.fetchall())


def seed_initial_version(document_id: str) -> dict | None:
    """Create v1 from the current document body if no versions exist yet."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT COUNT(*) AS n FROM document_versions WHERE document_id = %(doc_id)s",
                {"doc_id": document_id},
            )
            if cur.fetchone()["n"] > 0:
                return None

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

