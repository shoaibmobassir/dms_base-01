"""Multi-Level Version Diff Engine.

Provides dual representations of version changes:
1. Lexical Diff: Word- and line-level redlines (insertions, deletions, unchanged).
2. Semantic Legal Diff: High-level clause-by-clause comparison evaluating
   material changes, financial impacts, liability shifts, and risk levels.
"""
from __future__ import annotations

import difflib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, List, Optional

from psycopg.rows import dict_row

from app.db.connection import connect
from app.documents.canonical import (
    DocumentBlock,
    get_version_blocks,
    parse_canonical_blocks,
    save_canonical_blocks,
)


@dataclass
class RedlineToken:
    token_type: str  # insert | delete | equal
    text: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class MaterialLegalChange:
    change_id: str
    section_id: Optional[str]
    clause_title: str
    category: str  # indemnity | liability | governing_law | termination | change_of_control | general
    change_type: str  # ADDED | MODIFIED | DELETED | UNCHANGED
    risk_level: str  # CRITICAL | HIGH | MEDIUM | LOW | NEUTRAL
    risk_direction: str  # risk_increased | risk_decreased | neutral
    financial_impact: Optional[str]
    summary: str
    evidence_old: Optional[dict] = None
    evidence_new: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VersionDiffResult:
    diff_id: str
    document_id: str
    source_version_id: str
    target_version_id: str
    source_version_number: int
    target_version_number: int
    total_added_lines: int
    total_removed_lines: int
    material_changes_count: int
    overall_risk_level: str
    lexical_redline: List[dict]
    material_changes: List[dict]
    created_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_word_redline(text_a: str, text_b: str) -> List[RedlineToken]:
    """Compute word-level visual redline tokens between two texts."""
    words_a = re.findall(r"\S+|\s+", text_a)
    words_b = re.findall(r"\S+|\s+", text_b)

    matcher = difflib.SequenceMatcher(None, words_a, words_b)
    tokens: List[RedlineToken] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            tokens.append(RedlineToken("equal", "".join(words_a[i1:i2])))
        elif tag == "delete":
            tokens.append(RedlineToken("delete", "".join(words_a[i1:i2])))
        elif tag == "insert":
            tokens.append(RedlineToken("insert", "".join(words_b[j1:j2])))
        elif tag == "replace":
            tokens.append(RedlineToken("delete", "".join(words_a[i1:i2])))
            tokens.append(RedlineToken("insert", "".join(words_b[j1:j2])))

    return tokens


def _detect_clause_category(text: str) -> str:
    """Classify legal category from clause text."""
    lower = text.lower()
    if any(k in lower for k in ["indemn", "hold harmless", "defend"]):
        return "indemnity"
    if any(k in lower for k in ["liability", "aggregate limit", "consequential damages", "cap"]):
        return "liability"
    if any(k in lower for k in ["governing law", "jurisdiction", "venue", "courts of"]):
        return "governing_law"
    if any(k in lower for k in ["terminat", "cure period", "default"]):
        return "termination"
    if any(k in lower for k in ["change of control", "merger", "assignment", "successor"]):
        return "change_of_control"
    if any(k in lower for k in ["confidential", "non-disclosure", "trade secret"]):
        return "confidentiality"
    return "general"


def _extract_dollar_amount(text: str) -> Optional[int]:
    """Extract first numeric dollar value for financial comparison."""
    m = re.search(r"\$\s*([0-9,]+(?:\.[0-9]{2})?)", text)
    if m:
        cleaned = m.group(1).replace(",", "")
        try:
            return int(float(cleaned))
        except ValueError:
            return None
    return None


