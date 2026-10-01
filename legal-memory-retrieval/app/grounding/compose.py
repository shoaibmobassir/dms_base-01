"""Rewrite an answer so that what the lawyer reads matches what the sources support.

Given the answer prose and per-unit verdicts from ``verify.verify_claims``:

  supported   → kept; its citation markers are replaced by fresh [n] markers whose
                citations carry the verified spans (exact quotes + char offsets)
  partial     → kept, marked, and cited to what does support it ("support": "partial")
  unsupported → removed from the text and listed in the grounding report
  non_claim   → kept as written

Sources keyed as firm records (matter cards, people) support a sentence without a document
citation; the sentence keeps any MTR/MEM reference it already had.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.grounding.verify import CONTRADICTED, PARTIAL, SUPPORTED, Claim, Source, Span, check_absences, verify_claims, verify_consensus

_MARKER = re.compile(r"\s*\[(\d{1,3})\]")
_DOC_GROUP = re.compile(r"\s*[(\[]\s*(?:DOC-[0-9A-F]{3,}|MTR-\d{4}-\d+|MEM-\d+)(?:\s*[,;]\s*(?:DOC-[0-9A-F]{3,}|MTR-\d{4}-\d+|MEM-\d+))*\s*[)\]]", re.I)
_EVIDENCE_ID = re.compile(r"\b(DOC-[0-9A-F]{3,}|MTR-\d{4}-\d+|MEM-\d+)\b", re.I)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\[A-Z(\"'])")
_ABBREV_END = re.compile(
    r"\b(?:v|vs|No|Nos|Ltd|Pvt|Rs|Co|Corp|Inc|Art|Arts|Reg|Regs|Sec|Cl|para|paras|p|pp|Mr|Ms|Dr|Anr|Ors|viz|i\.e|e\.g|etc|S)\.$",
    re.I,
)
_LEAD_REF = re.compile(r"^(?:\s*(?:\[\d+\]|\((?:[^()]*(?:DOC|MTR|MEM)-[^()]*)\)))+")
_BULLET = re.compile(r"^(\s*(?:[-*•]|\d+[.)])\s+)")

RECORD_PREFIXES = ("MTR-", "MEM-", "record:")


@dataclass
class Unit:
    line: int
    start: int          # offset of the unit inside its line
    end: int
    text: str
    refs: list[str]     # citation refs ([n] numbers or evidence ids) found in the unit


@dataclass
class Grounded:
    text: str
    citations: list[dict[str, Any]]
    claims: list[Claim]
    removed: list[dict[str, str]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    def report(self) -> dict[str, Any]:
        claims = [c for c in self.claims if c.kind == "claim"]
        return {
            "claims": [
                {"text": c.text, "support": c.support,
                 "spans": [{"key": sp.key, "title": sp.title, "quote": sp.quote} for sp in c.spans[:3]]}
                for c in claims if c.support in (SUPPORTED, PARTIAL)
            ],
            "checked": len(claims),
            "supported": sum(1 for c in claims if c.support == SUPPORTED),
            "partial": sum(1 for c in claims if c.support == PARTIAL),
            "contradicted": sum(1 for c in claims if c.support == CONTRADICTED),
            "removed": len(self.removed),
            "removed_statements": self.removed,
        }


def _pieces(line: str) -> list[tuple[int, int]]:
    """Sentence ranges inside one markdown line (list prefix and table rows kept whole)."""
    body_start = 0
    m = _BULLET.match(line)
    if m:
        body_start = m.end()
    if line.lstrip().startswith("|"):
        return [(0, len(line))]
    ranges: list[tuple[int, int]] = []
    pos = body_start
    for m in _SENT_SPLIT.finditer(line, body_start):
        if _ABBREV_END.search(line[pos:m.start()].rstrip()):
            continue
        ranges.append((pos, m.start()))
        pos = m.end()
    ranges.append((pos, len(line)))
    # "…ends here. [2] Next": pull a leading marker back into the previous sentence.
    fixed: list[tuple[int, int]] = []
    for s, e in ranges:
        lead = _LEAD_REF.match(line[s:e])
        if lead and fixed:
            ps, _ = fixed[-1]
            fixed[-1] = (ps, s + lead.end())
            s = s + lead.end()
            while s < e and line[s] == " ":
                s += 1
        if e > s:
            fixed.append((s, e))
    return fixed


def split(text: str, ref_style: str) -> list[Unit]:
    units: list[Unit] = []
    for li, line in enumerate(text.split("\n")):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or re.fullmatch(r"[|\-:\s]+", stripped):
            continue
        if stripped.startswith("<CITATIONS>"):
            break
        for s, e in _pieces(line):
            chunk = line[s:e]
            if len(re.sub(r"[\W_]+", " ", chunk).split()) < 2:
                continue
            refs = (_MARKER.findall(chunk) if ref_style == "markers"
                    else [m.upper() for m in _EVIDENCE_ID.findall(chunk)])
            units.append(Unit(li, s, e, chunk, refs))
    return units


def _strip_doc_ids(text: str) -> str:
    """Drop DOC ids (unverified document pointers) but keep MTR/MEM record references."""
    def keep_records(m: re.Match[str]) -> str:
        ids = [i.upper() for i in _EVIDENCE_ID.findall(m.group(0)) if not i.upper().startswith("DOC-")]
        return f" ({', '.join(ids)})" if ids else ""
    return re.sub(r"  +", " ", _DOC_GROUP.sub(keep_records, text)).strip()


def _strip_refs(text: str, ref_style: str) -> str:
    text = _MARKER.sub("", text) if ref_style == "markers" else _DOC_GROUP.sub("", text)
    return text.replace("**", "").strip()


def _place(text: str, marks: str) -> str:
    """Put markers before the unit's closing punctuation: "… 2026 [3]."."""
    if not marks:
        return text
    m = re.search(r"([.;:!?]+[\"')\]]*\s*)$", text)
    if m:
        return f"{text[:m.start()].rstrip()} {marks}{m.group(1)}"
    return f"{text.rstrip()} {marks}"


