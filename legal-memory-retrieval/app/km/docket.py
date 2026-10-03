"""Pin an Ask-the-Firm question to a proceeding number before stem resolution.

Lawyers name appeals and petitions as phrases ("Appeal No. 163 of 2018"), not as
bags of stems. Matching the phrase against matter titles stops a copy of the same
filing on another matter from widening the evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from app.km.scope import ACL_SQL, DOC_SQL, MatterRef, _fetch, _refs

# Appeal No. 163 of 2018 | APL. 163 of 2018 | Appeal 163/2018 | Civil Appeal 10046 of 2025
_APPEAL_RE = re.compile(
    r"\b(?P<civil>civil\s+)?(?P<kind>appeal|apl)\.?\s*(?:no\.?\s*)?"
    r"(?P<num>\d{1,6})\s*(?:of\s+|/\s*)(?P<year>19\d{2}|20\d{2})\b",
    re.I,
)
# Petition No. 310/MP/2026 | Petition 1/MP/2017
_PETITION_RE = re.compile(
    r"\bpetition\s*(?:no\.?\s*)?(?P<num>\d{1,6})\s*/\s*(?P<forum>[A-Z]{2,6})\s*/\s*(?P<year>19\d{2}|20\d{2})\b",
    re.I,
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


@dataclass(frozen=True)
class DocketRef:
    kind: str  # appeal | civil_appeal | petition
    number: str
    year: str
    raw: str
    forum: str | None = None

    @property
    def label(self) -> str:
        if self.kind == "petition":
            return f"Petition {self.number}/{self.forum}/{self.year}"
        if self.kind == "civil_appeal":
            return f"Civil Appeal {self.number} of {self.year}"
        return f"Appeal {self.number} of {self.year}"

    def phrases(self) -> list[str]:
        """Normalised phrases that identify this proceeding in a title."""
        n, y = self.number, self.year
        if self.kind == "petition":
            forum = (self.forum or "").lower()
            return [
                f"petition {n} {forum} {y}",
                f"{n} {forum} {y}",
            ]
        out = [
            f"appeal {n} of {y}",
            f"apl {n} of {y}",
            f"apl {n} {y}",
            f"appeal {n} {y}",
        ]
        if self.kind == "civil_appeal":
            out.insert(0, f"civil appeal {n} of {y}")
        return out


def parse_docket(text: str) -> DocketRef | None:
    """Extract the first appeal / petition number from ``text``, if any."""
    raw = text or ""
    m = _PETITION_RE.search(raw)
    if m:
        return DocketRef(
            kind="petition",
            number=m.group("num"),
            year=m.group("year"),
            forum=m.group("forum").upper(),
            raw=m.group(0),
        )
    m = _APPEAL_RE.search(raw)
    if m:
        kind = "civil_appeal" if m.group("civil") else "appeal"
        return DocketRef(
            kind=kind,
            number=m.group("num"),
            year=m.group("year"),
            raw=m.group(0),
        )
    return None


def title_contains_docket(title: str, docket: DocketRef) -> bool:
    n = _norm(title)
    return any(p in n for p in docket.phrases())


def _sql_norm(expr: str) -> str:
    return f"regexp_replace(lower({expr}), '[^a-z0-9]+', ' ', 'g')"


def matters_with_docket_in_title(
    conn, docket: DocketRef, member_id: str | None, *, limit: int = 5,
) -> list[MatterRef]:
    """Accessible matters whose title contains the proceeding phrase."""
    phrases = docket.phrases()
    rows = _fetch(
        conn,
        f"""
        SELECT m.matter_id, m.matter_code, m.title, cl.name AS client_name, m.opposing_party,
               m.practice_area, m.status, m.jurisdiction, m.court
        FROM matters m
        JOIN clients cl ON cl.client_id = m.client_id
        JOIN permissions p ON p.matter_id = m.matter_id
        WHERE {ACL_SQL}
          AND {_sql_norm("m.title")} LIKE ANY(%(patterns)s)
        ORDER BY m.matter_id
        LIMIT %(limit)s
        """,
        {
            "member_id": member_id,
            "patterns": [f"%{p}%" for p in phrases],
            "limit": limit,
        },
    )
    # Phrase list can over-match ("310 mp 2026"); keep exact phrase hits.
    hits = [r for r in rows if title_contains_docket(str(r.get("title") or ""), docket)]
    return _refs(hits[:limit], "docket")


def matters_with_docket_in_doc_titles(
    conn, docket: DocketRef, member_id: str | None, *, limit: int = 10,
) -> list[MatterRef]:
    """Accessible matters that hold a document whose title contains the proceeding."""
    phrases = docket.phrases()
    rows = _fetch(
        conn,
        f"""
        SELECT DISTINCT ON (m.matter_id)
               m.matter_id, m.matter_code, m.title, cl.name AS client_name, m.opposing_party,
               m.practice_area, m.status, m.jurisdiction, m.court, d.title AS hit_doc_title
        FROM documents d
        JOIN matters m ON m.matter_id = d.matter_id
        JOIN clients cl ON cl.client_id = m.client_id
        JOIN permissions p ON p.matter_id = m.matter_id
        WHERE {ACL_SQL} AND {DOC_SQL}
          AND {_sql_norm("d.title")} LIKE ANY(%(patterns)s)
        ORDER BY m.matter_id, d.document_id
        LIMIT %(limit)s
        """,
        {
            "member_id": member_id,
            "patterns": [f"%{p}%" for p in phrases],
            "limit": max(limit * 3, 10),
        },
    )
    hits = [r for r in rows if title_contains_docket(str(r.get("hit_doc_title") or ""), docket)]
    return _refs(hits[:limit], "docket_doc")


def pin_docket(
    conn, question: str, member_id: str | None,
) -> tuple[list[MatterRef], list[MatterRef], DocketRef | None]:
    """Resolve a docket phrase to title-matched matters and document-only copies.

    Returns ``(title_matters, copy_matters, docket)``. Callers pin to the first
    title matter when present; copy matters are for a note, never for evidence.
    """
    docket = parse_docket(question)
    if docket is None:
        return [], [], None
    titled = matters_with_docket_in_title(conn, docket, member_id)
    docs = matters_with_docket_in_doc_titles(conn, docket, member_id)
    titled_ids = {m.matter_id for m in titled}
    copies = [m for m in docs if m.matter_id not in titled_ids]
    return titled, copies, docket


def docket_scope_note(docket: DocketRef, pinned: MatterRef, copies: list[MatterRef]) -> str:
    """Instruction for the answer model once a proceeding is pinned."""
    lines = [
        f"The user named proceeding {docket.label}. It is pinned to matter "
        f"{pinned.matter_code} ({pinned.matter_id}, client {pinned.client_name or 'unknown'}).",
        "Answer from this matter's records only.",
        "If the stored document title differs from the words in the question "
        "(for example 'submissions' vs 'arguments'), say so in one sentence.",
        "Do not repeat the key finding as the first paragraph of the answer.",
    ]
    if copies:
        listed = ", ".join(f"{c.matter_code} ({c.title})" for c in copies[:5])
        lines.append(
            f"Copies of filings for this proceeding also sit on: {listed}. "
            "Do not treat those matters as this appeal or cite them as the appeal."
        )
    return "\n".join(lines) + "\n"
