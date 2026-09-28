"""Navigate a long document without loading all of it into the model's context.

The Assistant reads documents as paged text ("[Page N]" markers, see
``document_tools.paged_text``). For a 300-page document the whole text does not fit
alongside everything else in a turn, so reads are *addressable*:

  outline(text)                      → sections with ids, titles, page ranges and sizes
  window(text, section|pages|cursor) → one bounded slice, snapped to paragraph ends,
                                       with a cursor to continue

Section ids are deterministic for a given text ("s1", "s2", …), so the model can come back
to a section later in the turn, or in the next turn, and get the same slice. Headings are
detected with the canonical parser's patterns; a document without headings is split into
page groups instead so every part is still addressable.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache

from app.documents.canonical import _RE_HEADING, _RE_MD_SECTION, _RE_UNNUMBERED_HEADING

_PAGE_RE = re.compile(r"^\[Page (\d+)\]$", re.MULTILINE)
_TOP_CLAUSE = re.compile(r"^(\d{1,3})\.\s+([A-Z][^\n]{2,120})$")  # "12. Termination" (level-1 only)
_PAGES_ARG = re.compile(r"^\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*$")
PAGES_PER_GROUP = 5


@dataclass(frozen=True)
class Section:
    section_id: str
    title: str
    start: int
    end: int
    first_page: int | None
    last_page: int | None

    def pages(self) -> str:
        if self.first_page is None:
            return ""
        return str(self.first_page) if self.first_page == self.last_page else f"{self.first_page}–{self.last_page}"


def _page_starts(text: str) -> list[tuple[int, int]]:
    return [(m.start(), int(m.group(1))) for m in _PAGE_RE.finditer(text)]


def _page_at(starts: list[tuple[int, int]], offset: int) -> int | None:
    page = None
    for pos, num in starts:
        if pos > offset:
            break
        page = num
    return page


def _heading(line: str) -> str | None:
    line = line.strip()
    if not line or len(line) > 160:
        return None
    m = _RE_HEADING.match(line) or _RE_MD_SECTION.match(line)
    if m:
        kind = "Section" if line.startswith("#") else line.split()[0].title()
        return f"{kind} {m.group(1)}" + (f" — {m.group(2).strip()}" if m.group(2).strip() else "")
    m = _RE_UNNUMBERED_HEADING.match(line)
    if m:
        return m.group(1).strip()
    m = _TOP_CLAUSE.match(line)
    if m:
        return f"{m.group(1)}. {m.group(2).strip()}"
    return None


@lru_cache(maxsize=64)
def _outline_cached(digest: str, text: str) -> tuple[Section, ...]:
    starts = _page_starts(text)
    marks: list[tuple[int, str]] = []
    pos = 0
    prev: tuple[int, str] | None = None  # (offset, text) of the previous non-blank line
    for line in text.split("\n"):
        title = _heading(line)
        if title:
            # A heading right after its page marker starts at the marker, so the section
            # carries its own page number and the previous one does not end with it.
            at = prev[0] if prev and _PAGE_RE.fullmatch(prev[1]) else pos
            marks.append((at, title))
        if line.strip():
            prev = (pos, line.strip())
        pos += len(line) + 1
    if len(marks) < 2:
        # No usable headings: address the document by groups of pages.
        if starts:
            groups = [starts[i:i + PAGES_PER_GROUP] for i in range(0, len(starts), PAGES_PER_GROUP)]
            marks = [(g[0][0], f"Pages {g[0][1]}–{g[-1][1]}" if len(g) > 1 else f"Page {g[0][1]}") for g in groups]
        else:
            marks = [(0, "Document")]
    if marks[0][0] > 0 and _PAGE_RE.sub("", text[: marks[0][0]]).strip():
        marks.insert(0, (0, "Opening"))
    sections = []
    for i, (start, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        last = _page_at(starts, max(start, end - 1))
        sections.append(Section(f"s{i + 1}", title, start, end, _page_at(starts, start) or (starts[0][1] if starts else None), last))
    return tuple(sections)


def outline(text: str) -> tuple[Section, ...]:
    return _outline_cached(hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest(), text)


def page_count(text: str) -> int:
    starts = _page_starts(text)
    return starts[-1][1] if starts else 0


def _snap(text: str, start: int, end: int) -> int:
    """Move a cut back to a paragraph (or line) end so no sentence is split."""
    if end >= len(text):
        return len(text)
    for sep in ("\n\n", "\n"):
        cut = text.rfind(sep, start + (end - start) // 2, end)
        if cut > start:
            return cut
    return end


def page_range(text: str, pages: str) -> tuple[int, int] | None:
    m = _PAGES_ARG.match(pages or "")
    if not m:
        return None
    first, last = int(m.group(1)), int(m.group(2) or m.group(1))
    starts = _page_starts(text)
    begin = next((pos for pos, num in starts if num >= first), None)
    if begin is None:
        return None
    end = next((pos for pos, num in starts if num > last), len(text))
    return begin, end


@dataclass
class Window:
    text: str
    start: int
    end: int
    first_page: int | None
    last_page: int | None
    next_cursor: int | None      # absolute char offset to continue from, or None when done
    remaining_chars: int


def window(text: str, start: int, stop: int, budget: int) -> Window:
    """A slice of ``text[start:stop]`` of at most ``budget`` chars, ending on a paragraph."""
    start = max(0, min(start, len(text)))
    stop = max(start, min(stop, len(text)))
    end = stop if stop - start <= budget else _snap(text, start, start + budget)
    starts = _page_starts(text)
    return Window(
        text=text[start:end], start=start, end=end,
        first_page=_page_at(starts, start) or (starts[0][1] if starts else None),
        last_page=_page_at(starts, max(start, end - 1)),
        next_cursor=end if end < stop else None,
        remaining_chars=stop - end,
    )


def outline_rows(text: str, limit: int = 250) -> list[dict]:
    rows = [{"section_id": s.section_id, "title": s.title, "pages": s.pages(), "chars": s.end - s.start}
            for s in outline(text)]
    if len(rows) > limit:
        # Very fine-grained numbering: keep the outline readable, every part still reachable by pages.
        step = len(rows) / limit
        rows = [rows[int(i * step)] for i in range(limit)]
    return rows


def section(text: str, section_id: str) -> Section | None:
    return next((s for s in outline(text) if s.section_id == section_id), None)
