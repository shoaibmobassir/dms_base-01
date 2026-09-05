"""Version-scoped hierarchical chunks + context envelopes.

Parent chunks = section-level; child chunks = paragraph groups within a section.
Every chunk carries enough metadata to reconstruct:
  client → matter → folder → document → version → section → page
"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from psycopg.rows import dict_row

from app.db.connection import connect
from app.documents.canonical import DocumentBlock


@dataclass
class HierarchicalChunk:
    chunk_id: str
    version_id: str
    document_id: str
    matter_id: str
    folder_path: str
    chunk_index: int
    text: str
    page_number: int
    section_id: Optional[str]
    section_title: Optional[str]
    block_ids: list[str] = field(default_factory=list)
    parent_chunk_id: Optional[str] = None
    is_parent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def context_envelope(
        self,
        *,
        client_name: str = "",
        matter_name: str = "",
        document_name: str = "",
        version_number: int | None = None,
    ) -> str:
        """Metadata envelope for LLM/retrieval context (never naked chunk text)."""
        ver = f"v{version_number}" if version_number is not None else self.version_id
        return (
            f"CLIENT: {client_name or 'n/a'}\n"
            f"MATTER: {matter_name or self.matter_id}\n"
            f"FOLDER: {self.folder_path or 'n/a'}\n"
            f"DOCUMENT: {document_name or self.document_id}\n"
            f"VERSION: {ver} ({self.version_id})\n"
            f"SECTION: {self.section_title or self.section_id or 'n/a'}\n"
            f"PAGE: {self.page_number}\n\n"
            f"{self.text}"
        )


def build_hierarchical_chunks(
    blocks: list[DocumentBlock] | list[dict],
    *,
    document_id: str,
    version_id: str,
    matter_id: str,
    folder_path: str = "",
    max_chars: int = 1200,
) -> list[HierarchicalChunk]:
    """Build parent (section) + child (paragraph-group) chunks from canonical blocks."""
    norm: list[dict] = []
    for b in blocks:
        if isinstance(b, DocumentBlock):
            norm.append(b.to_dict())
        else:
            norm.append(dict(b))

    by_section: dict[str, list[dict]] = defaultdict(list)
    headings: dict[str, str] = {}
    for b in norm:
        sid = b.get("section_id") or "preamble"
        if b.get("block_type") == "heading":
            headings[sid] = b.get("section_title") or b.get("text") or sid
            continue
        by_section[sid].append(b)

    out: list[HierarchicalChunk] = []
    index = 0
    for sid, sec_blocks in by_section.items():
        if not sec_blocks:
            continue
        title = headings.get(sid) or (sec_blocks[0].get("section_title") or f"Section {sid}")
        page = int(sec_blocks[0].get("page_number") or 1)
        full = "\n\n".join(b["text"] for b in sec_blocks if b.get("text"))
        parent_id = f"CHK-{uuid.uuid4().hex[:10].upper()}"

        out.append(
            HierarchicalChunk(
                chunk_id=parent_id,
                version_id=version_id,
                document_id=document_id,
                matter_id=matter_id,
                folder_path=folder_path,
                chunk_index=index,
                text=full[:12000],
                page_number=page,
                section_id=sid,
                section_title=title,
                block_ids=[b["block_id"] for b in sec_blocks if b.get("block_id")],
                parent_chunk_id=None,
                is_parent=True,
            )
        )
        parent_chunk_id = parent_id
        index += 1

        buf: list[dict] = []
        buf_len = 0
        for b in sec_blocks:
            t = b.get("text") or ""
            if buf_len + len(t) > max_chars and buf:
                child_id = f"CHK-{uuid.uuid4().hex[:10].upper()}"
                text = "\n\n".join(x["text"] for x in buf)
                out.append(
                    HierarchicalChunk(
                        chunk_id=child_id,
                        version_id=version_id,
                        document_id=document_id,
                        matter_id=matter_id,
                        folder_path=folder_path,
                        chunk_index=index,
                        text=text,
                        page_number=int(buf[0].get("page_number") or page),
                        section_id=sid,
                        section_title=title,
                        block_ids=[x["block_id"] for x in buf if x.get("block_id")],
                        parent_chunk_id=parent_chunk_id,
                        is_parent=False,
                    )
                )
                index += 1
                buf = []
                buf_len = 0
            buf.append(b)
            buf_len += len(t)
        if buf:
            child_id = f"CHK-{uuid.uuid4().hex[:10].upper()}"
            text = "\n\n".join(x["text"] for x in buf)
            out.append(
                HierarchicalChunk(
                    chunk_id=child_id,
                    version_id=version_id,
                    document_id=document_id,
                    matter_id=matter_id,
                    folder_path=folder_path,
                    chunk_index=index,
                    text=text,
                    page_number=int(buf[0].get("page_number") or page),
                    section_id=sid,
                    section_title=title,
                    block_ids=[x["block_id"] for x in buf if x.get("block_id")],
                    parent_chunk_id=parent_chunk_id,
                    is_parent=False,
                )
            )
            index += 1
    return out


def save_version_chunks(chunks: list[HierarchicalChunk]) -> int:
    """Persist hierarchical chunks for a version (does not overwrite other versions)."""
    if not chunks:
        return 0
    with connect() as conn:
        with conn.cursor() as cur:
            # Remove prior chunks for THIS version only (immutable re-parse safe)
            cur.execute(
                "DELETE FROM chunks WHERE version_id = %(vid)s",
                {"vid": chunks[0].version_id},
            )
            for c in chunks:
                cur.execute(
                    """
                    INSERT INTO chunks (
                        chunk_id, document_id, matter_id, chunk_index, text, tsv,
                        version_id, folder_path, section_id, section_title,
                        page_number, parent_chunk_id, block_ids, is_parent
                    ) VALUES (
                        %(cid)s, %(did)s, %(mid)s, %(idx)s, %(text)s, to_tsvector('english', %(text)s),
                        %(vid)s, %(fpath)s, %(sid)s, %(stitle)s,
                        %(page)s, %(parent)s, %(bids)s, %(is_parent)s
                    )
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        text = EXCLUDED.text,
                        tsv = EXCLUDED.tsv,
                        section_id = EXCLUDED.section_id,
                        section_title = EXCLUDED.section_title,
                        page_number = EXCLUDED.page_number,
                        block_ids = EXCLUDED.block_ids,
                        is_parent = EXCLUDED.is_parent
                    """,
                    {
                        "cid": c.chunk_id,
                        "did": c.document_id,
                        "mid": c.matter_id,
                        "idx": c.chunk_index,
                        "text": c.text,
                        "vid": c.version_id,
                        "fpath": c.folder_path,
                        "sid": c.section_id,
                        "stitle": c.section_title,
                        "page": c.page_number,
                        "parent": c.parent_chunk_id,
                        "bids": c.block_ids,
                        "is_parent": c.is_parent,
                    },
                )
            conn.commit()
    return len(chunks)


def get_version_chunks(version_id: str, *, children_only: bool = False) -> list[dict]:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            sql = """
                SELECT chunk_id, document_id, matter_id, chunk_index, text,
                       version_id, folder_path, section_id, section_title,
                       page_number, parent_chunk_id, block_ids, is_parent
                FROM chunks
                WHERE version_id = %(vid)s
            """
            if children_only:
                sql += " AND COALESCE(is_parent, FALSE) = FALSE"
            sql += " ORDER BY chunk_index ASC"
            cur.execute(sql, {"vid": version_id})
            return list(cur.fetchall())


def build_context_envelope_for_chunk(
    chunk_id: str,
) -> str | None:
    """Load chunk + document/matter names and return envelope text."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT c.*, d.title AS document_name, d.folder_path AS doc_folder_path,
                       m.title AS matter_name, m.client_name,
                       v.version_number
                FROM chunks c
                JOIN documents d ON d.document_id = c.document_id
                JOIN matters m ON m.matter_id = c.matter_id
                LEFT JOIN document_versions v ON v.version_id = c.version_id
                WHERE c.chunk_id = %(cid)s
                """,
                {"cid": chunk_id},
            )
            row = cur.fetchone()
            if not row:
                return None
            hc = HierarchicalChunk(
                chunk_id=row["chunk_id"],
                version_id=row.get("version_id") or "",
                document_id=row["document_id"],
                matter_id=row["matter_id"],
                folder_path=row.get("folder_path") or row.get("doc_folder_path") or "",
                chunk_index=row["chunk_index"],
                text=row["text"],
                page_number=row.get("page_number") or 1,
                section_id=row.get("section_id"),
                section_title=row.get("section_title"),
                block_ids=list(row.get("block_ids") or []),
                parent_chunk_id=row.get("parent_chunk_id"),
                is_parent=bool(row.get("is_parent")),
            )
            return hc.context_envelope(
                client_name=row.get("client_name") or "",
                matter_name=row.get("matter_name") or "",
                document_name=row.get("document_name") or "",
                version_number=row.get("version_number"),
            )
