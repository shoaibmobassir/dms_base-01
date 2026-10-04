"""A page of a document the lawyer dragged into the Assistant.

The viewer shows a document as Pages (a file with real pages) or Parts (a fixed run of passages, for a Word file with
no page rendition). A reference carries that same address, so "this page" means exactly what was on screen, and the
Assistant gets the text of it up front instead of having to guess what "page 9" refers to.
"""
from __future__ import annotations

from typing import Any

from app.chat.models import FileAttachment
from app.api.acl import ACL_CLAUSE, doc_acl

MAX_REFERENCE_CHARS = 6000
MAX_REFERENCES = 5


def _blocks(conn, document_id: str, version_id: str | None) -> list[dict]:
    rows = conn.execute(
        """
        SELECT b.page_number, b.text
        FROM document_blocks b JOIN documents d ON d.document_id = b.document_id
        WHERE b.document_id = %s AND b.version_id = COALESCE(%s, d.current_version_id)
        ORDER BY b.sequence ASC
        """,
        (document_id, version_id),
    ).fetchall()
    return [dict(r) for r in rows]


def reference_text(conn, document_id: str, version_id: str | None, unit: str, number: int, part_size: int) -> str:
    """The text on that page or part, as the viewer shows it."""
    blocks = _blocks(conn, document_id, version_id)
    if unit == "page":
        picked = [b for b in blocks if (b["page_number"] or 1) == number]
    else:
        size = max(1, min(part_size, 50))
        picked = blocks[(number - 1) * size: number * size]
    return "\n\n".join(b["text"] for b in picked if b["text"]).strip()


def resolve_references(conn, files: list[FileAttachment] | None, member_id: str | None) -> list[dict[str, Any]]:
    """References on this message that the member may read, with the text of each."""
    out: list[dict[str, Any]] = []
    for f in files or []:
        ref = f.reference
        if ref is None or not f.document_id:
            continue
        allowed = conn.execute(
            f"""
            SELECT d.document_id, d.title FROM documents d LEFT JOIN permissions p ON p.matter_id = d.matter_id
            WHERE d.document_id = %(id)s AND {ACL_CLAUSE} AND {doc_acl('d')}
            """,
            {"id": f.document_id, "member_id": member_id},
        ).fetchone()
        if not allowed:
            continue
        text = reference_text(conn, f.document_id, ref.version_id, ref.unit, ref.number, ref.part_size)
        out.append({"document_id": f.document_id, "filename": allowed["title"], "unit": ref.unit, "number": ref.number,
                    "version_id": ref.version_id, "text": text[:MAX_REFERENCE_CHARS],
                    "truncated": len(text) > MAX_REFERENCE_CHARS})
        if len(out) >= MAX_REFERENCES:
            break
    return out


def reference_note(refs: list[dict[str, Any]]) -> str:
    """System-prompt text naming what the user pointed at and quoting it."""
    if not refs:
        return ""
    lines = ["\n\nTHE USER POINTED AT THESE PASSAGES (\"this page\", \"this part\", \"here\" mean these; the text is "
             "exactly what they saw on screen; work on it, and quote from it when you propose edits):"]
    for r in refs:
        label = f"{r['unit'].capitalize()} {r['number']}"
        lines.append(f"\n--- {label} of {r['filename']} (document {r['document_id']}) ---\n"
                     + (r["text"] or "(no text on it)")
                     + ("\n[cut short]" if r["truncated"] else ""))
    return "\n".join(lines)
