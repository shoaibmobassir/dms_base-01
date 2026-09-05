"""P5.6-C7 — Proposition + evidence-first retrieval (schema).

Documents are containers of evidence. The primary retrieval unit is an
evidence-bearing passage scored against a legal proposition.

Does not enable production flags, CE document ranking, or GraphRAG.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

EvidenceRelation = Literal[
    "SUPPORTS",
    "CONTRADICTS",
    "QUALIFIES",
    "DEFINES",
    "REFERENCES",
]

EVIDENCE_RELATIONS: tuple[str, ...] = (
    "SUPPORTS",
    "CONTRADICTS",
    "QUALIFIES",
    "DEFINES",
    "REFERENCES",
)


@dataclass
class Proposition:
    """Atomic legal claim the review must establish or refute."""

    id: str
    claim: str
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    qualifiers: list[str] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    lexical_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def retrieval_text(self) -> str:
        """Text used for lexical/semantic evidence matching."""
        parts = [self.claim]
        if self.subject:
            parts.append(self.subject)
        if self.predicate:
            parts.append(self.predicate)
        if self.object:
            parts.append(self.object)
        if self.qualifiers:
            parts.extend(self.qualifiers)
        if self.lexical_terms:
            parts.extend(self.lexical_terms)
        return " ".join(p for p in parts if p)


@dataclass
class QueryPropositions:
    query_id: str
    query: str
    theme_hints: list[str] = field(default_factory=list)
    role_families: list[str] = field(default_factory=list)
    propositions: list[Proposition] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "query": self.query,
            "theme_hints": self.theme_hints,
            "role_families": self.role_families,
            "propositions": [p.to_dict() for p in self.propositions],
        }


@dataclass
class EvidenceSpan:
    """Passage that relates to a proposition (retrieval / gold unit)."""

    evidence_id: str
    document_id: str
    chunk_id: str
    matter_id: str | None = None
    proposition_id: str | None = None
    relationship: str = "SUPPORTS"
    quoted_text: str = ""
    start_offset: int | None = None
    end_offset: int | None = None
    score: float = 0.0
    channel: str = ""
    document_type: str | None = None
    title: str | None = None
    role_family: str | None = None
    annotation_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def proposition_from_dict(d: dict[str, Any]) -> Proposition:
    return Proposition(
        id=str(d["id"]),
        claim=str(d["claim"]),
        subject=d.get("subject"),
        predicate=d.get("predicate"),
        object=d.get("object"),
        qualifiers=list(d.get("qualifiers") or []),
        required_evidence=list(d.get("required_evidence") or []),
        lexical_terms=list(d.get("lexical_terms") or []),
    )


def query_propositions_from_dict(d: dict[str, Any]) -> QueryPropositions:
    return QueryPropositions(
        query_id=str(d["query_id"]),
        query=str(d.get("query") or d.get("question") or ""),
        theme_hints=list(d.get("theme_hints") or []),
        role_families=list(d.get("role_families") or []),
        propositions=[proposition_from_dict(p) for p in (d.get("propositions") or [])],
    )


def format_proposition_context(
    prop: Proposition,
    *,
    theme: str | None = None,
    role_family: str | None = None,
    section_title: str | None = None,
    document_type: str | None = None,
    chunk_text: str,
) -> str:
    """Contextual embedding input: proposition-conditioned passage."""
    parts = [f"[LEGAL PROPOSITION]\n{prop.claim}"]
    if theme:
        parts.append(f"[THEME]\n{theme}")
    if role_family:
        parts.append(f"[ROLE FAMILY]\n{role_family}")
    if document_type:
        parts.append(f"[DOCUMENT TYPE]\n{document_type}")
    if section_title:
        parts.append(f"[SECTION]\n{section_title}")
    parts.append(f"[TEXT]\n{(chunk_text or '').strip()}")
    return "\n\n".join(parts)
