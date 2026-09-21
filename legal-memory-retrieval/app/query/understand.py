from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from app.retrieval.route import MATTER_CODE_RE, MATTER_ID_RE

DOC_ID_RE = re.compile(r"\bDOC-\d+\b", re.I)
MEMBER_ID_RE = re.compile(r"\bMEM-\d+\b", re.I)

# Longest prefixes first so we peel the query down to the entity / topic.
_STRIP_PREFIXES = (
    r"what is the matter code for\s+",
    r"what have we previously done for\s+",
    r"what matters involve\s+",
    r"what matters involving\s+",
    r"matters involving\s+",
    r"which documents support our argument on\s+",
    r"find the document titled\s+",
    r"which lawyers have experience in\s+",
    r"which lawyers worked on matters involving\s+",
    r"what happened in\s+",
    r"what was our position regarding\s+",
    r"have we previously advised on\s+",
    r"have we previously negotiated\s+",
    r"have we previously handled\s+",
    r"have we previously done\s+",
    r"have we negotiated\s+",
    r"have we enforced\s+",
    r"have we acted on\s+",
    r"have we advised on\s+",
    r"have we handled\s+",
    r"have we dealt with\s+",
    r"have we done\s+",
)

STRIP_PREFIX_RE = re.compile(rf"^({'|'.join(_STRIP_PREFIXES)})", re.I)

# Metric label only. Detects a document/record/support ask without a new planner intent.
# Official prefixes stay first so document_title is not stolen.
_DOCUMENT_SEEKING_RE = re.compile(
    r"\b("
    r"papers?\b|"
    r"filings?\b|"
    r"supporting documents?\b|"
    r"documents? that\b|"
    r"docs that\b|"
    r"record of\b|"
    r"support(?:s|ing)? (?:our |the )?(?:argument|position)\b|"
    r"back our position\b"
    r")",
    re.I,
)

PRACTICE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Arbitration", re.compile(r"\barbitration\b|\barb\b", re.I)),
    ("M&A", re.compile(r"\bm\s*&\s*a\b|\bmergers?\b|\bacquisitions?\b|\bspa\b", re.I)),
    ("Insolvency", re.compile(r"\binsolvency\b|\bibc\b|\bcirp\b|\bliquidation\b", re.I)),
    ("Tax", re.compile(r"\btax\b|\bgst\b|\btransfer pricing\b", re.I)),
    ("Employment", re.compile(r"\bemployment\b|\blabou?r\b|\bposh\b|\bnon-competes?\b", re.I)),
    ("Real Estate", re.compile(r"\breal estate\b|\btitle diligence\b", re.I)),
    ("Regulatory", re.compile(r"\bregulatory\b|\bsebi\b|\binsider trading\b", re.I)),
    ("Disputes", re.compile(r"\bdisputes?\b|\blitigation\b|\boppression\b", re.I)),
    ("Banking & Finance", re.compile(r"\bbanking\b|\bshare pledges?\b|\bloan agreement\b", re.I)),
)

Intent = str


@dataclass
class ParsedQuery:
    raw: str
    intent: Intent
    search_text: str
    matter_ids: list[str] = field(default_factory=list)
    matter_codes: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    member_ids: list[str] = field(default_factory=list)
    practice_area: str | None = None
    relationship_types: list[str] = field(default_factory=list)
    skip_vector: bool = False
    skip_rerank: bool = False
    dedupe_matters: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def query_class(parsed: ParsedQuery) -> str:
    """Metric label only. Does not change intent or fusion weights."""
    q = parsed.raw.lower()
    if q.startswith("find the document titled"):
        return "document_title"
    if q.startswith("which documents support our argument on"):
        return "argument_support"
    if _DOCUMENT_SEEKING_RE.search(parsed.raw):
        return "argument_support"
    return "other"


def _clean(text: str) -> str:
    text = text.strip()
    text = STRIP_PREFIX_RE.sub("", text)
    text = text.strip(" ?.,;:")
    return re.sub(r"\s+", " ", text)


def _relationship_types(raw: str) -> list[str]:
    """Map a named relation in the question onto stored edge types.

    Unrecognised relationship language (same lead, different client) stays
    empty so the graph walk keeps its existing untyped behaviour.
    """
    q = raw.lower()
    found: list[str] = []
    if "same client" in q:
        found.append("same_client")
    if "similar facts" in q:
        found.append("similar_facts")
    if "precedent" in q:
        found.append("precedent_for")
    if "follow-up" in q or "follow up" in q:
        found.append("follow_up_to")
    if "same practice" in q:
        found.append("same_practice_area")
    return found


def _intent(raw: str) -> Intent:
    q = raw.lower()
    if not q.strip():
        return "empty"
    # Relationship questions name a seed matter but the answer is a neighbour.
    # Must run before the bare MTR-/DOC- exact-lookup rule.
    if (
        ("related to" in q and (MATTER_ID_RE.search(raw) or "client" in q or "lead" in q))
        or "precedent for" in q
        or "follow-up to" in q
        or "follow up to" in q
        or "similar facts" in q
    ):
        return "graph_reasoning"
    if "position" in q and (MATTER_CODE_RE.search(raw) or MATTER_ID_RE.search(raw)):
        return "cross_document"
    if MATTER_ID_RE.search(raw) or DOC_ID_RE.search(raw):
        return "exact_lookup"
    if "matter code" in q:
        return "exact_lookup"
    if "which lawyers" in q or "who has experience" in q or "who worked" in q:
        return "experience_search"
    if "previously done for" in q or "work for" in q:
        return "matter_research"
    if "similar" in q or "previously handled" in q or "have we acted" in q:
        return "similar_matter"
    if q.startswith("have we ") or "have we ever" in q:
        return "semantic"
    return "matter_research"


def understand(query: str | None) -> ParsedQuery:
    raw = (query or "").strip()
    intent = _intent(raw)
    search_text = _clean(raw) if raw else ""
    if not search_text:
        search_text = raw
    matter_ids = [m.upper() for m in MATTER_ID_RE.findall(raw)]
    matter_codes = [c.upper() for c in MATTER_CODE_RE.findall(raw)]
    document_ids = [d.upper() for d in DOC_ID_RE.findall(raw)]
    member_ids = [m.upper() for m in MEMBER_ID_RE.findall(raw)]
    relationship_types = _relationship_types(raw)
    practice_area = None
    for name, pattern in PRACTICE_PATTERNS:
        if pattern.search(raw):
            practice_area = name
            break
    skip_vector = (
        "matter code" in raw.lower()
        or bool(matter_ids)
        or bool(document_ids)
        or (bool(matter_codes) and len(raw.split()) <= 10)
    )
    skip_rerank = bool(matter_ids) and intent != "cross_document"
    if intent == "cross_document":
        skip_vector = False
    dedupe_matters = intent == "experience_search"
    if intent == "experience_search" and practice_area:
        search_text = practice_area
    return ParsedQuery(
        raw=raw,
        intent=intent,
        search_text=search_text,
        matter_ids=matter_ids,
        matter_codes=matter_codes,
        document_ids=document_ids,
        member_ids=member_ids,
        practice_area=practice_area,
        relationship_types=relationship_types,
        skip_vector=skip_vector,
        skip_rerank=skip_rerank,
        dedupe_matters=dedupe_matters,
    )
