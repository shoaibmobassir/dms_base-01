"""Assistant tools backed by the Ask-the-Firm knowledge layer (app.km).

These give the drafting/review agent the firm's structured memory — which
matter a description refers to, the matter record and team, who in the firm
knows a subject, and a cited KM answer — without the agent having to guess
search strings. Every documents these tools surface are registered in the
chat-local index so the agent can read and cite them with doc-N labels.
All reads apply the ethical-wall ACL for ``member_id``.
"""
from __future__ import annotations

import re
from typing import Any

from app.chat.tools.document_tools import DocEntry, DocIndex
from app.km import directory
from app.km.answer import ask_the_firm
from app.km.resolver import resolve_matter as km_resolve_matter
from app.km.scope import resolve_scope, resolve_scope_value

_DOC_ID_RE = re.compile(r"\bDOC-(?:\d+|[0-9A-F]{8,})\b", re.I)


def _register(doc_index: DocIndex, document_id: str, filename: str) -> str:
    for slug, entry in doc_index.items():
        if entry.document_id == document_id:
            return slug
    n = len(doc_index)
    while f"doc-{n}" in doc_index:
        n += 1
    slug = f"doc-{n}"
    doc_index[slug] = DocEntry(doc_id=slug, document_id=document_id, filename=filename or document_id)
    return slug


def _slugify_ids(text: str, doc_index: DocIndex) -> str:
    """Replace DMS document ids in KM prose with document names the agent can relate to doc-N."""
    by_id = {e.document_id.upper(): e.filename for e in doc_index.values()}
    return _DOC_ID_RE.sub(lambda m: f"“{by_id.get(m.group(0).upper(), m.group(0))}”", text or "")


def _matter_brief(m: dict) -> dict[str, Any]:
    return {k: m.get(k) for k in ("matter_id", "matter_code", "title", "client_name", "opposing_party", "practice_area", "status")}


def resolve_matter_tool(query: str, conn: Any, member_id: str | None) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"error": "Describe the matter (parties, subject, code or title)."}
    sc = resolve_scope(conn, q, None, member_id)
    if sc.matters:
        return {
            "status": "resolved",
            "method": sc.method,
            "matters": [m.to_dict() for m in sc.matters[:5]],
            "event": {"type": "matter_resolution", "query": q, "count": len(sc.matters)},
        }
    by_title = resolve_scope_value(conn, "matter", q, member_id)
    if by_title.matters and by_title.method == "title" and by_title.matters[0].score >= 0.6:
        return {"status": "resolved", "method": "title", "matters": [by_title.matters[0].to_dict()],
                "event": {"type": "matter_resolution", "query": q, "count": 1}}
    res = km_resolve_matter(conn, q, member_id)
    status = "resolved" if res.resolved else ("ambiguous" if res.method == "ambiguous" else "no_clear_match")
    return {
        "status": status,
        "method": res.method,
        "matters": [_matter_brief(c) | {"confidence": c["score"]} for c in (res.resolved or res.candidates[:5])],
        "note": None if res.resolved else "No single matter clearly matches; ask the user or check the candidates.",
        "event": {"type": "matter_resolution", "query": q, "count": len(res.resolved or res.candidates[:5])},
    }


def get_matter_profile_tool(matter: str, doc_index: DocIndex, conn: Any, member_id: str | None) -> dict[str, Any]:
    ref = (matter or "").strip()
    if not ref:
        return {"error": "Give a matter code, id or title."}
    sc = resolve_scope_value(conn, "matter", ref, member_id)
    if not sc.matters:
        return {"error": f"No accessible matter matches “{ref}”."}
    cards = directory.matter_cards(conn, sc.matter_ids[:1], member_id, max_docs=40)
    if not cards:
        return {"error": f"No accessible matter matches “{ref}”."}
    card = cards[0]
    docs = []
    for d in card.get("documents") or []:
        slug = _register(doc_index, str(d["document_id"]), str(d["title"]))
        docs.append({"doc_id": slug, "filename": d["title"], "document_type": d.get("document_type"),
                     "doc_date": str(d["doc_date"]) if d.get("doc_date") else None, "author": d.get("author_name")})
    return {
        "matter": {
            **_matter_brief(card),
            **{k: (str(card[k]) if card.get(k) is not None else None) for k in ("court", "jurisdiction", "opened_date", "closed_date", "claim_amount", "outcome", "matter_type")},
            "facts": card.get("facts") or [],
            "legal_issues": card.get("legal_issues") or [],
        },
        "team": card.get("team") or [],
        "documents": docs,
        "document_count": card.get("document_count"),
        "open_deadlines": [{**d, "due_date": str(d["due_date"])} for d in card.get("deadlines") or []],
        "event": {"type": "matter_profile", "matter_code": card["matter_code"], "title": card["title"]},
    }


def find_people_tool(query: str, matter: str | None, conn: Any, member_id: str | None) -> dict[str, Any]:
    if matter:
        sc = resolve_scope_value(conn, "matter", matter, member_id)
        if not sc.matters:
            return {"error": f"No accessible matter matches “{matter}”."}
        cards = directory.matter_cards(conn, sc.matter_ids[:1], member_id, max_docs=1)
        team = cards[0]["team"] if cards else []
        return {"matter": sc.matters[0].to_dict(), "people": team,
                "event": {"type": "people_results", "count": len(team)}}
    people = directory.people_search(conn, query or "", member_id)
    return {"query": query, "people": people, "event": {"type": "people_results", "count": len(people)}}


def ask_firm_tool(
    question: str,
    scope: str | None,
    doc_index: DocIndex,
    conn: Any,
    member_id: str | None,
) -> dict[str, Any]:
    q = (question or "").strip()
    if not q:
        return {"error": "Question is empty."}
    scope_arg = {"type": "auto", "value": scope} if scope else None
    result = ask_the_firm(conn, q, member_id, scope_arg)
    if scope and result.get("reason") == "scope_not_found":
        # The model's scope is often a description ("Acme Series B"), not a code or
        # exact title: let the matter resolver read it as part of the question.
        result = ask_the_firm(conn, f"{q} (regarding {scope})", member_id, None)
    passages = []
    for h in result.get("hits") or []:
        slug = _register(doc_index, str(h["document_id"]), str(h.get("title") or h["document_id"]))
        passages.append({
            "doc_id": slug, "filename": h.get("title"), "page": h.get("page_number"),
            "matter_code": h.get("matter_code"), "text": " ".join(str(h.get("text") or "").split())[:900],
        })
    for card in result.get("matter_cards") or []:
        for d in card.get("documents") or []:
            _register(doc_index, str(d["document_id"]), str(d["title"]))
    return {
        "status": result.get("status") or ("no_evidence" if result.get("abstained") else "answered"),
        "key_finding": _slugify_ids(result.get("key_finding") or "", doc_index),
        "draft_answer": _slugify_ids(result.get("answer") or "", doc_index),
        "resolved_scope": (result.get("resolved_scope") or {}).get("label"),
        "matters": [
            {k: c.get(k) for k in ("matter_id", "matter_code", "title", "client_name", "opposing_party", "status", "facts", "team")}
            for c in (result.get("matter_cards") or [])[:8]
        ],
        "people": result.get("people") or [],
        "passages": passages,
        "note": "Cite documents from `passages` with their doc-N label and a verbatim quote; matter and people facts come from firm records.",
        "event": {"type": "firm_answer", "question": q, "count": len(passages)},
    }