def _mark_suggestion_lists(text: str, units: list[Unit], claims: list[Claim]) -> None:
    """List items under a lead-in like "would typically be found in:" are pointers, not claims."""
    from app.grounding.verify import _SUGGESTION

    lines = text.split("\n")
    lead: str | None = None
    for li, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _BULLET.match(line):
            if lead is not None:
                for u, c in zip(units, claims):
                    if u.line == li:
                        c.under_suggestion = True
            continue
        lead = stripped if stripped.endswith(":") and _SUGGESTION.search(stripped) else None


def _drop_orphan_lead_ins(lines: list[str | None], emptied: set[int]) -> None:
    """Remove "X includes:" when every list line under it was removed."""
    for i, line in enumerate(lines):
        if line is None or not line.rstrip().endswith(":"):
            continue
        j = i + 1
        while j < len(lines) and lines[j] is not None and not lines[j].strip():
            j += 1
        block = []
        while j < len(lines) and (lines[j] is None or _BULLET.match(lines[j] or "")):
            block.append(j)
            j += 1
        if block and all(k in emptied for k in block):
            lines[i] = None


def ground_answer(
    text: str,
    *,
    ref_style: str,
    cited_keys: Callable[[Unit], list[str]],
    offered_quotes: Callable[[Unit], list[str]],
    sources: list[Source],
    llm: Callable[[list[dict[str, str]]], str] | list[Callable[[list[dict[str, str]]], str]],
    removed_note: bool = True,
    empty_message: str | None = "The documents and records available to you do not contain a supported answer to this question.",
    full_sources: list[Source] | None = None,
) -> Grounded:
    """Verify every unit of ``text`` and rebuild it with span-level citations.

    ``ref_style`` is "markers" for [n] citations (Assistant) or "ids" for inline
    DOC/MTR/MEM ids (Ask the Firm). ``cited_keys``/``offered_quotes`` map a unit's
    references to source keys and to the quotes the generator offered for them.
    """
    units = split(text, ref_style)
    claims = [
        Claim(text=_strip_refs(u.text, ref_style), cited=cited_keys(u), quotes=offered_quotes(u))
        for u in units
    ]
    _mark_suggestion_lists(text, units, claims)
    llms = llm if isinstance(llm, list) else [llm]
    t = time.perf_counter()
    verify_consensus(claims, sources, llms)
    verify_ms = (time.perf_counter() - t) * 1000
    # "X is not in the documents" is checked against whole documents, not only retrieved passages.
    t = time.perf_counter()
    check_absences(claims, full_sources if full_sources is not None else sources, llms[0])
    timings = {"units": len(claims), "verify_ms": round(verify_ms, 1),
               "absence_ms": round((time.perf_counter() - t) * 1000, 1)}

    lines = text.split("\n")
    edits: dict[int, list[tuple[int, int, str]]] = {}
    citations: list[dict[str, Any]] = []
    removed: list[dict[str, str]] = []
    ref_for: dict[tuple[str, int, int], int] = {}

    def cite(span_group: list[Span], support: str) -> int:
        key = (span_group[0].key, span_group[0].start, span_group[-1].end)
        if key in ref_for:
            return ref_for[key]
        n = len(citations) + 1
        head = span_group[0]
        citations.append({
            "ref": n, "doc_id": head.key, "document_id": head.document_id, "title": head.title,
            "chunk_id": head.chunk_id, "page": head.page, "quote": span_group[0].quote,
            "quotes": [
                {"page": sp.page, "quote": sp.quote,
                 "verification": {"verified": True, "start_char": sp.start, "end_char": sp.end}}
                for sp in span_group
            ],
            "verified": True, "support": support,
        })
        ref_for[key] = n
        return n

    for u, c in zip(units, claims):
        if c.kind in ("non_claim", "absence"):
            # Keep as written but never leave an unverified citation marker behind.
            if u.refs:
                kept = _strip_refs(u.text, "markers") if ref_style == "markers" else _strip_doc_ids(u.text)
                edits.setdefault(u.line, []).append((u.start, u.end, kept))
            continue
        if c.support in (SUPPORTED, PARTIAL):
            doc_spans: dict[str, list[Span]] = {}
            record_ids: list[str] = []
            for sp in c.spans:
                if sp.key.startswith(RECORD_PREFIXES):
                    if sp.key.upper() not in record_ids and not sp.key.startswith("record:"):
                        record_ids.append(sp.key.upper())
                else:
                    doc_spans.setdefault(sp.key, []).append(sp)
            marks = " ".join(f"[{cite(v[:3], c.support)}]" for v in doc_spans.values())
            if ref_style == "ids" and record_ids:
                marks = (marks + " " if marks else "") + "(" + ", ".join(record_ids) + ")"
            body = _strip_refs(u.text, ref_style)
            edits.setdefault(u.line, []).append((u.start, u.end, _place(body, marks)))
        else:
            removed.append({"text": c.text, "verdict": c.support or "unsupported", "reason": c.reason})
            edits.setdefault(u.line, []).append((u.start, u.end, ""))

    emptied: set[int] = set()
    for li, changes in edits.items():
        line = lines[li]
        for s, e, new in sorted(changes, key=lambda t: -t[0]):
            line = line[:s] + new + line[e:]
        if not _BULLET.sub("", line).strip(" |"):
            line = None  # the whole line was removed
            emptied.add(li)
        else:
            line = re.sub(r"  +", " ", line).rstrip()
        lines[li] = line
    _drop_orphan_lead_ins(lines, emptied)

    out = "\n".join(l for l in lines if l is not None)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    claims_kept = [c for c in claims if c.kind == "claim" and c.support in (SUPPORTED, PARTIAL)]
    if not claims_kept and any(c.kind == "claim" for c in claims):
        if not out.strip() and empty_message:
            out = empty_message
    if removed and removed_note:
        noun = "statement" if len(removed) == 1 else "statements"
        out += f"\n\n_{len(removed)} {noun} removed because the cited sources did not support {'it' if len(removed) == 1 else 'them'}._"
    return Grounded(text=out, citations=citations, claims=claims, removed=removed, timings=timings)
