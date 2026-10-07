"""A page of a document the lawyer dragged into the Assistant.

The viewer shows a document as Pages (a file with real pages) or Parts (a fixed run of passages, for a Word file with
no page rendition). A reference carries that same address, so "this page" means exactly what was on screen, and the
Assistant gets the text of it up front instead of having to guess what "page 9" refers to.
"""
from __future__ import annotations

from typing import Any

from app.chat.models import FileAttachment
from app.api.acl import ACL_CLAUSE, doc_acl, doc_read

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


def rendered_page_text(conn, document_id: str, version_id: str | None, number: int) -> str | None:
    """The text of page ``number`` of the file as the viewer renders it (cached rendition), or None."""
    import io

    from pypdf import PdfReader

    from app.documents.pdf_render import to_pdf
    from app.storage.object_store import get_object_store

    row = conn.execute(
        """SELECT v.storage_uri, coalesce(v.mime_type, d.mime_type) AS mime, d.title
           FROM documents d JOIN document_versions v ON v.version_id = COALESCE(%s, d.current_version_id)
           WHERE d.document_id = %s""",
        (version_id, document_id),
    ).fetchone()
    if not row or not row["storage_uri"]:
        return None
    try:
        pdf = PdfReader(io.BytesIO(to_pdf(get_object_store().get(row["storage_uri"]), row["mime"], row["title"])))
        if not 1 <= number <= len(pdf.pages):
            return None
        return (pdf.pages[number - 1].extract_text() or "").strip()
    except Exception:  # noqa: BLE001 — no rendition: fall back to the stored text
        return None


def reference_text(conn, document_id: str, version_id: str | None, unit: str, number: int, part_size: int,
                   rendered: bool = False) -> str:
    """The text on that page or part, as the viewer shows it."""
    if rendered and unit == "page":
        text = rendered_page_text(conn, document_id, version_id, number)
        if text is not None:
            return text
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
            WHERE d.document_id = %(id)s AND {doc_read('d')}
            """,
            {"id": f.document_id, "member_id": member_id},
        ).fetchone()
        if not allowed:
            continue
        text = reference_text(conn, f.document_id, ref.version_id, ref.unit, ref.number, ref.part_size, ref.rendered)
        out.append({"document_id": f.document_id, "filename": allowed["title"], "unit": ref.unit, "number": ref.number,
                    "version_id": ref.version_id, "text": text[:MAX_REFERENCE_CHARS],
                    "truncated": len(text) > MAX_REFERENCE_CHARS})
        if len(out) >= MAX_REFERENCES:
            break
    return out


MAX_OUTLINE_DOCS = 3
MAX_OUTLINE_HEADINGS = 60


def outline_note(conn, document_ids: list[str], member_id: str | None) -> str:
    """The current headings of the documents in play, read fresh each turn.

    A later turn does not have the document text in front of it; without this the model described and renumbered
    sections from memory ("sections 1 to 27" of a six-section agreement). Headings are short and exact, so they
    ground any talk of numbering or structure in what the current version says.
    """
    lines: list[str] = []
    for doc_id in list(dict.fromkeys(document_ids))[:MAX_OUTLINE_DOCS]:
        row = conn.execute(
            f"""
            SELECT d.document_id, d.title FROM documents d LEFT JOIN permissions p ON p.matter_id = d.matter_id
            WHERE d.document_id = %(id)s AND {doc_read('d')}
            """,
            {"id": doc_id, "member_id": member_id},
        ).fetchone()
        if not row:
            continue
        heads = [r["text"] for r in conn.execute(
            """SELECT b.text FROM document_blocks b JOIN documents d ON d.current_version_id = b.version_id
               WHERE b.document_id = %s AND b.block_type = 'heading' ORDER BY b.sequence LIMIT %s""",
            (doc_id, MAX_OUTLINE_HEADINGS + 1))]
        if not heads:
            continue
        more = len(heads) > MAX_OUTLINE_HEADINGS
        lines.append(f"- {row['title']}: " + " | ".join(h[:120] for h in heads[:MAX_OUTLINE_HEADINGS]) + (" | …" if more else ""))
    if not lines:
        return ""
    return ("\n\nCURRENT HEADINGS OF THE DOCUMENTS IN THIS CONVERSATION (exact, from the current version; use these for "
            "any numbering or structure, and read the document for anything else):\n" + "\n".join(lines))


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