def compute_semantic_diff(
    blocks_a: List[dict],
    blocks_b: List[dict],
) -> List[MaterialLegalChange]:
    """Compare canonical blocks across two versions and extract structured legal changes."""
    changes: List[MaterialLegalChange] = []

    # Map blocks by section_id or index
    map_a = {b.get("section_id") or f"seq_{b['sequence']}": b for b in blocks_a}
    map_b = {b.get("section_id") or f"seq_{b['sequence']}": b for b in blocks_b}

    all_keys = list(dict.fromkeys(list(map_a.keys()) + list(map_b.keys())))

    for k in all_keys:
        ba = map_a.get(k)
        bb = map_b.get(k)

        if ba and not bb:
            # Deleted
            cat = _detect_clause_category(ba["text"])
            changes.append(
                MaterialLegalChange(
                    change_id=f"CHG-{uuid.uuid4().hex[:8].upper()}",
                    section_id=ba.get("section_id"),
                    clause_title=ba.get("section_title") or f"Section {ba.get('section_id', '')}",
                    category=cat,
                    change_type="DELETED",
                    risk_level="HIGH" if cat in ["indemnity", "liability", "termination"] else "MEDIUM",
                    risk_direction="risk_increased" if cat in ["indemnity", "liability"] else "neutral",
                    financial_impact=None,
                    summary=f"Section {ba.get('section_id', '')} was completely removed.",
                    evidence_old={"block_id": ba["block_id"], "page": ba["page_number"], "quote": ba["text"][:200]},
                    evidence_new=None,
                )
            )
        elif bb and not ba:
            # Added
            cat = _detect_clause_category(bb["text"])
            changes.append(
                MaterialLegalChange(
                    change_id=f"CHG-{uuid.uuid4().hex[:8].upper()}",
                    section_id=bb.get("section_id"),
                    clause_title=bb.get("section_title") or f"Section {bb.get('section_id', '')}",
                    category=cat,
                    change_type="ADDED",
                    risk_level="HIGH" if cat in ["indemnity", "liability", "termination"] else "LOW",
                    risk_direction="neutral",
                    financial_impact=None,
                    summary=f"New section added: {bb.get('section_title') or bb.get('section_id', '')}",
                    evidence_old=None,
                    evidence_new={"block_id": bb["block_id"], "page": bb["page_number"], "quote": bb["text"][:200]},
                )
            )
        elif ba and bb:
            # Compare text
            text_a = ba["text"].strip()
            text_b = bb["text"].strip()

            if text_a != text_b:
                cat = _detect_clause_category(text_b)
                dollar_a = _extract_dollar_amount(text_a)
                dollar_b = _extract_dollar_amount(text_b)

                financial_note = None
                risk_dir = "neutral"
                risk_level = "MEDIUM"

                if dollar_a is not None and dollar_b is not None:
                    diff_usd = dollar_b - dollar_a
                    if diff_usd > 0:
                        financial_note = f"Increased from ${dollar_a:,} to ${dollar_b:,} (+${diff_usd:,})"
                        risk_dir = "risk_increased"
                        risk_level = "HIGH"
                    elif diff_usd < 0:
                        financial_note = f"Decreased from ${dollar_a:,} to ${dollar_b:,} (-${abs(diff_usd):,})"
                        risk_dir = "risk_decreased"
                        risk_level = "LOW"
                    else:
                        financial_note = f"Amount unchanged at ${dollar_a:,}"
                elif cat == "governing_law":
                    risk_level = "HIGH"
                    financial_note = "Jurisdiction altered"

                summary = (
                    f"{cat.replace('_', ' ').title()} terms modified."
                    if not financial_note
                    else f"{cat.replace('_', ' ').title()} terms modified: {financial_note}"
                )

                changes.append(
                    MaterialLegalChange(
                        change_id=f"CHG-{uuid.uuid4().hex[:8].upper()}",
                        section_id=bb.get("section_id"),
                        clause_title=bb.get("section_title") or f"Section {bb.get('section_id', '')}",
                        category=cat,
                        change_type="MODIFIED",
                        risk_level=risk_level,
                        risk_direction=risk_dir,
                        financial_impact=financial_note,
                        summary=summary,
                        evidence_old={"block_id": ba["block_id"], "page": ba["page_number"], "quote": text_a[:200]},
                        evidence_new={"block_id": bb["block_id"], "page": bb["page_number"], "quote": text_b[:200]},
                    )
                )

    return changes


