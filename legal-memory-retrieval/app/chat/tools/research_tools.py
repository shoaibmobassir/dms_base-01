"""Assistant tools for legal research over authorities (design doc §22.5).

Authorities (PCIJ decisions, UN Security Council resolutions) are registered in
the chat-local index like documents, so the agent reads and cites them with
doc-N labels and the existing grounding checks every quote. Their text is stored
with [Page N] markers at the PDF page breaks, so pinpoints name a real page.

Every tool result carries the authority's binding label and reason, decided by
rules (app/research/legal_systems.yaml), never by the model.
"""
from __future__ import annotations

import re
from typing import Any

from app.chat.spotlight import spotlight
from app.chat.tools.document_tools import DocIndex, DocStore
from app.chat.tools.firm_tools import _register
from app.research import local_provider as lp
from app.research import structure
from app.research.citations import extract_citations
from app.research.legal_systems import Forum, forum_from_matter
from app.research.verify import verify_citations

READ_BUDGET_CHARS = 14_000
_SLUG = re.compile(r"^doc-\d+$")


def _forum(conn: Any, matter: dict[str, str] | None, arguments: dict[str, Any]) -> Forum:
    """The forum from the conversation's matter, unless the model names a legal system."""
    base = Forum()
    if matter and matter.get("matter_id") and conn is not None:
        rows = conn.execute("SELECT matter_id, jurisdiction, court FROM matters WHERE matter_id = %s",
                            (matter["matter_id"],)).fetchall()
        if rows:
            r = rows[0]
            base = forum_from_matter(r if isinstance(r, dict) else dict(zip(("matter_id", "jurisdiction", "court"), r)))
    system = str(arguments.get("legal_system") or "").strip().lower() or base.legal_system
    return Forum(legal_system=system, court=base.court, matter_id=base.matter_id)


def _authority_from_args(conn: Any, arguments: dict[str, Any], doc_index: DocIndex, member_id: str | None) -> dict | None:
    ref = str(arguments.get("authority") or arguments.get("doc_id") or arguments.get("authority_id") or "").strip()
    if not ref:
        return None
    if _SLUG.match(ref) and ref in doc_index:
        return lp.get(conn, doc_index[ref].document_id, member_id)
    if ref.upper().startswith(("LOCAL:", "DOC-")):
        return lp.get(conn, ref, member_id)
    cites = extract_citations(ref)
    if cites:
        res = lp.resolve(conn, cites[0], member_id)
        if res.get("authorities"):
            return res["authorities"][0]
    return None


def _slug_for(doc_index: DocIndex, a: dict[str, Any]) -> str:
    return _register(doc_index, a["document_id"], a["citation"]["primary"].replace("*", ""))


def _not_found(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"error": "Authority not found or not accessible. Give a doc-N label from search_authority, "
                     "or a citation such as 'S/RES/1373 (2001)' or 'PCIJ Series A No. 1'.",
            "authority": arguments.get("authority")}


def search_authority_tool(arguments: dict[str, Any], doc_index: DocIndex, doc_store: DocStore, conn: Any,
                          member_id: str | None, matter: dict[str, str] | None, nonce: str) -> tuple[dict, list]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        return {"error": "Search query is empty."}, []
    kinds = arguments.get("kinds") or None
    if isinstance(kinds, str):
        kinds = [kinds]
    forum = _forum(conn, matter, arguments)
    if forum.legal_system not in (None, "", "international"):
        coverage = (f"The forum's legal system is {forum.legal_system}; the firm's research collection holds "
                    "international law only (PCIJ decisions, UN Security Council resolutions). Results are "
                    "persuasive at most; say so, and say which sources for that system were not available.")
    else:
        coverage = "Searched the firm's PCIJ decisions and UN Security Council resolutions."
    hits = lp.search(conn, query, member_id, kinds=kinds, date_from=arguments.get("date_from"),
                     date_to=arguments.get("date_to"), limit=max(1, min(int(arguments.get("limit") or 6), 12)),
                     forum=forum)
    results = []
    for h in hits:
        a = {"document_id": h["document_id"], "citation": {"primary": h["citation"]}}
        slug = _slug_for(doc_index, a)
        results.append({"doc_id": slug, "citation": h["citation"], "kind": h["kind"], "date": h.get("decision_date"),
                        "role": (h.get("passage") or {}).get("role") or h.get("role"),
                        "para": (h.get("passage") or {}).get("para"), "page": (h.get("passage") or {}).get("page"),
                        "binding": h["binding"], "chapter_vii": h.get("chapter_vii"),
                        "snippet": spotlight(h["snippet"], nonce),
                        **({"cited_by_results": h["cited_by_results"]} if h.get("cited_by_results") else {})})
    return {
        "query": query, "count": len(results), "results": results, "coverage": coverage,
        "next": "Read the authorities you will rely on with read_authority before citing them.",
    }, [{"type": "authority_results", "query": query, "count": len(results),
         "citations": [r["citation"].replace("*", "") for r in results[:8]]}]


