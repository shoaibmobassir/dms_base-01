"""Give existing versions a clean stored file (plan 21, C2).

Versions saved before the commit model keep the author's tracked changes inside the stored .docx, so the current
version of such a document is not clean and a download carries its whole edit trail. For each Word version still
unchecked (``is_clean IS NULL``):

- no tracked changes: just marked clean;
- tracked changes: the file with every change accepted is stored beside it (``versions/vNNN/clean.docx``), the
  version points at that, and the file it had is kept as ``source_storage_uri``. ``body`` is unchanged (it already
  holds the accepted text), so chunks, vectors and search are untouched.

Nothing is deleted and the run can be repeated or resumed: a row is only touched while ``is_clean IS NULL``.
Versions whose file cannot be read on this machine are reported and skipped.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from app.documents import docx_review
from app.storage.object_store import get_object_store

log = logging.getLogger(__name__)
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _is_docx(data: bytes) -> bool:
    if data[:2] != b"PK":
        return False
    try:
        from io import BytesIO
        from zipfile import ZipFile

        ZipFile(BytesIO(data)).getinfo("word/document.xml")
        return True
    except (KeyError, Exception):
        return False


def clean_versions(conn, *, apply: bool = False, document_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
    """Convert (or, without ``apply``, only count) unchecked Word versions. Returns counts and examples."""
    store = get_object_store()
    rows = conn.execute(
        """SELECT version_id, document_id, version_number, storage_uri FROM document_versions
           WHERE is_clean IS NULL AND storage_uri IS NOT NULL AND (%s::text IS NULL OR document_id = %s)
           ORDER BY document_id, version_number LIMIT %s""",
        (document_id, document_id, limit or 1_000_000)).fetchall()
    counts: Counter[str] = Counter()
    per_document: Counter[str] = Counter()
    unreadable: list[str] = []
    for r in rows:
        try:
            data = store.get(r["storage_uri"])
        except Exception:
            counts["file_missing"] += 1
            unreadable.append(r["version_id"])
            continue
        if not _is_docx(data):
            counts["not_word"] += 1
            continue
        if not docx_review.has_revisions(data):
            counts["already_clean"] += 1
            if apply:
                conn.execute("UPDATE document_versions SET is_clean = true WHERE version_id = %s", (r["version_id"],))
            continue
        counts["to_clean"] += 1
        per_document[r["document_id"]] += 1
        if not apply:
            continue
        clean = docx_review.accept_everything(data)
        folder = r["storage_uri"].rsplit("/", 1)[0]
        new_uri = store.put(folder + "/clean.docx", clean, content_type=DOCX_MIME)
        if new_uri == r["storage_uri"]:  # the store keyed both to one file: never overwrite the only copy
            raise RuntimeError(f"clean copy of {r['version_id']} would overwrite its original")
        conn.execute(
            "UPDATE document_versions SET storage_uri = %s, source_storage_uri = coalesce(source_storage_uri, %s), "
            "is_clean = true, file_size_bytes = %s WHERE version_id = %s",
            (new_uri, r["storage_uri"], len(clean), r["version_id"]))
    if apply:
        conn.commit()
    return {"applied": apply, "checked": len(rows), **dict(counts),
            "documents_to_clean": dict(per_document.most_common(10)), "unreadable": unreadable[:10]}
