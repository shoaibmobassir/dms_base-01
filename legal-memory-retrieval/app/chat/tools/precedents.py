"""Find the firm's precedents for a clause (plan 22, W3.4).

The lawyer selects a clause and asks how it compares with what the firm has used before. This searches only firm
material — the firm template library first, then documents on the firm's matters the member may read — by meaning
(the clause's vector against chunk vectors), never personal libraries or projects, and never the document the clause
came from. It returns verbatim passages with doc-N labels so the comparison can quote and cite them.
"""
from __future__ import annotations

import re
from typing import Any

from app.api.acl import doc_read
from app.chat.tools.document_tools import DocIndex
from app.chat.tools.firm_tools import _register

# Below this cosine similarity a passage is about something else (measured on the demo corpus: on-point clauses
# score 0.7–0.8, unrelated authorities 0.45–0.55).
MIN_SIMILARITY = 0.6
_PRECEDENT_HINT = re.compile(r"precedent|template|standard|form|model|know[- ]?how", re.I)


def _vector_literal(text: str) -> str:
    from app.embeddings.pending import _get_embedder

    vec = _get_embedder().encode([text])[0]
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"


def find_precedents(conn: Any, member_id: str | None, text: str, exclude_document_id: str | None = None,
                    limit: int = 6) -> list[dict]:
    """The closest firm passages to ``text``, one per document, firm templates and precedent folders first."""
    clause = " ".join((text or "").split())[:2000]
    if len(clause) < 20:
        return []
    params = {"v": _vector_literal(clause), "ex": (exclude_document_id or "").upper(), "member_id": member_id}
    found = conn.execute(
        f"""
        WITH near AS (
            SELECT c.document_id, c.chunk_id, c.page_number, c.text, c.embedding <=> %(v)s::vector AS dist
            FROM chunks c JOIN documents d ON d.document_id = c.document_id
            LEFT JOIN permissions p ON p.matter_id = d.matter_id
            WHERE c.embedding IS NOT NULL AND NOT coalesce(c.is_parent, false)
              AND (c.version_id IS NULL OR c.version_id = d.current_version_id)
              AND d.archived_at IS NULL AND d.home_kind IN ('matter', 'firm') AND d.document_id <> %(ex)s
              AND {doc_read('d')}
            ORDER BY dist
            LIMIT 80
        )
        SELECT DISTINCT ON (n.document_id) n.*, d.title, d.document_type, d.folder_path, d.home_kind, m.matter_code
        FROM near n JOIN documents d ON d.document_id = n.document_id
        LEFT JOIN matters m ON m.matter_id = d.matter_id
        ORDER BY n.document_id, n.dist
        """,
        params,
    ).fetchall()

    def precedent(r: dict) -> bool:
        return r["home_kind"] == "firm" or bool(_PRECEDENT_HINT.search(f"{r['document_type'] or ''} {r['folder_path'] or ''}"))

    ranked, seen = [], set()
    if params["ex"]:
        # copies of the source document (same words) are not precedents for it
        for c in conn.execute(
                """SELECT c.text FROM chunks c JOIN documents d ON d.document_id = c.document_id
                   WHERE c.document_id = %s AND (c.version_id IS NULL OR c.version_id = d.current_version_id)""",
                (params["ex"],)).fetchall():
            seen.add(" ".join(str(c["text"] or "").lower().split())[:400])
    for r in sorted((dict(r) for r in found), key=lambda r: (not precedent(r), r["dist"])):
        key = " ".join(str(r["text"] or "").lower().split())[:400]
        if key in seen:  # copies of one document say the same thing once
            continue
        seen.add(key)
        ranked.append(r)
    out = []
    for r in ranked:
        r["is_precedent"] = precedent(r)
        r["similarity"] = round(1 - float(r.pop("dist")), 3)
        if r["similarity"] >= MIN_SIMILARITY:
            out.append(r)
    return out[:limit]


def find_precedents_tool(arguments: dict, doc_index: DocIndex, conn: Any, member_id: str | None) -> dict[str, Any]:
    text = str(arguments.get("text") or "")
    if len(" ".join(text.split())) < 20:
        return {"error": "Give the clause itself (at least a sentence) to compare."}
    exclude = None
    ref = str(arguments.get("document") or "").strip()
    if ref:
        entry = doc_index.get(ref)
        exclude = entry.document_id if entry else ref
    hits = find_precedents(conn, member_id, text, exclude, limit=min(int(arguments.get("limit") or 6), 10))
    passages = [{
        "doc_id": _register(doc_index, h["document_id"], h["title"]), "filename": h["title"], "page": h["page_number"],
        "matter_code": h["matter_code"], "kind": "firm template" if h["home_kind"] == "firm" else "matter document",
        "precedent_folder": h["is_precedent"], "similarity": h["similarity"],
        "text": " ".join(str(h["text"] or "").split())[:900],
    } for h in hits]
    return {
        "passages": passages,
        "note": ("Compare the clause point by point with these passages (closest first; firm templates and precedent "
                 "folders ranked ahead). Quote and cite each passage you rely on with its doc-N label. Say plainly if "
                 "none of them deals with the same point." if passages else
                 "No firm precedent on this point was found; say so rather than comparing with general knowledge."),
        "event": {"type": "precedents", "count": len(passages)},
    }
