"""Structured extraction results: Page → text with offsets."""
from __future__ import annotations

from dataclasses import dataclass, field


PAGE_BREAK = "\f"  # form-feed between pages in joined text


@dataclass
class PageSpan:
    page_number: int
    start_offset: int
    end_offset: int
    text: str


@dataclass
class ExtractedDocument:
    text: str
    page_count: int
    pages: list[PageSpan] = field(default_factory=list)
    mime_type: str = "application/octet-stream"
    source_format: str = "text"  # pdf | docx | text

    def page_for_offset(self, offset: int) -> int:
        if not self.pages:
            return max(1, (offset // 3000) + 1)
        for p in self.pages:
            if p.start_offset <= offset < p.end_offset:
                return p.page_number
        return self.pages[-1].page_number if self.pages else 1


def join_pages(page_texts: list[str]) -> ExtractedDocument:
    """Join page texts with form-feeds and build PageSpan offsets."""
    pages: list[PageSpan] = []
    parts: list[str] = []
    cursor = 0
    for i, raw in enumerate(page_texts, start=1):
        text = (raw or "").strip()
        if i > 1:
            parts.append(PAGE_BREAK)
            cursor += len(PAGE_BREAK)
        start = cursor
        parts.append(text)
        end = start + len(text)
        pages.append(PageSpan(page_number=i, start_offset=start, end_offset=end, text=text))
        cursor = end
    full = "".join(parts)
    return ExtractedDocument(
        text=full,
        page_count=max(1, len(page_texts)),
        pages=pages,
    )