def diff_document_versions(
    version_id_a: str,
    version_id_b: str,
) -> VersionDiffResult:
    """Execute complete lexical + semantic diff between two document versions."""
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT version_id, document_id, version_number, title, body FROM document_versions WHERE version_id = %(vid)s",
                {"vid": version_id_a},
            )
            va = cur.fetchone()
            cur.execute(
                "SELECT version_id, document_id, version_number, title, body FROM document_versions WHERE version_id = %(vid)s",
                {"vid": version_id_b},
            )
            vb = cur.fetchone()

    if not va or not vb:
        raise ValueError("One or both document versions not found")

    body_a = va["body"] or ""
    body_b = vb["body"] or ""

    # Ensure canonical blocks exist for both versions
    blocks_a = get_version_blocks(version_id_a)
    if not blocks_a:
        parsed_a = parse_canonical_blocks(body_a, va["document_id"], version_id_a)
        save_canonical_blocks(parsed_a)
        blocks_a = [b.to_dict() for b in parsed_a]

    blocks_b = get_version_blocks(version_id_b)
    if not blocks_b:
        parsed_b = parse_canonical_blocks(body_b, vb["document_id"], version_id_b)
        save_canonical_blocks(parsed_b)
        blocks_b = [b.to_dict() for b in parsed_b]

    # Compute word-level redline
    redline_tokens = compute_word_redline(body_a, body_b)

    # Compute line counts
    lines_a = body_a.splitlines()
    lines_b = body_b.splitlines()
    diff_gen = difflib.unified_diff(lines_a, lines_b, lineterm="")
    added = sum(1 for l in diff_gen if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff_gen if l.startswith("-") and not l.startswith("---"))

    # Compute semantic legal diff
    material_changes = compute_semantic_diff(blocks_a, blocks_b)

    # Determine overall risk level
    if any(c.risk_level == "CRITICAL" for c in material_changes):
        overall_risk = "critical"
    elif any(c.risk_level == "HIGH" for c in material_changes):
        overall_risk = "high"
    elif any(c.risk_level == "MEDIUM" for c in material_changes):
        overall_risk = "medium"
    elif material_changes:
        overall_risk = "low"
    else:
        overall_risk = "neutral"

    diff_id = f"DIFF-{uuid.uuid4().hex[:10].upper()}"

    res = VersionDiffResult(
        diff_id=diff_id,
        document_id=va["document_id"],
        source_version_id=version_id_a,
        target_version_id=version_id_b,
        source_version_number=va["version_number"],
        target_version_number=vb["version_number"],
        total_added_lines=added,
        total_removed_lines=removed,
        material_changes_count=len(material_changes),
        overall_risk_level=overall_risk,
        lexical_redline=[t.to_dict() for t in redline_tokens],
        material_changes=[c.to_dict() for c in material_changes],
    )

    # Persist in DB
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO version_diffs (
                    diff_id, document_id, source_version_id, target_version_id,
                    lexical_diff, semantic_diff, material_changes_count, risk_level
                ) VALUES (
                    %(did)s, %(doc_id)s, %(svid)s, %(tvid)s,
                    %(lex)s, %(sem)s, %(count)s, %(risk)s
                )
                ON CONFLICT (source_version_id, target_version_id) DO UPDATE SET
                    lexical_diff = EXCLUDED.lexical_diff,
                    semantic_diff = EXCLUDED.semantic_diff,
                    material_changes_count = EXCLUDED.material_changes_count,
                    risk_level = EXCLUDED.risk_level
                """,
                {
                    "did": res.diff_id,
                    "doc_id": res.document_id,
                    "svid": res.source_version_id,
                    "tvid": res.target_version_id,
                    "lex": json.dumps(res.lexical_redline),
                    "sem": json.dumps(res.material_changes),
                    "count": res.material_changes_count,
                    "risk": res.overall_risk_level,
                },
            )
            conn.commit()

    return res
