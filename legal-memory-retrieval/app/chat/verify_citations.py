"""
Server-side citation quote verification: Locate quoted passages in original
document text using a 3-tier matcher (exact → whitespace+case normalized →
punctuation-tolerant). Auto-correct drifted quotes by swapping in the exact
source excerpt.

Clean-room independent implementation for FirmOS legal assistant chatbot.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PAGE_BREAK_SENTINEL = "[[PAGE_BREAK]]"
_ELLIPSIS_RE = re.compile(r"\.{3}|…")

# Source text that indicates the document could not be read
_UNREADABLE_SOURCES = frozenset({
    "Document could not be read.",
    "Document not found.",
})


# ---------------------------------------------------------------------------
# Quote location data
# ---------------------------------------------------------------------------

class QuoteLocation:
    __slots__ = ("start", "end", "excerpt")

    def __init__(self, start: int, end: int, excerpt: str):
        self.start = start
        self.end = end
        self.excerpt = excerpt


class QuoteVerification:
    __slots__ = ("verified", "source_excerpt", "start_char", "end_char")

    def __init__(
        self,
        verified: bool,
        source_excerpt: str | None = None,
        start_char: int | None = None,
        end_char: int | None = None,
    ):
        self.verified = verified
        self.source_excerpt = source_excerpt
        self.start_char = start_char
        self.end_char = end_char

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"verified": self.verified}
        if self.source_excerpt is not None:
            d["source_excerpt"] = self.source_excerpt
        if self.start_char is not None:
            d["start_char"] = self.start_char
        if self.end_char is not None:
            d["end_char"] = self.end_char
        return d


# ---------------------------------------------------------------------------
# Text normalisation helpers
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[\u2018\u2019\u201c\u201d\u2013\u2014\u2026.,;:!?'\"\-\(\)\[\]{}]")


def _normalise_text(text: str, *, strip_punctuation: bool = False) -> tuple[str, list[int]]:
    """
    Normalise text for fuzzy matching, returning both the normalised string
    and an index map from normalised positions back to original positions.

    - Lowercases
    - Collapses whitespace
    - Optionally strips punctuation
    """
    result_chars: list[str] = []
    orig_indices: list[int] = []
    prev_ws = False

    # Normalise one source character at a time: NFKD and lowercasing can turn one
    # character into several, and every output character must map back to its source.
    for i, raw in enumerate(text):
        piece = raw.lower()
        if strip_punctuation:
            piece = _PUNCT_RE.sub(" ", unicodedata.normalize("NFKD", piece))
        for ch in piece:
            if ch in " \t\n\r\f\v":
                if not prev_ws and result_chars:
                    result_chars.append(" ")
                    orig_indices.append(i)
                    prev_ws = True
            else:
                result_chars.append(ch)
                orig_indices.append(i)
                prev_ws = False

    return "".join(result_chars), orig_indices


# ---------------------------------------------------------------------------
# Quote location (3-tier)
# ---------------------------------------------------------------------------

def locate_quote(source: str, quote: str) -> QuoteLocation | None:
    """
    Locate `quote` inside `source`, returning the exact original substring
    (`excerpt`) plus its char offsets into `source`. Tries progressively more
    tolerant matchers and returns the first hit:
      1. exact substring
      2. whitespace + case normalised
      3. whitespace + case + punctuation normalised (tolerant/fuzzy)
    """
    if not source or not quote:
        return None

    # Tier 1: exact substring
    idx = source.find(quote)
    if idx >= 0:
        return QuoteLocation(start=idx, end=idx + len(quote), excerpt=quote)

    # Tier 2: whitespace + case normalised
    loc = _locate_normalised(source, quote, strip_punctuation=False)
    if loc:
        return loc

    # Tier 3: also punctuation-tolerant
    return _locate_normalised(source, quote, strip_punctuation=True)


def _locate_normalised(
    source: str,
    quote: str,
    *,
    strip_punctuation: bool,
) -> QuoteLocation | None:
    """Find a normalised needle in a normalised haystack, mapping back to original offsets."""
    norm_source, orig_idx = _normalise_text(source, strip_punctuation=strip_punctuation)
    norm_quote, _ = _normalise_text(quote, strip_punctuation=strip_punctuation)
    needle = norm_quote.strip()
    if not needle:
        return None

    pos = norm_source.find(needle)
    if pos < 0:
        return None

    end_norm_pos = pos + len(needle)
    start = orig_idx[pos] if pos < len(orig_idx) else 0
    end = (orig_idx[end_norm_pos - 1] + 1) if end_norm_pos - 1 < len(orig_idx) else len(source)
    return QuoteLocation(start=start, end=end, excerpt=source[start:end])


# ---------------------------------------------------------------------------
# Single quote verification
# ---------------------------------------------------------------------------

def verify_quote(source: str, quote: str) -> tuple[QuoteVerification, bool]:
    """
    Verify a single model quote against the source text.
    Returns (verification, needs_correction) tuple.

    Handles:
    - Cross-page quotes split by [[PAGE_BREAK]]
    - Ellipsis-abbreviated quotes split by ... or …
    - Simple contiguous quotes
    """
    if not source or source in _UNREADABLE_SOURCES:
        return QuoteVerification(verified=False), False

    # Cross-page quotes
    if PAGE_BREAK_SENTINEL in quote:
        segments = [s.strip() for s in quote.split(PAGE_BREAK_SENTINEL) if s.strip()]
        if not segments:
            return QuoteVerification(verified=False), False
        results = [verify_quote(source, seg) for seg in segments]
        if any(not v.verified for v, _ in results):
            return QuoteVerification(verified=False), False
        needs_correction = any(nc for _, nc in results)
        combined_excerpt = f" {PAGE_BREAK_SENTINEL} ".join(
            v.source_excerpt or seg for (v, _), seg in zip(results, segments)
        )
        return (
            QuoteVerification(verified=True, source_excerpt=combined_excerpt),
            needs_correction,
        )

    # Ellipsis-abbreviated quotes
    if _ELLIPSIS_RE.search(quote):
        segments = [s.strip() for s in _ELLIPSIS_RE.split(quote)]
        # Keep only segments with actual letters/numbers
        segments = [s for s in segments if re.search(r"[\w]", s)]
        if not segments:
            return QuoteVerification(verified=False), False
        located = [(seg, locate_quote(source, seg)) for seg in segments]
        if any(loc is None for _, loc in located):
            return QuoteVerification(verified=False), False
        needs_correction = any(
            loc.excerpt != seg for seg, loc in located if loc is not None
        )
        combined_excerpt = " ... ".join(
            loc.excerpt for _, loc in located if loc is not None
        )
        return (
            QuoteVerification(verified=True, source_excerpt=combined_excerpt),
            needs_correction,
        )

    # Simple contiguous quote
    loc = locate_quote(source, quote)
    if not loc:
        return QuoteVerification(verified=False), False

    needs_correction = loc.excerpt != quote
    return (
        QuoteVerification(
            verified=True,
            source_excerpt=loc.excerpt,
            start_char=loc.start,
            end_char=loc.end,
        ),
        needs_correction,
    )


# ---------------------------------------------------------------------------
# Batch verification
# ---------------------------------------------------------------------------

def verify_document_citation(
    citation_dict: dict[str, Any],
    source_text: str,
) -> dict[str, Any]:
    """
    Verify all quotes in a document citation against the source text.
    Returns the citation dict enriched with per-quote verification data
    and a top-level `verified` flag. Drifted quotes are auto-corrected
    by swapping in the exact source excerpt.
    """
    quotes = citation_dict.get("quotes", [])
    if not quotes:
        raw_quote = citation_dict.get("quote")
        if isinstance(raw_quote, str) and raw_quote.strip():
            quotes = [{"page": citation_dict.get("page", 1), "quote": raw_quote}]
        else:
            return {**citation_dict, "verified": False}

    verified_quotes: list[dict[str, Any]] = []
    for q in quotes:
        quote_text = q.get("quote", "")
        verification, needs_correction = verify_quote(source_text, quote_text)
        corrected_quote = (
            verification.source_excerpt
            if needs_correction and verification.source_excerpt
            else quote_text
        )
        verified_quotes.append({
            **q,
            "quote": corrected_quote,
            "verification": verification.to_dict(),
        })

    all_verified = all(q["verification"]["verified"] for q in verified_quotes)
    return {
        **citation_dict,
        "quotes": verified_quotes,
        "quote": verified_quotes[0]["quote"] if verified_quotes else citation_dict.get("quote"),
        "verified": all_verified,
    }
