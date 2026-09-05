"""Document intelligence: summaries, entities, clause tags (ingest-time)."""
from __future__ import annotations

import re

from architecture_sim.cache import VersionedCache
from architecture_sim.hashing import sha256_text
from architecture_sim.models import DocumentBlock, DocumentVersion

CLAUSE_KEYWORDS: dict[str, list[str]] = {
    "indemnification": ["indemnif", "tax claims", "losses arising"],
    "change_of_control": ["change of control", "voting securities"],
    "termination": ["terminat", "outside date"],
    "liability": ["aggregate liability", "consequential", "liability cap"],
    "governing_law": ["governed by the laws", "courts of"],
    "assignment": ["may not be assigned", "assign to an affiliate"],
    "non_compete": ["not to compete", "non-compete"],
    "unusual_obligations": ["minimum cash balance", "right of first refusal"],
}

ENTITY_RE = re.compile(
    r"\b(Buyer|Seller|Party|Parties|Affiliate|Delaware|New York|Singapore|California)\b"
)
MONEY_RE = re.compile(r"\$[\d,]+(?:,\d{3})*(?:\.\d+)?")


def extract_entities(text: str) -> list[str]:
    ents = set(ENTITY_RE.findall(text))
    ents.update(MONEY_RE.findall(text))
    return sorted(ents)


def detect_clauses(text: str) -> list[str]:
    low = text.lower()
    return [c for c, kws in CLAUSE_KEYWORDS.items() if any(k in low for k in kws)]


def section_summary(section_id: str, blocks: list[DocumentBlock]) -> str:
    paras = [b.text for b in blocks if b.section_id == section_id]
    if not paras:
        return ""
    joined = " ".join(paras)
    clauses = detect_clauses(joined)
    money = MONEY_RE.findall(joined)
    head = paras[0][:160]
    extra = ""
    if clauses:
        extra += f" Clauses: {', '.join(clauses)}."
    if money:
        extra += f" Amounts: {', '.join(money[:3])}."
    return f"Section {section_id}: {head}…{extra}"


def document_summary(version: DocumentVersion, blocks: list[DocumentBlock]) -> str:
    clauses = detect_clauses(version.raw_text)
    entities = extract_entities(version.raw_text)
    sections = sorted({b.section_id for b in blocks if b.section_id not in ("preamble",)})
    return (
        f"{version.page_count}-page document. "
        f"Sections: {len(sections)}. "
        f"Key clauses: {', '.join(clauses) or 'none detected'}. "
        f"Parties/entities: {', '.join(entities[:8]) or 'n/a'}."
    )


def enrich_version(
    version: DocumentVersion,
    blocks: list[DocumentBlock],
    cache: VersionedCache,
    summary_version: str = "summary_v1",
) -> DocumentVersion:
    """Attach intelligence; cache by content_hash + summary pipeline version."""
    cached = cache.get("summary", version.document_id, version.content_hash, summary_version)
    if cached:
        version.executive_summary = cached["executive_summary"]
        version.section_summaries = cached["section_summaries"]
        version.entities = cached["entities"]
        version.clauses = cached["clauses"]
        return version

    section_ids = sorted({b.section_id for b in blocks})
    section_summaries = {
        sid: section_summary(sid, [b for b in blocks if b.section_id == sid])
        for sid in section_ids
        if sid != "preamble"
    }
    version.section_summaries = section_summaries
    version.executive_summary = document_summary(version, blocks)
    version.entities = extract_entities(version.raw_text)
    version.clauses = detect_clauses(version.raw_text)

    cache.set(
        {
            "executive_summary": version.executive_summary,
            "section_summaries": version.section_summaries,
            "entities": version.entities,
            "clauses": version.clauses,
        },
        "summary",
        version.document_id,
        version.content_hash,
        summary_version,
    )
    return version


def lexical_diff(old_text: str, new_text: str) -> dict:
    """Simple line-oriented lexical diff summary."""
    import difflib

    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm="", n=0))
    added = [d[1:] for d in diff if d.startswith("+") and not d.startswith("+++")]
    removed = [d[1:] for d in diff if d.startswith("-") and not d.startswith("---")]
    return {
        "added_lines": len(added),
        "removed_lines": len(removed),
        "sample_added": added[:5],
        "sample_removed": removed[:5],
        "content_changed": sha256_text(old_text) != sha256_text(new_text),
    }


def semantic_diff_hints(old_text: str, new_text: str) -> list[dict]:
    """Rule-based semantic/legal diff hints (liability caps, governing law, etc.)."""
    hints: list[dict] = []
    old_money = set(MONEY_RE.findall(old_text))
    new_money = set(MONEY_RE.findall(new_text))
    if old_money != new_money:
        hints.append(
            {
                "category": "liability",
                "title": "Monetary amounts changed",
                "old": sorted(old_money),
                "new": sorted(new_money),
                "severity": "high",
            }
        )
    for jur in ("New York", "Delaware", "Singapore", "California", "England and Wales"):
        in_old = jur in old_text
        in_new = jur in new_text
        if in_old != in_new:
            hints.append(
                {
                    "category": "governing_law",
                    "title": f"Jurisdiction mention changed: {jur}",
                    "old": jur if in_old else None,
                    "new": jur if in_new else None,
                    "severity": "medium",
                }
            )
    old_c = set(detect_clauses(old_text))
    new_c = set(detect_clauses(new_text))
    for added in sorted(new_c - old_c):
        hints.append(
            {
                "category": added,
                "title": f"Clause type appeared: {added}",
                "old": None,
                "new": added,
                "severity": "medium",
            }
        )
    return hints