def read_authority_tool(arguments: dict[str, Any], doc_index: DocIndex, doc_store: DocStore, conn: Any,
                        member_id: str | None, matter: dict[str, str] | None, nonce: str) -> tuple[dict, list]:
    a = _authority_from_args(conn, arguments, doc_index, member_id)
    if not a:
        return _not_found(arguments), []
    body = lp.body(conn, a["authority_id"], member_id) or ""
    slug = _slug_for(doc_index, a)
    paged = lp.paged_body(lp.without_headnote(a, body))
    entry = doc_index[slug]
    entry.text = paged
    doc_store[slug] = paged  # grounding and quote checks read this text, with real PDF pages
    forum = _forum(conn, matter, arguments)
    segs = lp.passages(a, body)
    out: dict[str, Any] = {"doc_id": slug, "citation": a["citation"]["primary"], "kind": a["kind"],
                           "date": a.get("decision_date"), "court": a["court"]["name"]}

    if a["provider_kind"] == "unsc":
        want: set[int] = set()
        for lo, hi in re.findall(r"(\d+)\s*(?:-\s*(\d+))?", str(arguments.get("paras") or "")):
            want.update(range(int(lo), int(hi or lo) + 1))
        ops = [p for p in segs if p.role == "operative"]
        out["chapter_vii"] = a.get("chapter_vii")
        out["preamble"] = [" ".join(p.text.split())[:140] for p in segs if p.role == "preamble"][:30]
        if any(p.role == "headnote" for p in segs):
            out["headnote_note"] = "An editorial summary precedes the official text; it is not the Council's text and is omitted."
        paras, used = [], 0
        for p in ops:
            if want and p.para not in want:
                continue
            text = " ".join(p.text.split())
            if used + len(text) > READ_BUDGET_CHARS:
                out["truncated_after_para"] = p.para_label
                break
            used += len(text)
            paras.append({"para": p.para_label, "lead_verb": p.lead_verb,
                          "binding": lp.label(a, forum, p), "text": spotlight(text, nonce)})
        out["operative_paragraphs"] = paras
        out["operative_count"] = len(ops)
        out["cite_as"] = "Cite operative paragraphs with this doc_id, page 1, and a verbatim quote; name the paragraph number in prose."
    else:
        out["case_name"] = a.get("case_name")
        out["role"] = a.get("role")
        out["binding"] = lp.label(a, forum, segs[0] if segs else None)
        if a.get("judge"):
            out["judge"] = a["judge"]
        offs = structure.page_offsets(body)
        out["pages"] = len(offs)
        m = re.match(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*$", str(arguments.get("pages") or ""))
        first = int(m.group(1)) if m else int(arguments.get("cursor") or 1)
        last = int(m.group(2) or m.group(1)) if m else len(offs)
        chunks, used, page = [], 0, max(1, first)
        while page <= min(last, len(offs)):
            start = offs[page - 1]
            end = offs[page] if page < len(offs) else len(body)
            text = body[start:end].strip()
            if used and used + len(text) > READ_BUDGET_CHARS:
                break
            chunks.append(f"[Page {page}]\n{text}")
            used += len(text)
            page += 1
        out["text"] = spotlight("\n\n".join(chunks), nonce)
        out["complete"] = page > len(offs)
        if page <= min(last, len(offs)):
            out["next_cursor"] = page
        others = [p for p in segs if p.role != "majority"]
        if others:
            out["opinions_in_this_text"] = [{"role": p.role, "judge": p.extra.get("judge"), "page": p.page} for p in others]
        if a.get("role") != "majority":
            out["warning"] = "This is a judge's individual opinion, not the Court's decision. Do not cite it as the holding."
    return out, [{"type": "authority_read", "doc_id": slug, "citation": a["citation"]["primary"].replace("*", ""),
                  "filename": entry.filename}]


def resolve_citation_tool(arguments: dict[str, Any], doc_index: DocIndex, doc_store: DocStore, conn: Any,
                          member_id: str | None, matter: dict[str, str] | None, nonce: str) -> tuple[dict, list]:
    text = str(arguments.get("citation") or arguments.get("text") or "").strip()
    if not text:
        return {"error": "Give a citation string."}, []
    out = []
    for res in lp.resolve_text(conn, text, member_id)[:10]:
        row = {k: res.get(k) for k in ("citation", "resolution", "reason", "pinpoint")}
        if res.get("authorities"):
            row["matches"] = [{"doc_id": _slug_for(doc_index, a), "citation": a["citation"]["primary"], "role": a.get("role")}
                              for a in res["authorities"][:6]]
        out.append(row)
    if not out:
        return {"citation": text, "resolution": "unrecognized",
                "reason": "No citation form was recognized in this text."}, []
    return {"results": out}, []


def get_citing_authorities_tool(arguments: dict[str, Any], doc_index: DocIndex, doc_store: DocStore, conn: Any,
                                member_id: str | None, matter: dict[str, str] | None, nonce: str) -> tuple[dict, list]:
    a = _authority_from_args(conn, arguments, doc_index, member_id)
    if not a:
        return _not_found(arguments), []
    res = lp.citing(conn, a["authority_id"], member_id, limit=max(1, min(int(arguments.get("limit") or 15), 40)))
    for c in res.get("citing", []):
        c["doc_id"] = _register(doc_index, c.pop("document_id"), str(c["citation"]))
        c.pop("authority_id", None)
        c["context"] = spotlight(c.get("context") or "", nonce)
    return res, [{"type": "authority_status", "citation": a["citation"]["primary"].replace("*", ""),
                  "display": f"{res.get('count', 0)} later citing authorities"}]


def check_authority_status_tool(arguments: dict[str, Any], doc_index: DocIndex, doc_store: DocStore, conn: Any,
                                member_id: str | None, matter: dict[str, str] | None, nonce: str) -> tuple[dict, list]:
    a = _authority_from_args(conn, arguments, doc_index, member_id)
    if not a:
        return _not_found(arguments), []
    res = lp.status(conn, a["authority_id"], member_id, as_of=arguments.get("as_of") or None)
    for s in res.get("status", {}).get("signals", []):
        if s.get("by"):
            s["doc_id"] = _register(doc_index, lp.document_id_of(s.pop("by")), str(s.get("citation") or ""))
    res["rule"] = "Say 'status not verified' when the signal is unknown. Never call an authority good law."
    return res, [{"type": "authority_status", "citation": a["citation"]["primary"].replace("*", ""), "display": res["display"]}]


def verify_citations_tool(arguments: dict[str, Any], doc_index: DocIndex, doc_store: DocStore, conn: Any,
                          member_id: str | None, matter: dict[str, str] | None, nonce: str) -> tuple[dict, list]:
    text = str(arguments.get("text") or "")
    if not text.strip() and arguments.get("doc_id") in doc_index:
        from app.chat.tools.document_tools import resolve_document_text

        text = resolve_document_text(doc_index[arguments["doc_id"]], doc_store, conn, member_id)
    if not text.strip():
        return {"error": "Give the text to check, or a doc_id of a document to cite-check."}, []
    res = verify_citations(conn, text[:200_000], member_id, forum=_forum(conn, matter, arguments),
                           as_of=arguments.get("as_of") or None)
    return res, [{"type": "citation_check", "count": res["count"], "summary": res["summary"]}]


RESEARCH_TOOLS = {
    "search_authority": search_authority_tool,
    "read_authority": read_authority_tool,
    "resolve_citation": resolve_citation_tool,
    "get_citing_authorities": get_citing_authorities_tool,
    "check_authority_status": check_authority_status_tool,
    "verify_citations": verify_citations_tool,
}
