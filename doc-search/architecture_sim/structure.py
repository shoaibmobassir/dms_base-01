"""Parse raw text into hierarchical sections + blocks (canonical structure)."""
from __future__ import annotations

import re
import uuid

from architecture_sim.hashing import sha256_text
from architecture_sim.models import BlockType, DocumentBlock

SECTION_RE = re.compile(r"^##\s+Section\s+([\d.]+)\.\s+(.+)$", re.MULTILINE)


def parse_structure(version_id: str, raw_text: str, page_chars: int = 2500) -> list[DocumentBlock]:
    """
    Split document into section-aware blocks.

    Pages are derived from character offsets (simulating PDF page breaks).
    """
    blocks: list[DocumentBlock] = []
    matches = list(SECTION_RE.finditer(raw_text))
    if not matches:
        # Single blob
        page = 1
        bid = f"BLK-{uuid.uuid4().hex[:10].upper()}"
        blocks.append(
            DocumentBlock(
                block_id=bid,
                version_id=version_id,
                page_number=page,
                section_id="0",
                block_type=BlockType.PARAGRAPH,
                sequence=0,
                text=raw_text.strip(),
                text_hash=sha256_text(raw_text.strip()),
                start_offset=0,
                end_offset=len(raw_text.strip()),
            )
        )
        return blocks

    # Preamble before first section
    seq = 0
    preamble = raw_text[: matches[0].start()].strip()
    if preamble:
        page = 1 + (0 // page_chars)
        bid = f"BLK-{uuid.uuid4().hex[:10].upper()}"
        blocks.append(
            DocumentBlock(
                block_id=bid,
                version_id=version_id,
                page_number=page,
                section_id="preamble",
                block_type=BlockType.PARAGRAPH,
                sequence=seq,
                text=preamble,
                text_hash=sha256_text(preamble),
                start_offset=0,
                end_offset=len(preamble),
            )
        )
        seq += 1

    for i, m in enumerate(matches):
        sec_id = m.group(1)
        title = m.group(2).strip()
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_text)
        section_text = raw_text[start:end].strip()

        # Heading block
        heading = f"Section {sec_id}. {title}"
        page = 1 + (start // page_chars)
        h_bid = f"BLK-{uuid.uuid4().hex[:10].upper()}"
        blocks.append(
            DocumentBlock(
                block_id=h_bid,
                version_id=version_id,
                page_number=page,
                section_id=sec_id,
                block_type=BlockType.HEADING,
                sequence=seq,
                text=heading,
                text_hash=sha256_text(heading),
                start_offset=0,
                end_offset=len(heading),
            )
        )
        seq += 1

        # Paragraph blocks — split on blank lines
        body = section_text.split("\n", 1)[-1] if "\n" in section_text else ""
        paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        offset_cursor = 0
        for para in paras:
            p_bid = f"BLK-{uuid.uuid4().hex[:10].upper()}"
            abs_start = raw_text.find(para, start, end)
            page = 1 + (max(abs_start, start) // page_chars)
            blocks.append(
                DocumentBlock(
                    block_id=p_bid,
                    version_id=version_id,
                    page_number=page,
                    section_id=sec_id,
                    block_type=BlockType.PARAGRAPH,
                    sequence=seq,
                    text=para,
                    text_hash=sha256_text(para),
                    start_offset=0,
                    end_offset=len(para),
                )
            )
            seq += 1
            offset_cursor += len(para)
    return blocks


def hierarchical_chunks(
    document_id: str,
    matter_id: str,
    folder_path: str,
    version_id: str,
    blocks: list[DocumentBlock],
    max_chars: int = 1200,
) -> list[dict]:
    """
    Build parent (section) + child (paragraph-group) chunks.
    Returns dicts ready to become Chunk models with embeddings filled later.
    """
    from collections import defaultdict

    by_section: dict[str, list[DocumentBlock]] = defaultdict(list)
    for b in blocks:
        if b.block_type == BlockType.HEADING:
            continue
        by_section[b.section_id].append(b)

    out: list[dict] = []
    position = 0
    for sec_id, sec_blocks in by_section.items():
        heading = next(
            (b for b in blocks if b.section_id == sec_id and b.block_type == BlockType.HEADING),
            None,
        )
        section_title = heading.text if heading else f"Section {sec_id}"
        full = "\n\n".join(b.text for b in sec_blocks)
        parent_id = f"CHK-{uuid.uuid4().hex[:10].upper()}"
        page = sec_blocks[0].page_number if sec_blocks else 1
        out.append(
            {
                "chunk_id": parent_id,
                "version_id": version_id,
                "document_id": document_id,
                "matter_id": matter_id,
                "folder_path": folder_path,
                "page": page,
                "section_id": sec_id,
                "section_title": section_title,
                "block_ids": [b.block_id for b in sec_blocks],
                "text": full[:8000],
                "parent_chunk_id": None,
                "position": position,
                "is_parent": True,
            }
        )
        position += 1

        # Child chunks
        buf: list[DocumentBlock] = []
        buf_len = 0
        for b in sec_blocks:
            if buf_len + len(b.text) > max_chars and buf:
                child_id = f"CHK-{uuid.uuid4().hex[:10].upper()}"
                text = "\n\n".join(x.text for x in buf)
                out.append(
                    {
                        "chunk_id": child_id,
                        "version_id": version_id,
                        "document_id": document_id,
                        "matter_id": matter_id,
                        "folder_path": folder_path,
                        "page": buf[0].page_number,
                        "section_id": sec_id,
                        "section_title": section_title,
                        "block_ids": [x.block_id for x in buf],
                        "text": text,
                        "parent_chunk_id": parent_id,
                        "position": position,
                        "is_parent": False,
                    }
                )
                position += 1
                buf = []
                buf_len = 0
            buf.append(b)
            buf_len += len(b.text)
        if buf:
            child_id = f"CHK-{uuid.uuid4().hex[:10].upper()}"
            text = "\n\n".join(x.text for x in buf)
            out.append(
                {
                    "chunk_id": child_id,
                    "version_id": version_id,
                    "document_id": document_id,
                    "matter_id": matter_id,
                    "folder_path": folder_path,
                    "page": buf[0].page_number,
                    "section_id": sec_id,
                    "section_title": section_title,
                    "block_ids": [x.block_id for x in buf],
                    "text": text,
                    "parent_chunk_id": parent_id,
                    "position": position,
                    "is_parent": False,
                }
            )
            position += 1
    return out
