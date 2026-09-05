"""P5.6-C5.5-D — Cheap document profile features (no LLM).

Discovers discriminative structure/genre signals that separate holder
documents (EL/ICA / primary artifacts) from topic-similar memos/opinions.
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

# Types that currently confuse semantic retrieval inside themes.
HARD_NEG_TYPES = frozenset({
    "Research Memo",
    "Legal Opinion",
    "Matter Strategy Note",
    "KM Note",
    "Meeting Notes",
})

EL_ICA_TYPES = frozenset({"Engagement Letter", "Initial Case Assessment"})

# Role families — retrieval reasons over these, not raw document_type.
ROLE_FAMILIES = (
    "TRANSACTIONAL",
    "ANALYSIS",
    "PLEADING",
    "EVIDENCE_RECORD",
    "CORRESPONDENCE",
    "OUTCOME",
    "ADMIN",
    "OTHER",
)

# document_role → role_family
_ROLE_TO_FAMILY: dict[str, str] = {
    "ENGAGEMENT_DOCUMENT": "TRANSACTIONAL",
    "PRIMARY_AGREEMENT": "TRANSACTIONAL",
    "RESEARCH_MEMO": "ANALYSIS",
    "LEGAL_OPINION": "ANALYSIS",
    "STRATEGY_NOTE": "ANALYSIS",
    "ANALYSIS": "ANALYSIS",
    "PLEADING": "PLEADING",
    "PROCEDURAL": "EVIDENCE_RECORD",
    "EVIDENCE": "EVIDENCE_RECORD",
    "CORRESPONDENCE": "CORRESPONDENCE",
    "OUTCOME": "OUTCOME",
    "ADMIN": "ADMIN",
    "OTHER": "OTHER",
}

# document_type → role_family (direct; keeps taxonomy explicit)
_TYPE_TO_FAMILY: dict[str, str] = {
    "Engagement Letter": "TRANSACTIONAL",
    "Initial Case Assessment": "TRANSACTIONAL",
    "Share Purchase Agreement": "TRANSACTIONAL",
    "Term Sheet": "TRANSACTIONAL",
    "Research Memo": "ANALYSIS",
    "Legal Opinion": "ANALYSIS",
    "Matter Strategy Note": "ANALYSIS",
    "KM Note": "ANALYSIS",
    "Partner Note": "ANALYSIS",
    "Statement of Claim": "PLEADING",
    "Statement of Defence": "PLEADING",
    "Final Arguments": "PLEADING",
    "Hearing Notes": "EVIDENCE_RECORD",
    "Evidence Note": "EVIDENCE_RECORD",
    "Meeting Notes": "CORRESPONDENCE",
    "Client Email": "CORRESPONDENCE",
    "Internal Email": "CORRESPONDENCE",
    "Award Summary": "OUTCOME",
    "Matter Closure Memo": "ADMIN",
}

# Heuristic role map: what the document *does* in a matter (not just type label).
_TYPE_TO_ROLE: dict[str, str] = {
    "Engagement Letter": "ENGAGEMENT_DOCUMENT",
    "Initial Case Assessment": "ENGAGEMENT_DOCUMENT",
    "Share Purchase Agreement": "PRIMARY_AGREEMENT",
    "Term Sheet": "PRIMARY_AGREEMENT",
    "Research Memo": "RESEARCH_MEMO",
    "Legal Opinion": "LEGAL_OPINION",
    "Matter Strategy Note": "STRATEGY_NOTE",
    "KM Note": "ANALYSIS",
    "Meeting Notes": "CORRESPONDENCE",
    "Client Email": "CORRESPONDENCE",
    "Internal Email": "CORRESPONDENCE",
    "Partner Note": "ANALYSIS",
    "Statement of Claim": "PLEADING",
    "Statement of Defence": "PLEADING",
    "Hearing Notes": "PROCEDURAL",
    "Final Arguments": "PLEADING",
    "Award Summary": "OUTCOME",
    "Evidence Note": "EVIDENCE",
    "Matter Closure Memo": "ADMIN",
}


@dataclass
class DocFeatures:
    document_id: str
    matter_id: str | None = None
    document_type: str | None = None
    document_role: str | None = None
    role_family: str | None = None
    title: str | None = None
    # cheap counts / flags
    word_count: int = 0
    char_count: int = 0
    line_count: int = 0
    section_heading_count: int = 0
    date_count: int = 0
    number_count: int = 0
    currency_count: int = 0
    percentage_count: int = 0
    citation_count: int = 0
    table_like_count: int = 0
    party_mention_count: int = 0
    defined_term_count: int = 0
    shall_count: int = 0
    agreement_count: int = 0
    signature_present: bool = False
    engagement_header: bool = False
    assessment_header: bool = False
    memo_header: bool = False
    opinion_header: bool = False
    # binary helpers for analysis
    is_el_ica: bool = False
    is_hard_neg_type: bool = False
    title_has_type_token: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b",
    re.I,
)
_CURRENCY_RE = re.compile(r"\b(?:USD|EUR|GBP|INR|SGD|\$|€|£|₹)\s?[\d,]+(?:\.\d+)?\b", re.I)
_PCT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%")
_CITE_RE = re.compile(
    r"\b(?:v\.|vs\.|section\s+\d+|art(?:icle)?\s+\d+|AIR\s+\d{4}|SCC\s+\d+)\b",
    re.I,
)
_DEFINED_RE = re.compile(
    r'"[^"]{2,40}"\s+(?:means|shall mean)|hereinafter\s+referred\s+to\s+as',
    re.I,
)
_HEADING_RE = re.compile(r"^(?:[A-Z][A-Z0-9 /&-]{3,}|#{1,3}\s+\S|Article\s+\d+|Section\s+\d+)", re.M)
_PARTY_RE = re.compile(r"\b(?:party|parties|client|counterparty|between)\b", re.I)
_TABLE_RE = re.compile(r"\|.+\||\t.+\t")


def infer_document_role(document_type: str | None, title: str | None = None) -> str:
    dtype = (document_type or "").strip()
    if dtype in _TYPE_TO_ROLE:
        return _TYPE_TO_ROLE[dtype]
    low = f"{dtype} {(title or '')}".lower()
    if "engagement" in low:
        return "ENGAGEMENT_DOCUMENT"
    if "agreement" in low or "deed" in low or "term sheet" in low:
        return "PRIMARY_AGREEMENT"
    if "memo" in low:
        return "RESEARCH_MEMO"
    if "opinion" in low:
        return "LEGAL_OPINION"
    if "claim" in low or "defence" in low or "defense" in low or "petition" in low:
        return "PLEADING"
    if "hearing" in low or "transcript" in low:
        return "PROCEDURAL"
    return "OTHER"


def infer_role_family(
    document_type: str | None,
    *,
    document_role: str | None = None,
    title: str | None = None,
) -> str:
    """Map type/role → role_family (retrieval primitive)."""
    dtype = (document_type or "").strip()
    if dtype in _TYPE_TO_FAMILY:
        return _TYPE_TO_FAMILY[dtype]
    role = document_role or infer_document_role(dtype, title)
    return _ROLE_TO_FAMILY.get(role, "OTHER")


def document_types_for_families(families: list[str] | set[str]) -> list[str]:
    """Invert taxonomy: which document_types belong to the given families."""
    wanted = {f.upper() for f in families}
    return sorted({t for t, fam in _TYPE_TO_FAMILY.items() if fam in wanted})


def oracle_role_families_from_gold(
    gold_docs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Derive oracle role families from gold document labels (no query hardcoding).

    Returns families with confidence=1.0 for the oracle experiment.
    """
    counts: dict[str, int] = {}
    for doc in gold_docs:
        fam = infer_role_family(
            doc.get("document_type"),
            title=doc.get("title"),
        )
        counts[fam] = counts.get(fam, 0) + 1
    total = max(sum(counts.values()), 1)
    out = [
        {
            "family": fam,
            "confidence": 1.0,  # oracle
            "n_gold": n,
            "gold_share": round(n / total, 4),
        }
        for fam, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    ]
    return out


