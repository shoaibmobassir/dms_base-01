"""Find a phrase inside one document version's blocks (the reader's "find in document")."""
from __future__ import annotations

from typing import Any

MIN_QUERY = 2
MAX_RESULTS = 50
_SNIPPET_RADIUS = 60


def search_blocks(blocks: list[dict[str, Any]], query: str, limit: int = MAX_RESULTS) -> dict[str, Any]:
    """Blocks whose text contains ``query`` (case-insensitive), in reading order, with a short snippet.

    ``index`` is the block's position in the version, which the reader turns into a page or part.
    """
    q = " ".join((query or "").split())
    if len(q) < MIN_QUERY:
        return {"query": q, "matches": [], "total": 0}
    needle = q.lower()
    matches: list[dict[str, Any]] = []
    total = 0
    for index, block in enumerate(blocks):
        # Line breaks and double spaces in extracted text must not hide a phrase.
        text = " ".join(str(block.get("text") or "").split())
        at = text.lower().find(needle)
        if at < 0:
            continue
        total += 1
        if len(matches) >= limit:
            continue
        start = max(0, at - _SNIPPET_RADIUS)
        end = min(len(text), at + len(q) + _SNIPPET_RADIUS)
        snippet = ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")
        matches.append({
            "block_id": block.get("block_id"),
            "index": index,
            "page_number": block.get("page_number"),
            "section_title": block.get("section_title"),
            "snippet": snippet,
        })
    return {"query": q, "matches": matches, "total": total}
