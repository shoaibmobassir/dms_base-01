"""Cite-check: verify every citation in a block of text (§22.9).

For each citation: does it exist (resolved by a provider, never by the model),
is the pinpoint real, is a quote placed next to it really in the authority and
in a passage that may be cited for it, what is its status, and how binding is
it for the forum. Verdicts map to the UI states: Verified / Verified with
caution / Negative treatment / Not verified.
"""
from __future__ import annotations

import re
from typing import Any

from app.chat.verify_citations import locate_quote
from app.research import local_provider as lp
from app.research import structure
from app.research.citations import extract_citations
from app.research.formatter import format_citation, judge_name
from app.research.legal_systems import Forum, label_for
from app.research.ocr_match import locate_ocr

_QUOTE = re.compile(r"[\"“]([^\"”]{12,600})[\"”]")


def _quote_before(text: str, start: int, floor: int = 0) -> str | None:
    """A quotation that ends shortly before the citation (the usual "..." (Cite) pattern).

    ``floor`` is the end of the previous citation: a quote before it belongs to that citation.
    """
    window = text[max(floor, start - 700):start]
    quotes = list(_QUOTE.finditer(window))
    if quotes and len(window) - quotes[-1].end() < 60:
        return quotes[-1].group(1)
    return None


def verify_citations(conn, text: str, member_id: str | None, *, forum: Forum | None = None,
                     as_of: str | None = None) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    prev_end = 0
    for cit in extract_citations(text or ""):
        floor, prev_end = prev_end, cit.end
        res = lp.resolve(conn, cit, member_id)
        row: dict[str, Any] = {"citation": cit.raw, "key": cit.key, "system": cit.system,
                               "pinpoint": cit.pinpoint, "resolution": res["resolution"], "issues": []}
        if res["resolution"] != "resolved":
            row.update(verdict="not_verified", reason=res.get("reason"))
            rows.append(row)
            continue
        candidates = res["authorities"]
        a = candidates[0]
        body = lp.body(conn, a["authority_id"], member_id) or ""
        segs = lp.passages(a, body)
        seg: structure.Passage | None = None
        page = cit.pinpoint.get("page")
        para = cit.pinpoint.get("para")

        if a["provider_kind"] == "unsc" and para:
            ops = [p for p in segs if p.role == "operative"]
            seg = next((p for p in ops if p.para == para), None)
            if seg is None:
                row["issues"].append(f"Paragraph {para} does not exist: the resolution has {len(ops)} operative paragraphs.")
        if a["provider_kind"] == "pcij" and page:
            n_pages = len(structure.page_offsets(body))
            for cand in candidates[1:]:
                if page <= n_pages or cand.get("role") != "majority":
                    break
                cbody = lp.body(conn, cand["authority_id"], member_id) or ""
                if page <= len(structure.page_offsets(cbody)):
                    a, body, segs, n_pages = cand, cbody, lp.passages(cand, cbody), len(structure.page_offsets(cbody))
            if page > n_pages:
                row["issues"].append(f"Page {page} is beyond this decision's {n_pages} PDF pages "
                                     "(pinpoints here are PDF pages, not official report pages).")

        quote = _quote_before(text, cit.start, floor)
        if quote:
            # Search every document of the authority (majority first, then opinions) for the quote.
            located = None
            for cand in candidates:
                cbody = body if cand is a else (lp.body(conn, cand["authority_id"], member_id) or "")
                loc = locate_quote(cbody, quote)
                start = loc.start if loc is not None else None
                if start is None:
                    fuzzy = locate_ocr(cbody, quote)  # scanned reports: OCR-tolerant fallback
                    start = fuzzy[0] if fuzzy else None
                if start is not None:
                    located = (cand, cbody, start)
                    break
            if located is None:
                row["issues"].append("Quoted text was not found in the authority.")
                row["quote_found"] = False
            else:
                cand, cbody, qstart = located
                csegs = lp.passages(cand, cbody)
                where = structure.role_at(csegs, qstart)
                row["quote_found"] = True
                if cand is not a or (where and where.role not in ("majority", "operative")):
                    role = (where.role if where else cand.get("role")) or "unknown"
                    row["issues"].append(f"The quote comes from a {role.replace('_', ' ')}"
                                         f"{' of ' + judge_name(cand['judge']) if cand.get('judge') else ''}, "
                                         "not the Court's or Council's operative text.")
                    a, seg = cand, where
                elif a["provider_kind"] == "unsc":
                    seg = where
                if a["provider_kind"] == "pcij":
                    page = structure.page_at(structure.page_offsets(cbody), qstart)

        binding = label_for(a, forum, {"role": seg.role, "lead_verb": seg.lead_verb} if seg else None)
        st = lp.status(conn, a["authority_id"], member_id, as_of=as_of)
        signal = st["status"]["signal"]
        if signal in ("negative",):
            verdict = "negative_treatment"
        elif signal in ("expired", "caution", "superseded") or row["issues"]:
            verdict = "verified_with_caution"
        else:
            verdict = "verified"
        row.update(
            verdict=verdict,
            authority=lp.brief(a),
            formatted=format_citation(a, page=page, para=(seg.para_label if seg and seg.role == "operative" else para)),
            binding=binding.to_dict(),
            status=st["status"] | {"display": st["display"]},
            status_notes=st.get("notes", []),
        )
        rows.append(row)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"count": len(rows), "summary": counts, "citations": rows,
            "note": "Verification uses the firm's PCIJ and UN Security Council collections. Other citations are "
                    "recognized but not verifiable until a source for them is added."}
