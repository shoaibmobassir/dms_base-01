"""Canonical Document AST & Block Parser.

Decomposes legal text into structured, typed DocumentBlock nodes with
deterministic character offsets, section hierarchy, and SHA-256 hashes.
This forms the foundational layer for durable anchoring, multi-level diffs,
and hierarchical retrieval.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional, Sequence

from psycopg.rows import dict_row

from app.db.connection import connect


@dataclass
class DocumentBlock:
    block_id: str
    version_id: str
    document_id: str
    page_number: int
    sequence: int
    section_id: Optional[str]
    section_title: Optional[str]
    block_type: str  # heading | paragraph | clause | table | footnote | signature | list
    text: str
    text_hash: str
    start_offset: int
    end_offset: int
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_block_hash(text: str) -> str:
    """SHA-256 hex digest of normalized block text."""
    normalized = " ".join(text.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


_RE_HEADING = re.compile(
    r"^(?:ARTICLE|SECTION|CLAUSE|SCHEDULE|EXHIBIT|ANNEX|PART)\s+([0-9IVXLCDM\.]+)\.?\s*[:\-—]?\s*(.*)$",
    re.IGNORECASE,
)
_RE_NUMBERED_CLAUSE = re.compile(
    r"^([0-9]+\.[0-9]+(?:\.[0-9]+)*)\.?\s+(.+)$"
)
_RE_LETTERED_CLAUSE = re.compile(
    r"^\(([a-zA-Z0-9]+)\)\s+(.+)$"
)
_RE_SIGNATURE = re.compile(
    r"^(?:IN WITNESS WHEREOF|EXECUTED as a deed|SIGNED by|FOR AND ON BEHALF OF)",
    re.IGNORECASE,
)
_RE_FOOTNOTE = re.compile(
    r"^\[(?:[0-9]+|\*)\]\s+"
)
_RE_MD_SECTION = re.compile(
    r"^##\s+Section\s+([\d.]+)\.\s+(.+)$",
    re.IGNORECASE,
)


def _page_for_offset(
    offset: int,
    page_spans: Sequence[Any] | None,
    approx_chars_per_page: int,
) -> int:
    if page_spans:
        for p in page_spans:
            start = getattr(p, "start_offset", None)
            end = getattr(p, "end_offset", None)
            num = getattr(p, "page_number", None)
            if start is None and isinstance(p, dict):
                start, end, num = p["start_offset"], p["end_offset"], p["page_number"]
            if start is not None and end is not None and start <= offset < end:
                return int(num)
        last = page_spans[-1]
        return int(
            getattr(last, "page_number", None)
            or (last["page_number"] if isinstance(last, dict) else 1)
        )
    return max(1, (offset // approx_chars_per_page) + 1)


def parse_canonical_blocks(
    body: str,
    document_id: str,
    version_id: str,
    approx_chars_per_page: int = 3000,
    page_spans: Sequence[Any] | None = None,
) -> List[DocumentBlock]:
    """Parse legal text into AST blocks. ``page_spans`` supplies real PDF/DOCX pages."""
    if not body:
        return []

    raw_paragraphs: list[str] = []
    for page_part in body.split("\f"):
        parts = [p for p in page_part.split("\n\n") if p.strip()]
        raw_paragraphs.extend(parts)

    blocks: List[DocumentBlock] = []
    current_section_id: Optional[str] = None
    current_section_title: Optional[str] = None
    seq = 0
    current_search_pos = 0

    for raw_p in raw_paragraphs:
        cleaned_text = raw_p.strip()
        if not cleaned_text:
            continue

        start_offset = body.find(raw_p, current_search_pos)
        if start_offset == -1:
            start_offset = current_search_pos
        end_offset = start_offset + len(raw_p)
        current_search_pos = end_offset

        page_number = _page_for_offset(start_offset, page_spans, approx_chars_per_page)
        seq += 1
        block_id = f"BLK-{uuid.uuid4().hex[:10].upper()}"
        text_hash = compute_block_hash(cleaned_text)

        heading_match = _RE_HEADING.match(cleaned_text)
        md_match = _RE_MD_SECTION.match(cleaned_text)
        clause_match = _RE_NUMBERED_CLAUSE.match(cleaned_text)
        letter_match = _RE_LETTERED_CLAUSE.match(cleaned_text)
        sig_match = _RE_SIGNATURE.match(cleaned_text)
        footnote_match = _RE_FOOTNOTE.match(cleaned_text)

        if heading_match or md_match:
            m = heading_match or md_match
            assert m is not None
            current_section_id = m.group(1).strip()
            current_section_title = m.group(2).strip() or None
            block_type = "heading"
            meta: dict[str, Any] = {"is_header": True, "level": 1}
        elif clause_match:
            current_section_id = clause_match.group(1).strip()
            rest = clause_match.group(2).strip()
            current_section_title = rest.split(".")[0][:120] if rest else current_section_title
            block_type = "clause"
            meta = {"clause_num": current_section_id}
        elif letter_match:
            block_type = "clause"
            meta = {"subclause_num": letter_match.group(1)}
        elif sig_match:
            block_type = "signature"
            meta = {"is_execution_block": True}
        elif footnote_match:
            block_type = "footnote"
            meta = {"is_footnote": True}
        elif "|" in cleaned_text and cleaned_text.count("|") >= 2:
            block_type = "table"
            meta = {"is_table": True}
        elif cleaned_text.lstrip().startswith(("- ", "* ", "• ")):
            block_type = "list"
            meta = {"is_list": True}
        else:
            block_type = "paragraph"
            meta = {}

        meta["page_source"] = "span" if page_spans else "heuristic"

        blocks.append(
            DocumentBlock(
                block_id=block_id,
                version_id=version_id,
                document_id=document_id,
                page_number=page_number,
                sequence=seq,
                section_id=current_section_id,
                section_title=current_section_title,
                block_type=block_type,
                text=cleaned_text,
                text_hash=text_hash,
                start_offset=start_offset,
                end_offset=end_offset,
                metadata=meta,
            )
        )

    return blocks


def parse_from_extracted(
    extracted: Any,
    document_id: str,
    version_id: str,
) -> List[DocumentBlock]:
    """Parse blocks from an ExtractedDocument (page-aware)."""
    return parse_canonical_blocks(
        body=extracted.text,
        document_id=document_id,
        version_id=version_id,
        page_spans=getattr(extracted, "pages", None),
    )


def save_canonical_blocks(blocks: List[DocumentBlock]) -> int:
    """Persist a list of canonical blocks into PostgreSQL."""
    if not blocks:
        return 0

    with connect() as conn:
        with conn.cursor() as cur:
            for b in blocks:
                cur.execute(
                    """
                    INSERT INTO document_blocks (
                        block_id, version_id, document_id, page_number, sequence,
                        section_id, section_title, block_type, text, text_hash,
                        start_offset, end_offset, metadata
                    ) VALUES (
                        %(bid)s, %(vid)s, %(did)s, %(page)s, %(seq)s,
                        %(sec_id)s, %(sec_title)s, %(btype)s, %(text)s, %(thash)s,
                        %(soff)s, %(eoff)s, %(meta)s
                    )
                    ON CONFLICT (block_id) DO UPDATE SET
                        text = EXCLUDED.text,
                        text_hash = EXCLUDED.text_hash,
                        metadata = EXCLUDED.metadata
                    """,
                    {
                        "bid": b.block_id,
                        "vid": b.version_id,
                        "did": b.document_id,
                        "page": b.page_number,
                        "seq": b.sequence,
                        "sec_id": b.section_id,
                        "sec_title": b.section_title,
                        "btype": b.block_type,
                        "text": b.text,
                        "thash": b.text_hash,
                        "soff": b.start_offset,
                        "eoff": b.end_offset,
                        "meta": json.dumps(b.metadata),
                    },
                )
            conn.commit()
    return len(blocks)


def get_version_blocks(version_id: str) -> List[dict]:
    """Retrieve all canonical blocks for a version in reading sequence."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT block_id, version_id, document_id, page_number, sequence,
                       section_id, section_title, block_type, text, text_hash,
                       start_offset, end_offset, metadata, created_at
                FROM document_blocks
                WHERE version_id = %(vid)s
                ORDER BY sequence ASC
                """,
                {"vid": version_id},
            )
            return list(cur.fetchall())
