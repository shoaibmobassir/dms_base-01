"""Citation recognition across legal systems.

Finds citations in free text (an answer, a draft, a pleading) and gives each a
normalized key, so the same authority cited three different ways resolves to one
thing. Covers the systems this firm works in: international law (PCIJ, ICJ, UN
Security Council, UNTS), India (reported judgments, case numbers, statutes) and
US reporters (delegated to the patterns in ``app.caselaw.citation_parser``).

A key says *what* is cited; whether it exists is the provider's job (resolve).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.caselaw.citation_parser import CitationParser


@dataclass(frozen=True)
class Citation:
    raw: str
    key: str
    system: str  # international | india | us
    kind: str  # case | advisory_or_case | resolution | treaty | statute | case_number
    start: int
    end: int
    pinpoint: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)


def _series(raw: str) -> str:
    s = re.sub(r"\s+", "", raw.upper())
    return "A/B" if s in ("A/B", "AB") else s


# Pinpoint tail: ", p. 25" / ", at p. 25" / ", para. 3" / ", paras. 3-4" / ", operative paragraph 2"
_PIN = r"(?P<pin>,?\s*(?:at\s+)?(?:(?:pp?\.|page)\s*(?P<page>\d+)|(?:paras?\.|paragraphs?|op(?:erative)?\.?\s*para(?:graph)?\.?)\s*(?P<para>\d+)))?"

_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("international", "pcij", re.compile(
        r"\bP\.?\s?C\.?\s?I\.?\s?J\.?\s*,?\s*(?:Series|Ser\.)\s*(?P<series>A\s*/\s*B|AB|A|B|C|D|E)\s*,?\s*No\.?\s*(?P<num>\d{1,3})" + _PIN)),
    ("international", "pcij", re.compile(
        r"\bSeries\s+(?P<series>A\s*/\s*B|AB|A|B)\s*,?\s*No\.?\s*(?P<num>\d{1,3})" + _PIN)),
    ("international", "icj", re.compile(
        r"\bI\.?\s?C\.?\s?J\.?\s*(?:Reports|Rep\.?)\s*,?\s*(?P<year>(?:19|20)\d{2})\s*,?\s*(?:p\.?\s*)?(?P<page0>\d{1,4})" + _PIN)),
    ("international", "unsc", re.compile(
        r"\bS/RES/(?P<num>\d{1,4})\s*\(\s*(?P<year>(?:19|20)\d{2})\s*\)" + _PIN)),
    ("international", "unsc", re.compile(
        r"\b(?:Security\s+Council\s+)?[Rr]esolutions?\s+(?P<num>\d{1,4})\s*\(\s*(?P<year>(?:19|20)\d{2})\s*\)" + _PIN)),
    ("international", "unsc", re.compile(
        r"\b(?:UNSC|SC|S\.C\.)\s*Res(?:olution)?\.?\s*(?:No\.?\s*)?(?P<num>\d{1,4})(?:\s*\(\s*(?P<year>(?:19|20)\d{2})\s*\))?" + _PIN)),
    ("international", "unsc", re.compile(r"\bUNSCR\s*(?P<num>\d{1,4})" + _PIN)),
    ("international", "unts", re.compile(
        r"\b(?P<vol>\d{1,4})\s*U\.?\s?N\.?\s?T\.?\s?S\.?\s*,?\s*(?:p\.\s*)?(?P<page0>\d{1,5})")),
    ("international", "unts", re.compile(
        r"\bUNTS\s*,?\s*vol\.?\s*(?P<vol>\d{1,4})\s*,?\s*p\.?\s*(?P<page0>\d{1,5})")),
    ("india", "scc", re.compile(
        r"\((?P<year>(?:19|20)\d{2})\)\s*(?P<vol>\d{1,2})\s*SCC\s*(?P<page0>\d{1,5})" + _PIN)),
    ("india", "scconline", re.compile(
        r"\b(?P<year>(?:19|20)\d{2})\s*SCC\s*OnLine\s*(?P<court>[A-Z][A-Za-z]{1,8})\s*(?P<page0>\d{1,6})")),
    ("india", "air", re.compile(
        r"\bAIR\s*(?P<year>(?:19|20)\d{2})\s*(?P<court>SC|[A-Z][A-Za-z]{1,8})\s*(?P<page0>\d{1,5})")),
    ("india", "civil-appeal", re.compile(
        r"\bCivil\s+Appeal\s+Nos?\.?\s*(?P<num>\d{1,6})\s+of\s+(?P<year>(?:19|20)\d{2})", re.I)),
    ("india", "petition", re.compile(
        r"\bPetition\s+(?:No\.?\s*)?(?P<num>\d{1,5}\s*/\s*[A-Z]{1,4}\s*/\s*(?:19|20)\d{2})", re.I)),
    ("india", "ia", re.compile(
        r"\bI\.\s?A\.?\s*(?:No\.?\s*)?(?P<num>\d{1,6})\s+of\s+(?P<year>(?:19|20)\d{2})", re.I)),
    ("india", "appeal", re.compile(
        r"\b(?:Appeal|APL\.?)\s+(?:No\.?\s*)?(?P<num>\d{1,5})\s+of\s+(?P<year>(?:19|20)\d{2})", re.I)),
    ("india", "petition", re.compile(
        r"\bPetition\s+(?:No\.?\s*)?(?P<num>\d{1,5})\s+of\s+(?P<year>(?:19|20)\d{2})", re.I)),
    ("india", "act", re.compile(
        r"\b(?:Section|Sec\.|[Ss]\.|[Ss]s\.)\s*(?P<sec>\d{1,4}[A-Z]?)(?P<sub>(?:\s*\(\w{1,4}\))*)\s*(?:of\s+the\s+|,\s*(?:the\s+)?)"
        r"(?P<act>[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,5}\s+Act),?\s*(?P<year>(?:18|19|20)\d{2})")),
]

_GA_BEFORE = re.compile(r"General\s+Assembly\s*$", re.I)
_US = CitationParser()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _key(kind: str, g: dict[str, Any]) -> str:
    if kind == "pcij":
        return f"pcij:{_series(g['series'])}:{int(g['num'])}"
    if kind == "icj":
        return f"icj:{g['year']}:{int(g['page0'])}"
    if kind == "unsc":
        return f"unsc:{int(g['num'])}"
    if kind == "unts":
        return f"unts:{int(g['vol'])}:{int(g['page0'])}"
    if kind == "scc":
        return f"in:scc:{g['year']}:{int(g['vol'])}:{int(g['page0'])}"
    if kind in ("scconline", "air"):
        return f"in:{kind}:{g['year']}:{g['court'].lower()}:{int(g['page0'])}"
    if kind == "act":
        sub = re.sub(r"\s+", "", g.get("sub") or "")
        return f"in:act:{_slug(g['act'])}-{g['year']}:s{g['sec'].lower()}{sub}"
    if kind == "petition" and "/" in str(g["num"]):
        return "in:petition:" + re.sub(r"\s+", "", g["num"]).upper()
    return f"in:{kind}:{int(g['num'])}:{g['year']}"


_KIND = {
    "pcij": "case", "icj": "case", "unsc": "resolution", "unts": "treaty", "scc": "case", "scconline": "case",
    "air": "case", "act": "statute", "civil-appeal": "case_number", "petition": "case_number", "ia": "case_number",
    "appeal": "case_number",
}


def extract_citations(text: str) -> list[Citation]:
    """All citations in ``text``, in reading order, longest match winning on overlap."""
    text = text or ""
    found: list[Citation] = []
    for system, kind, rx in _PATTERNS:
        for m in rx.finditer(text):
            if kind == "unsc" and _GA_BEFORE.search(text[max(0, m.start() - 40):m.start()]):
                continue  # a General Assembly resolution, not the Council's
            g = m.groupdict()
            pin = {k: int(g[k]) for k in ("page", "para") if g.get(k)}
            raw = m.group(0).rstrip(" ,")
            found.append(Citation(raw=raw, key=_key(kind, g), system=system, kind=_KIND[kind],
                                  start=m.start(), end=m.start() + len(raw), pinpoint=pin))
    for rx, kind in ((_US.CASE_RE, "case"), (_US.STATUTE_RE, "statute")):
        for m in rx.finditer(text):
            raw = m.group(0).strip()
            key = "us:" + re.sub(r"\s+", " ", raw).lower()
            found.append(Citation(raw=raw, key=key, system="us", kind=kind, start=m.start(), end=m.start() + len(raw)))
    found.sort(key=lambda c: (c.start, -(c.end - c.start)))
    out: list[Citation] = []
    for c in found:
        if out and c.start < out[-1].end:
            continue
        out.append(c)
    return out


def parse_citation(text: str) -> Citation | None:
    """The first citation in ``text`` (for a single citation string)."""
    cites = extract_citations(text)
    return cites[0] if cites else None
