"""
Citation extraction: Parse <CITATIONS> blocks from LLM output, normalise
citation objects, and support incremental partial parsing during streaming.
Clean-room independent implementation for FirmOS legal assistant chatbot.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Citation block constants
# ---------------------------------------------------------------------------

CITATIONS_BLOCK_RE = re.compile(
    r"<CITATIONS>\s*([\s\S]*?)\s*</CITATIONS>"
)
CITATIONS_OPEN_TAG = "<CITATIONS>"
CITATIONS_CLOSE_TAG = "</CITATIONS>"


# ---------------------------------------------------------------------------
# Parsed citation types
# ---------------------------------------------------------------------------

class DocumentQuote:
    __slots__ = ("page", "quote", "sheet", "cell")

    def __init__(
        self,
        page: int | str = 1,
        quote: str = "",
        sheet: str | None = None,
        cell: str | None = None,
    ):
        self.page = page
        self.quote = quote
        self.sheet = sheet
        self.cell = cell

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"page": self.page, "quote": self.quote}
        if self.sheet:
            d["sheet"] = self.sheet
        if self.cell:
            d["cell"] = self.cell
        return d


class DocumentCitation:
    __slots__ = ("ref", "doc_id", "page", "quote", "quotes", "sheet", "cell")

    def __init__(
        self,
        ref: int,
        doc_id: str,
        quotes: list[DocumentQuote],
    ):
        self.ref = ref
        self.doc_id = doc_id
        self.quotes = quotes
        # Legacy compat: first quote fields
        first = quotes[0] if quotes else DocumentQuote()
        self.page = first.page
        self.quote = first.quote
        self.sheet = first.sheet
        self.cell = first.cell

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": "document",
            "ref": self.ref,
            "doc_id": self.doc_id,
            "page": self.page,
            "quote": self.quote,
            "quotes": [q.to_dict() for q in self.quotes],
        }
        if self.sheet:
            d["sheet"] = self.sheet
        if self.cell:
            d["cell"] = self.cell
        return d


ParsedCitation = DocumentCitation  # Extensible for case law citations later


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalise_page(value: Any) -> int | str:
    """Normalise a page value: integer, 'N-M' range string, or default 1."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.match(r"^\d+\s*-\s*\d+$", value):
        return value
    try:
        n = int(str(value or ""))
        return n if n > 0 else 1
    except (ValueError, TypeError):
        return 1


def _normalise_cell_locator(c: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(c.get("sheet"), str) and c["sheet"].strip():
        out["sheet"] = c["sheet"].strip()
    if isinstance(c.get("cell"), str) and c["cell"].strip():
        out["cell"] = c["cell"].strip()
    return out


def _normalise_document_quotes(c: dict) -> list[DocumentQuote]:
    """Extract and normalise the quotes array from a raw citation dict."""
    if not isinstance(c.get("quotes"), list):
        return []
    result: list[DocumentQuote] = []
    for raw in c["quotes"][:3]:
        if not isinstance(raw, dict):
            continue
        text = raw.get("quote") or raw.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        cell_info = _normalise_cell_locator({
            "sheet": raw.get("sheet", c.get("sheet")),
            "cell": raw.get("cell", c.get("cell")),
        })
        result.append(DocumentQuote(
            page=_normalise_page(raw.get("page", c.get("page"))),
            quote=text,
            sheet=cell_info.get("sheet"),
            cell=cell_info.get("cell"),
        ))
    return result


def _normalise_citation(raw: Any) -> ParsedCitation | None:
    """Parse one raw citation dict into a typed citation object."""
    if not isinstance(raw, dict):
        return None
    c = raw
    # Resolve ref
    ref = c.get("ref")
    if not isinstance(ref, int):
        # Try marker string "[N]"
        marker = c.get("marker")
        if isinstance(marker, str):
            m = re.match(r"^\[(\d+)\]$", marker)
            if m:
                ref = int(m.group(1))
        if not isinstance(ref, int):
            return None

    # Must have doc_id for document citations
    doc_id = c.get("doc_id")
    if not isinstance(doc_id, str):
        return None

    # Build quotes
    quotes = _normalise_document_quotes(c)
    if not quotes:
        # Fallback to top-level quote/text
        text = c.get("quote") or c.get("text")
        if not isinstance(text, str) or not text.strip():
            return None
        cell_info = _normalise_cell_locator(c)
        quotes = [DocumentQuote(
            page=_normalise_page(c.get("page")),
            quote=text,
            sheet=cell_info.get("sheet"),
            cell=cell_info.get("cell"),
        )]

    return DocumentCitation(ref=ref, doc_id=doc_id, quotes=quotes)


# ---------------------------------------------------------------------------
# Main parsers
# ---------------------------------------------------------------------------

def parse_citations(text: str) -> list[ParsedCitation]:
    """
    Parse the <CITATIONS> block from full LLM output text.
    Returns a list of normalised citation objects.
    """
    match = CITATIONS_BLOCK_RE.search(text)
    if not match:
        return []
    raw_json = match.group(1)
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [c for raw in parsed if (c := _normalise_citation(raw)) is not None]


def extract_citations_text(text: str) -> str:
    """Strip the <CITATIONS> block from the response text, returning clean prose."""
    return CITATIONS_BLOCK_RE.sub("", text).rstrip()


def parse_partial_citations(text: str) -> list[ParsedCitation]:
    """
    Parse citation objects incrementally from a partially-streamed
    <CITATIONS> block. Used during SSE streaming so the UI can render
    citation pills before the full block is closed.
    """
    before_close = text.split(CITATIONS_CLOSE_TAG)[0]
    array_start = before_close.find("[")
    if array_start < 0:
        return []

    parsed: list[ParsedCitation] = []
    in_string = False
    escaped = False
    depth = 0
    object_start = -1

    for i in range(array_start + 1, len(before_close)):
        ch = before_close[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = in_string
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                object_start = i
            depth += 1
        elif ch == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and object_start >= 0:
                try:
                    raw = json.loads(before_close[object_start : i + 1])
                    cit = _normalise_citation(raw)
                    if cit:
                        parsed.append(cit)
                except json.JSONDecodeError:
                    pass
                object_start = -1
        elif ch == "]" and depth == 0:
            break
    return parsed
