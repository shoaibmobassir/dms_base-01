"""P5.6-C4 — Matter evidence profiles + field-weighted holder ranking.

Profiles are built deterministically from Postgres (no LLM).
Primary signals (in priority order):
  1. theme_key match (semantic clusters in this corpus)
  2. practice_area match
  3. legal_issues / concept overlap
  4. title / party lexical
  5. document-type intent
  6. optional in-matter document evidence (BM25 over docs)

Does not enable SEMANTIC_DOC_RESOLVE; does not change CE / P5.6-A.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.retrieval.matter_resolver import (
    MatterQueryRep,
    build_matter_query_rep,
    to_or_tsquery,
)

# Query → theme_key (matches dummy-firm theme clusters)
_THEME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"insider|upsi|price.?sensitive|scn", re.I), "sebi_insider"),
    (re.compile(r"non-?compete|restraint of trade|post-employment|garden leave", re.I), "employment_exit"),
    (re.compile(r"title diligence|family settlement|unregistered|marketable title|rera", re.I), "title_diligence"),
    (re.compile(r"transfer pricing|intra-?group|arm.?s length|management fee", re.I), "transfer_pricing"),
    (re.compile(r"supply.?contract|quality failure|take-or-pay|terminat", re.I), "commercial_arb"),
    (re.compile(r"joint venture|deadlock|shotgun|russian roulette|50:50|50\s*:\s*50", re.I), "jv"),
    (re.compile(r"natural disaster|force majeure|flood|contractual performance|impossibility", re.I), "flood_force_majeure"),
    (re.compile(r"share pledge|loan agreement|security", re.I), "loan_security"),
    (re.compile(r"indemnity|spa\b|purchase agreement", re.I), "spa_indemnity_cap"),
    (re.compile(r"cirp|insolvency|ibc|nclt", re.I), "cirp"),
    (re.compile(r"oppression|mismanagement|shareholder", re.I), "shareholder_oppression"),
)

_DOC_TYPE_INTENT: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"employment agreement|employment contract", re.I),
     ("Engagement Letter", "Legal Opinion", "Research Memo")),
    (re.compile(r"share purchase|spa\b|term sheet|merger|acquisition agreement", re.I),
     ("Share Purchase Agreement", "Term Sheet", "Due Diligence Report", "Board Resolution")),
    (re.compile(r"loan|facility|credit agreement|pledge", re.I),
     ("Loan Agreement", "Term Sheet")),
    (re.compile(r"arbitration|award|statement of claim", re.I),
     ("Award Summary", "Statement of Claim", "Statement of Defence", "Hearing Notes")),
)

# Field weights for profile score (tunable; measured in ablation)
DEFAULT_WEIGHTS: dict[str, float] = {
    "theme": 50.0,
    "practice": 8.0,
    "legal_issue": 6.0,
    "title": 4.0,
    "party": 3.0,
    "doc_type": 5.0,
    "doc_evidence": 12.0,
    "lexical_base": 1.0,
}


@dataclass
class QueryEvidenceIntent:
    """Structured intent for matter-profile ranking."""

    rep: MatterQueryRep
    theme_keys: list[str] = field(default_factory=list)
    doc_type_targets: list[str] = field(default_factory=list)
    concept_tokens: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "theme_keys": self.theme_keys,
            "doc_type_targets": self.doc_type_targets,
            "concepts": self.rep.concepts,
            "practice_area": self.rep.practice_area,
            "terms": self.rep.terms[:12],
        }


def infer_theme_keys(text: str) -> list[str]:
    found: list[str] = []
    for pattern, key in _THEME_PATTERNS:
        if pattern.search(text):
            found.append(key)
    return list(dict.fromkeys(found))


def infer_doc_type_targets(text: str) -> list[str]:
    found: list[str] = []
    for pattern, types in _DOC_TYPE_INTENT:
        if pattern.search(text):
            found.extend(types)
    return list(dict.fromkeys(found))


def build_query_evidence_intent(
    raw: str,
    *,
    search_text: str | None = None,
    practice_area: str | None = None,
) -> QueryEvidenceIntent:
    rep = build_matter_query_rep(raw, search_text=search_text, practice_area=practice_area)
    blob = f"{raw} {search_text or ''}"
    themes = infer_theme_keys(blob)
    # Prefer concept-driven themes; fall back to practice-only later in SQL
    return QueryEvidenceIntent(
        rep=rep,
        theme_keys=themes,
        doc_type_targets=infer_doc_type_targets(blob),
        concept_tokens=[c.lower() for c in rep.concepts] + [t.lower() for t in rep.terms[:8]],
    )


def score_matter_profile(
    profile: dict[str, Any],
    intent: QueryEvidenceIntent,
    *,
    weights: dict[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    """Explainable field-weighted score for one matter profile row."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    parts: dict[str, float] = {}

    theme = (profile.get("theme_key") or "").strip()
    if intent.theme_keys and theme in intent.theme_keys:
        parts["theme"] = w["theme"]
    elif intent.theme_keys:
        parts["theme"] = 0.0
    else:
        parts["theme"] = 0.0

    practice = (profile.get("practice_area") or "").strip()
    if intent.rep.practice_area and practice.lower() == intent.rep.practice_area.lower():
        parts["practice"] = w["practice"]
    else:
        parts["practice"] = 0.0

    issues = [str(x).lower() for x in (profile.get("legal_issues") or [])]
    concept_hits = 0
    for tok in intent.concept_tokens:
        if any(tok in issue or issue in tok for issue in issues if issue):
            concept_hits += 1
    parts["legal_issue"] = min(concept_hits, 4) * (w["legal_issue"] / 2.0)

    title = (profile.get("title") or "").lower()
    title_hits = sum(1 for t in intent.rep.terms[:10] if t.lower() in title)
    parts["title"] = min(title_hits, 3) * (w["title"] / 2.0)

    parties = " ".join([
        str(profile.get("client_name") or ""),
        str(profile.get("opposing_party") or ""),
    ]).lower()
    party_hits = sum(1 for t in intent.rep.terms[:8] if len(t) > 3 and t.lower() in parties)
    parts["party"] = min(party_hits, 2) * w["party"]

    doc_types = [str(x) for x in (profile.get("document_types") or [])]
    if intent.doc_type_targets:
        overlap = len(set(doc_types) & set(intent.doc_type_targets))
        parts["doc_type"] = overlap * w["doc_type"]
    else:
        parts["doc_type"] = 0.0

    # Precomputed optional document-evidence score (0..1 normalized from SQL)
    doc_ev = float(profile.get("doc_evidence_score") or 0.0)
    parts["doc_evidence"] = doc_ev * w["doc_evidence"]

    lex = float(profile.get("lexical_score") or 0.0)
    parts["lexical_base"] = lex * w["lexical_base"]

    total = sum(parts.values())
    return total, parts
