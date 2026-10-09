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
from typing import Collection, Any, List, Optional, Sequence

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


# The section number must be real numbering followed by a delimiter: digits ("12.3"),
# upper-case Roman numerals ("IV") or a single letter ("A"). Matching the number
# case-insensitively read "SECTION Meeting" as section "M", title "eeting".
_RE_HEADING = re.compile(
    r"^(?i:ARTICLE|SECTION|CLAUSE|SCHEDULE|EXHIBIT|ANNEX|PART)\s+"
    r"(\d+(?:\.\d+)*|[IVXLCDM]+|[A-Z])(?=$|[\s.:\-—])\.?\s*[:\-—]?\s*(.*)$"
)
# Unnumbered headings in text indexed before 2026-10-04, when the DOCX extractor still wrote Heading-style paragraphs
# as "SECTION <text>". Kept so those stored bodies parse the same until they are re-indexed.
_RE_UNNUMBERED_HEADING = re.compile(r"^SECTION\s+(\S.{0,158})$")
# A short numbered line with no closing punctuation is a heading: "5. Remuneration", "2.1 Definitions".
_RE_NUMBERED_HEADING = re.compile(r"^(\d{1,3}(?:\.\d{1,3})*)\.?\s+([A-Z(][^\n]{0,118}?)\s*$")
_HEADING_MAX_WORDS = 12


def numbered_heading(text: str) -> tuple[str, str] | None:
    """("5", "Remuneration") for a short numbered heading line; None for a numbered sentence or clause."""
    m = _RE_NUMBERED_HEADING.match(text)
    if not m or text.rstrip()[-1] in ".;:," or len(text.split()) > _HEADING_MAX_WORDS:
        return None
    return m.group(1), m.group(2).strip()


def caps_heading(text: str) -> bool:
    """A short line in capitals with no closing full stop ("EMPLOYMENT AGREEMENT — CHIEF TECHNOLOGY OFFICER")."""
    letters = [c for c in text if c.isalpha()]
    return (len(letters) >= 4 and all(c.isupper() for c in letters) and "\n" not in text
            and len(text.split()) <= 14 and not text.rstrip().endswith("."))
_HEADING_MAX_CHARS = 200
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


def _heading_slug(title: str) -> str:
    """Stable section id for an unnumbered heading ("Specific disclosure" → "specific-disclosure")."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "section"


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
    headings: Collection[str] | None = None,
) -> List[DocumentBlock]:
    """Parse legal text into AST blocks. ``page_spans`` supplies real PDF/DOCX pages; ``headings`` the paragraphs the
    source file styles as headings (a Word file's Heading styles), which are headings whatever their wording."""
    if not body:
        return []
    styled = {" ".join(h.split()) for h in headings or ()}

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

        heading_match = _RE_HEADING.match(cleaned_text) if len(cleaned_text) <= _HEADING_MAX_CHARS else None
        plain_heading = (
            _RE_UNNUMBERED_HEADING.match(cleaned_text)
            if heading_match is None and "\n" not in cleaned_text else None
        )
        md_match = _RE_MD_SECTION.match(cleaned_text)
        clause_match = _RE_NUMBERED_CLAUSE.match(cleaned_text)
        letter_match = _RE_LETTERED_CLAUSE.match(cleaned_text)
        sig_match = _RE_SIGNATURE.match(cleaned_text)
        footnote_match = _RE_FOOTNOTE.match(cleaned_text)

        styled_heading = bool(styled) and " ".join(cleaned_text.split()) in styled
        numbered = numbered_heading(cleaned_text) if heading_match is None and not md_match and "\n" not in cleaned_text else None
        if styled_heading and not heading_match and not md_match:
            current_section_id, current_section_title = numbered or (_heading_slug(cleaned_text), cleaned_text)
            block_type = "heading"
            meta = {"is_header": True, "level": 1, "numbered": numbered is not None, "styled": True}
        elif numbered and not plain_heading:
            current_section_id, current_section_title = numbered
            block_type = "heading"
            meta = {"is_header": True, "level": 1, "numbered": True}
        elif plain_heading and not md_match:
            current_section_title = plain_heading.group(1).strip()
            current_section_id = _heading_slug(current_section_title)
            block_type = "heading"
            meta = {"is_header": True, "level": 1, "numbered": False}
        elif heading_match or md_match:
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
        elif caps_heading(cleaned_text):
            current_section_title = cleaned_text.strip()
            current_section_id = _heading_slug(current_section_title)
            block_type = "heading"
            meta = {"is_header": True, "level": 1, "numbered": False}
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
        headings=getattr(extracted, "headings", None),
    )


def save_canonical_blocks(blocks: List[DocumentBlock]) -> int:
    """Persist canonical blocks, one row per (version_id, sequence).

    Re-parsing a version (reindex, review, diff, lazy block load) updates the
    existing rows instead of appending copies. The stored block_id is kept and
    written back onto each ``DocumentBlock`` so callers that link chunks or
    anchors to blocks use the persisted id.
    """
    if not blocks:
        return 0

    with connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
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
                    ON CONFLICT (version_id, sequence) DO UPDATE SET
                        -- A parse without page spans puts every block on page 1;
                        -- keep the page a page-aware parse recorded earlier.
                        page_number = CASE WHEN EXCLUDED.page_number <> 1 THEN EXCLUDED.page_number
                                           ELSE document_blocks.page_number END,
                        section_id = EXCLUDED.section_id,
                        section_title = EXCLUDED.section_title,
                        block_type = EXCLUDED.block_type,
                        text = EXCLUDED.text,
                        text_hash = EXCLUDED.text_hash,
                        start_offset = EXCLUDED.start_offset,
                        end_offset = EXCLUDED.end_offset,
                        metadata = EXCLUDED.metadata
                    RETURNING block_id
                    """,
                    [
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
                    }
                    for b in blocks
                    ],
                    returning=True,
                )
            # one result set per block, in order: the stored id is kept (an existing row keeps its id)
            for b in blocks:
                row = cur.fetchone()
                if row:
                    b.block_id = row["block_id"] if isinstance(row, dict) else row[0]
                cur.nextset()
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
