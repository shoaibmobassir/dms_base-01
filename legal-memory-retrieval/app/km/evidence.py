"""Render firm records and passages as citable evidence blocks for the LLM.

Every block is headed by the id the model must cite: matters by MTR id,
people by MEM id, passages by DOC id.
"""
from __future__ import annotations

import re
from typing import Any

EVIDENCE_ID_RE = re.compile(r"\b(DOC-[0-9A-F]{3,}|MTR-\d{4}-\d+|MEM-\d+)\b", re.I)


def evidence_ids(text: str) -> list[str]:
    seen: list[str] = []
    for m in EVIDENCE_ID_RE.findall(text or ""):
        up = m.upper()
        if up not in seen:
            seen.append(up)
    return seen


def _d(value: Any) -> str:
    return "" if value is None else str(value)


def matter_block(card: dict, *, compact: bool = False) -> str:
    lines = [f"[{card['matter_id']}] MATTER RECORD — {card['title']}"]
    lines.append(
        f"Code: {card['matter_code']} | Client: {_d(card.get('client_name'))} | "
        f"Counterparty: {_d(card.get('opposing_party')) or 'n/a'} | Practice: {_d(card.get('practice_area'))} | "
        f"Status: {_d(card.get('status'))}"
    )
    if not compact:
        extra = [
            ("Matter type", card.get("matter_type")), ("Forum", card.get("court")),
            ("Jurisdiction", card.get("jurisdiction")), ("Office", card.get("office")),
            ("Opened", card.get("opened_date")), ("Closed", card.get("closed_date")),
            ("Claim amount", card.get("claim_amount")), ("Outcome", card.get("outcome")),
        ]
        shown = " | ".join(f"{k}: {v}" for k, v in extra if v)
        if shown:
            lines.append(shown)
    facts = card.get("facts") or []
    if facts:
        lines.append("Facts:" + "".join(f"\n  - {f}" for f in facts[: (3 if compact else 12)]))
    issues = card.get("legal_issues") or []
    if issues:
        lines.append("Legal issues: " + "; ".join(issues[: (3 if compact else 10)]))
    team = card.get("team") or []
    if team:
        lines.append(
            "Team: " + "; ".join(
                f"{t['name']} [{t['member_id']}] ({t['role']}{', ' + t['role_on_matter'] if t.get('role_on_matter') else ''})"
                for t in team
            )
        )
    docs = card.get("documents") or []
    if docs and not compact:
        n = card.get("document_count") or len(docs)
        lines.append(
            f"Documents ({n}): " + "; ".join(
                f"{d['document_id']} {d['title']}"
                + (f" ({d['document_type']}" + (f", {d['doc_date']}" if d.get("doc_date") else "") + ")" if d.get("document_type") else "")
                for d in docs[:15]
            )
        )
    deadlines = card.get("deadlines") or []
    if deadlines and not compact:
        lines.append("Open deadlines: " + "; ".join(f"{d['due_date']} {d['title']} ({d['kind']})" for d in deadlines[:6]))
    return "\n".join(lines)


def person_block(p: dict) -> str:
    lines = [f"[{p['member_id']}] PERSON — {p['name']}, {p['role']}" + (f", {p['office']} office" if p.get("office") else "")]
    if p.get("practice_areas"):
        lines.append("Practice areas: " + ", ".join(p["practice_areas"]))
    if p.get("specializations"):
        lines.append("Specialisations: " + ", ".join(p["specializations"]))
    if p.get("matters"):
        lines.append(
            f"Matters ({p.get('matter_count', len(p['matters']))} total, most relevant): " + "; ".join(
                f"{m['matter_code']} {m['title']}" + (f" ({m['role_on_matter']})" if m.get("role_on_matter") else "")
                for m in p["matters"]
            )
        )
    return "\n".join(lines)


def passage_block(h: dict, *, max_chars: int = 1500) -> str:
    where = f" · p.{h['page_number']}" if h.get("page_number") else ""
    sect = f" · {h['section_title']}" if h.get("section_title") else ""
    head = (
        f"[{str(h['document_id']).upper()}{where}] {h.get('title') or ''}{sect} — "
        f"{h.get('document_type') or ''} | Matter {h.get('matter_code') or h.get('matter_id')}"
        + (f" | Client: {h['client_name']}" if h.get("client_name") else "")
        + (f" | Dated {h['doc_date']}" if h.get("doc_date") else "")
    )
    text = " ".join(str(h.get("text") or "").split())[:max_chars]
    return f"{head}\n{text}"


def pack(
    cards: list[dict],
    people: list[dict],
    passages: list[dict],
    candidates: list[dict],
    *,
    compact_cards: bool = False,
    budget_chars: int = 24000,
) -> tuple[str, set[str]]:
    blocks: list[str] = []
    allowed: set[str] = set()
    used = 0

    def add(block: str, ident: str) -> bool:
        nonlocal used
        if used + len(block) > budget_chars and blocks:
            return False
        blocks.append(block)
        allowed.add(ident.upper())
        used += len(block) + 2
        return True

    for c in cards:
        add(matter_block(c, compact=compact_cards), c["matter_id"])
        for t in c.get("team") or []:
            allowed.add(t["member_id"].upper())
        for d in c.get("documents") or []:
            allowed.add(str(d["document_id"]).upper())
    for p in people:
        add(person_block(p), p["member_id"])
    for h in passages:
        if not add(passage_block(h), str(h["document_id"])):
            break
    if candidates:
        lines = ["CANDIDATE MATTERS (closest records by name/facts; may NOT be what was asked about):"]
        for c in candidates[:5]:
            lines.append(f"  [{c['matter_id']}] {c['matter_code']} — {c['title']} (client {c.get('client_name')}, counterparty {c.get('opposing_party') or 'n/a'})")
            allowed.add(c["matter_id"].upper())
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks), allowed