def extract_doc_features(
    *,
    document_id: str,
    matter_id: str | None,
    document_type: str | None,
    title: str | None,
    body: str | None,
    folder_path: str | None = None,
) -> DocFeatures:
    text = body or ""
    title_s = title or ""
    words = re.findall(r"[A-Za-z0-9']+", text)
    lines = text.splitlines()
    role = infer_document_role(document_type, title_s)
    dtype = document_type or ""
    head = text[:400].upper()
    family = infer_role_family(dtype, document_role=role, title=title_s)

    feat = DocFeatures(
        document_id=document_id,
        matter_id=matter_id,
        document_type=dtype or None,
        document_role=role,
        role_family=family,
        title=title_s or None,
        word_count=len(words),
        char_count=len(text),
        line_count=len(lines),
        section_heading_count=len(_HEADING_RE.findall(text)),
        date_count=len(_DATE_RE.findall(text)),
        number_count=len(re.findall(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b", text)),
        currency_count=len(_CURRENCY_RE.findall(text)),
        percentage_count=len(_PCT_RE.findall(text)),
        citation_count=len(_CITE_RE.findall(text)),
        table_like_count=len(_TABLE_RE.findall(text)),
        party_mention_count=len(_PARTY_RE.findall(text)),
        defined_term_count=len(_DEFINED_RE.findall(text)),
        shall_count=len(re.findall(r"\bshall\b", text, re.I)),
        agreement_count=len(re.findall(r"\bagreement\b", text, re.I)),
        signature_present=bool(
            re.search(r"\b(?:signature|signed by|yours sincerely|for and on behalf)\b", text, re.I)
        ),
        engagement_header="ENGAGEMENT LETTER" in head,
        assessment_header="INITIAL CASE ASSESSMENT" in head or "CASE ASSESSMENT" in head,
        memo_header="RESEARCH MEMO" in head or "MEMORANDUM" in head,
        opinion_header="LEGAL OPINION" in head or "OPINION" in head[:80],
        is_el_ica=dtype in EL_ICA_TYPES,
        is_hard_neg_type=dtype in HARD_NEG_TYPES,
        title_has_type_token=any(
            tok in title_s.lower()
            for tok in ("engagement", "assessment", "research memo", "opinion", "strategy")
        ),
    )
    return feat


def feature_vector(feat: DocFeatures) -> dict[str, float]:
    """Numeric / binary features for discriminative analysis."""
    return {
        "word_count": float(feat.word_count),
        "char_count": float(feat.char_count),
        "section_heading_count": float(feat.section_heading_count),
        "date_count": float(feat.date_count),
        "number_count": float(feat.number_count),
        "currency_count": float(feat.currency_count),
        "percentage_count": float(feat.percentage_count),
        "citation_count": float(feat.citation_count),
        "table_like_count": float(feat.table_like_count),
        "party_mention_count": float(feat.party_mention_count),
        "defined_term_count": float(feat.defined_term_count),
        "shall_count": float(feat.shall_count),
        "agreement_count": float(feat.agreement_count),
        "signature_present": 1.0 if feat.signature_present else 0.0,
        "engagement_header": 1.0 if feat.engagement_header else 0.0,
        "assessment_header": 1.0 if feat.assessment_header else 0.0,
        "memo_header": 1.0 if feat.memo_header else 0.0,
        "opinion_header": 1.0 if feat.opinion_header else 0.0,
        "is_el_ica": 1.0 if feat.is_el_ica else 0.0,
        "role_engagement": 1.0 if feat.document_role == "ENGAGEMENT_DOCUMENT" else 0.0,
        "role_research": 1.0 if feat.document_role == "RESEARCH_MEMO" else 0.0,
        "role_opinion": 1.0 if feat.document_role == "LEGAL_OPINION" else 0.0,
        "role_strategy": 1.0 if feat.document_role == "STRATEGY_NOTE" else 0.0,
        "family_transactional": 1.0 if feat.role_family == "TRANSACTIONAL" else 0.0,
        "family_analysis": 1.0 if feat.role_family == "ANALYSIS" else 0.0,
        "family_pleading": 1.0 if feat.role_family == "PLEADING" else 0.0,
        "title_has_type_token": 1.0 if feat.title_has_type_token else 0.0,
        "short_doc_lt_800_chars": 1.0 if feat.char_count < 800 else 0.0,
        "long_doc_gt_1200_chars": 1.0 if feat.char_count > 1200 else 0.0,
    }


def log_odds(p_pos: float, p_neg: float, *, eps: float = 1e-3) -> float:
    p = min(max(p_pos, eps), 1 - eps)
    q = min(max(p_neg, eps), 1 - eps)
    return math.log(p / (1 - p)) - math.log(q / (1 - q))


def discriminative_table(
    positives: list[dict[str, float]],
    negatives: list[dict[str, float]],
    *,
    binary_threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Compare feature rates/means: gold vs hard-negatives."""
    if not positives or not negatives:
        return []
    keys = sorted(positives[0].keys())
    rows: list[dict[str, Any]] = []
    n_pos, n_neg = len(positives), len(negatives)
    for key in keys:
        pos_vals = [float(p.get(key, 0)) for p in positives]
        neg_vals = [float(n.get(key, 0)) for n in negatives]
        # Treat mostly 0/1 features as binary rates
        is_binary = all(v in (0.0, 1.0) for v in pos_vals + neg_vals)
        if is_binary:
            p_pos = sum(pos_vals) / n_pos
            p_neg = sum(neg_vals) / n_neg
            rows.append({
                "feature": key,
                "kind": "binary",
                "p_gold": round(p_pos, 4),
                "p_hard_neg": round(p_neg, 4),
                "mean_gold": round(p_pos, 4),
                "mean_hard_neg": round(p_neg, 4),
                "log_odds": round(log_odds(p_pos, p_neg), 3),
                "abs_log_odds": round(abs(log_odds(p_pos, p_neg)), 3),
            })
        else:
            m_pos = sum(pos_vals) / n_pos
            m_neg = sum(neg_vals) / n_neg
            # rate of "high" for continuous: above cohort median
            mid = sorted(pos_vals + neg_vals)[len(pos_vals + neg_vals) // 2]
            p_pos = sum(1 for v in pos_vals if v >= mid) / n_pos
            p_neg = sum(1 for v in neg_vals if v >= mid) / n_neg
            rows.append({
                "feature": key,
                "kind": "continuous",
                "p_gold": round(p_pos, 4),
                "p_hard_neg": round(p_neg, 4),
                "mean_gold": round(m_pos, 3),
                "mean_hard_neg": round(m_neg, 3),
                "log_odds": round(log_odds(p_pos, p_neg), 3),
                "abs_log_odds": round(abs(log_odds(p_pos, p_neg)), 3),
            })
    rows.sort(key=lambda r: r["abs_log_odds"], reverse=True)
    return rows
