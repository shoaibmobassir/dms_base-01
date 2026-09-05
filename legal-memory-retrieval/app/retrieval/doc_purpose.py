"""P5.6-C5.5-D6 — Document purpose / functional profile (no LLM).

Purpose answers: what is this artifact *doing*, beyond theme + role family.

Taxonomy (evaluation first; production soft prior later):
  ESTABLISH  — forms client/service relationship
  PROPOSE    — proposes transaction / commercial terms
  ASSESS     — assesses matter / person / transaction
  ANALYZE    — research / opinion / strategy analysis
  PLEAD      — asserts claims / defences
  RECORD     — records hearing / evidence / events
  AMEND      — amends an existing instrument
  NOTIFY     — notice / correspondence of position
  OTHER
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from app.retrieval.doc_profile import (
    infer_document_role,
    infer_role_family,
)

PURPOSES = (
    "ESTABLISH",
    "PROPOSE",
    "ASSESS",
    "ANALYZE",
    "PLEAD",
    "RECORD",
    "AMEND",
    "NOTIFY",
    "OTHER",
)

# Primary type → purpose (deterministic seed; headers refine).
_TYPE_TO_PURPOSE: dict[str, str] = {
    "Engagement Letter": "ESTABLISH",
    "Initial Case Assessment": "ASSESS",
    "Term Sheet": "PROPOSE",
    "Share Purchase Agreement": "PROPOSE",
    "Research Memo": "ANALYZE",
    "Legal Opinion": "ANALYZE",
    "Matter Strategy Note": "ANALYZE",
    "KM Note": "ANALYZE",
    "Partner Note": "ANALYZE",
    "Statement of Claim": "PLEAD",
    "Statement of Defence": "PLEAD",
    "Final Arguments": "PLEAD",
    "Hearing Notes": "RECORD",
    "Evidence Note": "RECORD",
    "Meeting Notes": "RECORD",
    "Client Email": "NOTIFY",
    "Internal Email": "NOTIFY",
    "Award Summary": "RECORD",
    "Matter Closure Memo": "NOTIFY",
}

_PURPOSE_PHRASES: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    ("ESTABLISH", (
        re.compile(r"\bengagement letter\b", re.I),
        re.compile(r"\bpleased to act\b", re.I),
        re.compile(r"\bretain(?:ed|er)\b", re.I),
        re.compile(r"\bscope of (?:our )?engagement\b", re.I),
        re.compile(r"\bfee(?:s)? (?:and|&) (?:billing|compensation)\b", re.I),
    )),
    ("ASSESS", (
        re.compile(r"\binitial case assessment\b", re.I),
        re.compile(r"\bcase assessment\b", re.I),
        re.compile(r"\bpreliminary assessment\b", re.I),
        re.compile(r"\brisk(?:s)? assessment\b", re.I),
    )),
    ("PROPOSE", (
        re.compile(r"\bterm sheet\b", re.I),
        re.compile(r"\bproposed (?:terms|transaction)\b", re.I),
        re.compile(r"\bindicative terms\b", re.I),
        re.compile(r"\bnon-?binding\b", re.I),
    )),
    ("ANALYZE", (
        re.compile(r"\bresearch memo\b", re.I),
        re.compile(r"\blegal opinion\b", re.I),
        re.compile(r"\banalysis\b", re.I),
        re.compile(r"\brecommendation(?:s)?\b", re.I),
    )),
    ("PLEAD", (
        re.compile(r"\bstatement of claim\b", re.I),
        re.compile(r"\bstatement of defence\b", re.I),
        re.compile(r"\bplaintiff (?:states|avers)\b", re.I),
        re.compile(r"\bprayer for relief\b", re.I),
    )),
    ("RECORD", (
        re.compile(r"\bhearing notes?\b", re.I),
        re.compile(r"\btranscript\b", re.I),
        re.compile(r"\bwitness\b", re.I),
        re.compile(r"\bevidence note\b", re.I),
    )),
    ("AMEND", (
        re.compile(r"\bamendment\b", re.I),
        re.compile(r"\bsupplemental agreement\b", re.I),
    )),
    ("NOTIFY", (
        re.compile(r"\bnotice\b", re.I),
        re.compile(r"\bwe write to\b", re.I),
        re.compile(r"\bplease be advised\b", re.I),
    )),
)


@dataclass
class PurposeSignals:
    """Cheap purpose evidence from title / headings / opening (not full body)."""

    purpose: str
    purpose_source: str  # type | phrase | fallback
    role_family: str
    document_role: str
    phrase_hits: list[str] = field(default_factory=list)
    title_purpose_tokens: list[str] = field(default_factory=list)
    opening_chars: int = 0
    # surface representations for D6.2 ablation
    title_text: str = ""
    heading_text: str = ""
    opening_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _headings(text: str, *, max_lines: int = 40) -> list[str]:
    out: list[str] = []
    for line in text.splitlines()[:200]:
        s = line.strip()
        if not s:
            continue
        if s.isupper() and 3 <= len(s) <= 80:
            out.append(s)
        elif re.match(r"^(?:Article|Section|Clause)\s+\d+", s, re.I):
            out.append(s)
        if len(out) >= max_lines:
            break
    return out


def infer_purpose(
    document_type: str | None,
    *,
    title: str | None = None,
    body: str | None = None,
    opening_chars: int = 1000,
) -> PurposeSignals:
    """Infer document purpose from type + title/header/opening phrases."""
    dtype = (document_type or "").strip()
    title_s = (title or "").strip()
    body_s = body or ""
    opening = body_s[:opening_chars]
    headings = _headings(body_s)
    heading_blob = "\n".join(headings[:20])
    surface = f"{title_s}\n{heading_blob}\n{opening}"

    role = infer_document_role(dtype, title_s)
    family = infer_role_family(dtype, document_role=role, title=title_s)

    phrase_hits: list[str] = []
    phrase_purpose: str | None = None
    for purpose, patterns in _PURPOSE_PHRASES:
        for pat in patterns:
            if pat.search(surface):
                phrase_hits.append(f"{purpose}:{pat.pattern}")
                if phrase_purpose is None:
                    phrase_purpose = purpose

    if dtype in _TYPE_TO_PURPOSE:
        purpose = _TYPE_TO_PURPOSE[dtype]
        source = "type"
        # Prefer phrase when it conflicts? Keep type as primary for ceiling stability;
        # record phrase as evidence.
        if phrase_purpose and phrase_purpose != purpose:
            source = "type_with_phrase_conflict"
    elif phrase_purpose:
        purpose = phrase_purpose
        source = "phrase"
    else:
        # Coarse fallback from role family
        fam_fallback = {
            "TRANSACTIONAL": "ESTABLISH",
            "ANALYSIS": "ANALYZE",
            "PLEADING": "PLEAD",
            "EVIDENCE_RECORD": "RECORD",
            "CORRESPONDENCE": "NOTIFY",
        }
        purpose = fam_fallback.get(family, "OTHER")
        source = "family_fallback"

    title_tokens = [
        t for t in ("engagement", "assessment", "term sheet", "research",
                    "opinion", "claim", "hearing", "amendment", "notice")
        if t in title_s.lower()
    ]

    return PurposeSignals(
        purpose=purpose,
        purpose_source=source,
        role_family=family,
        document_role=role,
        phrase_hits=phrase_hits[:12],
        title_purpose_tokens=title_tokens,
        opening_chars=len(opening),
        title_text=title_s,
        heading_text=heading_blob[:500],
        opening_text=opening[:500],
    )


def document_types_for_purposes(purposes: list[str] | set[str]) -> list[str]:
    wanted = {p.upper() for p in purposes}
    return sorted({t for t, p in _TYPE_TO_PURPOSE.items() if p in wanted})


def oracle_purposes_from_gold(gold_docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive oracle purposes from gold docs (type + optional body/title)."""
    counts: Counter[str] = Counter()
    for doc in gold_docs:
        sig = infer_purpose(
            doc.get("document_type"),
            title=doc.get("title"),
            body=doc.get("body"),
        )
        counts[sig.purpose] += 1
    total = max(sum(counts.values()), 1)
    return [
        {
            "purpose": purpose,
            "confidence": 1.0,
            "n_gold": n,
            "gold_share": round(n / total, 4),
        }
        for purpose, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    ]


def purpose_card(doc: dict[str, Any], signals: PurposeSignals) -> dict[str, Any]:
    """Human-readable debug card comparing purpose vs topics."""
    body = (doc.get("body") or "")[:800].lower()
    topics = [
        t for t in (
            "investment", "insider", "ownership", "pricing", "upsi", "sebi",
            "non-compete", "joint venture", "force majeure", "flood",
            "transfer pricing", "title", "diligence",
        )
        if t in body or t in (doc.get("title") or "").lower()
    ]
    return {
        "document_id": doc.get("document_id"),
        "document_type": doc.get("document_type"),
        "title": doc.get("title"),
        "role_family": signals.role_family,
        "document_role": signals.document_role,
        "purpose": signals.purpose,
        "purpose_source": signals.purpose_source,
        "signals": {
            "phrase_hits": signals.phrase_hits,
            "title_tokens": signals.title_purpose_tokens,
        },
        "topics": topics,
    }
