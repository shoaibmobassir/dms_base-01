"""Local corpus provider: typed authorities from documents the firm already holds (§22.4).

Authorities here are the published decisions of the Permanent Court of
International Justice (Judgment, Order, Advisory Opinion) and United Nations
Security Council resolutions. Pleadings, applications and annexes in the same
matters are party material and stay firm documents.

Every read goes through the matter ACL and document privacy, like any other
document. There is no citator: status comes only from labeled, derived signals
found in later authorities of the corpus (§22.9), and is otherwise ``unknown``.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.api.acl import ACL_CLAUSE, doc_acl
from app.km.passages import _FROM, _SELECT, _collapse, _cross_encode, _embed, rank_passages
from app.km.scope import ACL_SQL, DOC_SQL, _fetch
from app.research import structure
from app.research.citations import Citation, extract_citations
from app.research.formatter import format_citation
from app.research.legal_systems import Forum, label_for
from app.retrieval.matter_resolver import chunk_or_tsquery

PROVIDER = "local"
AUTHORITY_TYPES = ("Judgment", "Order", "Advisory Opinion", "Security Council Resolution")
_KIND = {"Judgment": "case", "Order": "order", "Advisory Opinion": "advisory_opinion",
         "Security Council Resolution": "resolution"}
_PCIJ_TITLE = re.compile(r"PCIJ\s+Series\s+(?P<series>A/B|AB|A|B)\s+No\.\s*(?P<num>\d+)", re.I)
_UNSC_TITLE = re.compile(r"resolution\s+(?P<num>\d{1,4})\s*\((?P<year>\d{4})\)", re.I)
_UNTIL = re.compile(r"until\s+(?P<d>\d{1,2})\s+(?P<m>[A-Z][a-z]{2,8})\.?\s+(?P<y>\d{4})")
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_CH7_SQL = r"d.body ~* 'Acting\s+under\s+(Chapter\s+VII|Article\s+(39|40|41|42)\M)'"

_AUTH_COLS = f"""
    d.document_id, d.title, d.document_type, d.doc_date, d.matter_id, d.current_version_id,
    m.title AS matter_title, m.court, m.matter_type, left(d.body, 400) AS head, length(d.body) AS body_len,
    {_CH7_SQL} AS chapter_vii
"""
_AUTH_FROM = """
    FROM documents d
    JOIN matters m ON m.matter_id = d.matter_id
    JOIN permissions p ON p.matter_id = d.matter_id
"""
_ACL = f"({ACL_CLAUSE} AND {doc_acl('d')})"


def capabilities() -> dict[str, Any]:
    return {
        "provider": PROVIDER,
        "legal_systems": ["international"],
        "kinds": ["case", "advisory_opinion", "order", "resolution"],
        "collections": ["PCIJ (Series A, B, A/B)", "UN Security Council resolutions"],
        "citator": False,
        "pinpoints": "PCIJ: PDF pages; UNSC: operative paragraphs",
        "egress": "none",
    }


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def authority_id(document_id: str) -> str:
    return f"{PROVIDER}:{document_id}"


def document_id_of(aid: str) -> str:
    return aid.split(":", 1)[1] if aid.startswith(f"{PROVIDER}:") else aid


def _until(title: str) -> date | None:
    m = _UNTIL.search(title or "")
    if not m:
        return None
    month = _MONTHS.get(m.group("m")[:3].lower())
    try:
        return date(int(m.group("y")), month, int(m.group("d"))) if month else None
    except ValueError:
        return None


def normalize(row: dict[str, Any]) -> dict[str, Any]:
    """Authority dict (subset of the §22.4 shape) from a documents ⋈ matters row."""
    doc_type = row["document_type"]
    title = row["title"] or ""
    base: dict[str, Any] = {
        "authority_id": authority_id(row["document_id"]),
        "provider": PROVIDER,
        "document_id": row["document_id"],
        "matter_id": row["matter_id"],
        "legal_system": "international",
        "kind": _KIND.get(doc_type, "other"),
        "title": title,
        "decision_date": row["doc_date"].isoformat() if isinstance(row.get("doc_date"), date) else row.get("doc_date"),
        "page_kind": "pdf",
        "length": row.get("body_len"),
        "license": {"llm_use": True, "store_text": True, "display": "full"},
    }
    if doc_type == "Security Council Resolution":
        m = _UNSC_TITLE.search(title)
        subject = re.search(r"\[(.+?)\]", title)
        until = _until(title)
        base.update({
            "provider_kind": "unsc",
            "court": {"name": "United Nations Security Council", "level": "un_organ"},
            "citation": {"key": f"unsc:{int(m.group('num'))}" if m else None,
                         "number": int(m.group("num")) if m else None, "year": int(m.group("year")) if m else None},
            "subject": subject.group(1) if subject else None,
            "chapter_vii": bool(row.get("chapter_vii")),
            "mandate_until": until.isoformat() if until else None,
        })
    else:
        mt = row.get("matter_title") or ""
        m = _PCIJ_TITLE.search(mt)
        series = (m.group("series").upper().replace("AB", "A/B") if m else None)
        opinion = structure.opinion_heading(row.get("head") or "")
        base.update({
            "provider_kind": "pcij",
            "court": {"name": "Permanent Court of International Justice", "level": "international_court"},
            "case_name": mt.split(" — ")[0].strip() if mt else title,
            "citation": {"key": f"pcij:{series}:{int(m.group('num'))}" if m else None,
                         "series": series, "number": int(m.group("num")) if m else None},
            "role": opinion[0] if opinion else "majority",
            "judge": opinion[1] if opinion else None,
        })
    base["citation"]["primary"] = format_citation(base)
    return base


def brief(authority: dict[str, Any], label: dict[str, Any] | None = None) -> dict[str, Any]:
    keep = ("authority_id", "document_id", "kind", "provider_kind", "title", "case_name", "decision_date",
            "role", "judge", "subject", "chapter_vii", "mandate_until")
    out = {k: authority[k] for k in keep if authority.get(k) not in (None, "")}
    out["citation"] = authority["citation"]["primary"]
    if label:
        out["binding"] = label
    return out


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def _rows(conn, where: str, params: dict[str, Any], *, order: str = "d.doc_date, d.document_id", limit: int = 50) -> list[dict]:
    return _fetch(conn, f"SELECT {_AUTH_COLS} {_AUTH_FROM} WHERE {_ACL} AND d.document_type = ANY(%(types)s) AND {where} "
                        f"ORDER BY {order} LIMIT {int(limit)}",
                  {"types": list(AUTHORITY_TYPES), **params})


def get(conn, aid: str, member_id: str | None) -> dict[str, Any] | None:
    rows = _rows(conn, "d.document_id = %(id)s", {"id": document_id_of(aid).upper(), "member_id": member_id}, limit=1)
    return normalize(rows[0]) if rows else None


def body(conn, aid: str, member_id: str | None) -> str | None:
    rows = _fetch(conn, f"SELECT d.body {_AUTH_FROM} WHERE {_ACL} AND d.document_id = %(id)s",
                  {"id": document_id_of(aid).upper(), "member_id": member_id})
    return rows[0]["body"] if rows else None


def paged_body(text: str) -> str:
    """Body with [Page N] markers at PDF page breaks, the form the citation rules read."""
    pages = (text or "").split("\f")
    return "\n\n".join(f"[Page {i}]\n{p.strip()}" for i, p in enumerate(pages, 1) if p.strip())


def without_headnote(authority: dict[str, Any], text: str) -> str:
    """Resolution text with any editorial summary replaced by a marker, so a quote taken from the
    summary can never be verified as the Council's words."""
    if authority.get("provider_kind") != "unsc":
        return text
    for p in structure.segment_resolution(text):
        if p.role == "headnote":
            return "[Editorial summary omitted: not the Council's text]\n" + text[p.end:]
    return text


def passages(authority: dict[str, Any], text: str) -> list[structure.Passage]:
    if authority.get("provider_kind") == "unsc":
        return structure.segment_resolution(text)
    return structure.segment_decision(text)


def _passage_dict(p: structure.Passage) -> dict[str, Any]:
    return {"role": p.role, "lead_verb": p.lead_verb, "para": p.para}


def label(authority: dict[str, Any], forum: Forum | None, passage: structure.Passage | None = None) -> dict[str, Any]:
    return label_for(authority, forum, _passage_dict(passage) if passage else None).to_dict()


# ---------------------------------------------------------------------------
# resolve_citation
# ---------------------------------------------------------------------------

_HELD = {"pcij", "unsc"}


def resolve(conn, citation: Citation, member_id: str | None) -> dict[str, Any]:
    """Resolve a parsed citation against the held collections.

    resolution: resolved | not_found (a held collection, but no such authority) |
    not_held (no provider for this collection yet).
    """
    base = {"citation": citation.raw, "key": citation.key, "system": citation.system, "pinpoint": citation.pinpoint}
    collection = citation.key.split(":", 1)[0]
    if collection not in _HELD:
        where = {"icj": "ICJ Reports", "unts": "the UN Treaty Series", "in": "Indian law", "us": "US law"}.get(collection, collection)
        return {**base, "resolution": "not_held",
                "reason": f"Recognized citation, but no source for {where} is available yet; not verified."}
    if collection == "unsc":
        num = int(citation.key.split(":")[1])
        rows = _rows(conn, "d.title ~* %(rx)s", {"rx": rf"resolution\s+{num}\s*\(", "member_id": member_id}, limit=3)
        year = re.search(r"\((\d{4})\)", citation.raw)
        if rows and year:
            rows = [r for r in rows if str(r["doc_date"].year if r.get("doc_date") else "") == year.group(1)] or rows
        if not rows:
            latest = _fetch(conn, "SELECT max((substring(title from 'resolution\\s+(\\d+)'))::int) AS n FROM documents "
                                  "WHERE document_type = 'Security Council Resolution'", {})
            hi = (latest[0] or {}).get("n") if latest else None
            why = (f"No Security Council resolution {num} in the collection (which runs to {hi})."
                   if hi and num <= hi else f"Resolution {num} is later than the collection's latest ({hi}).")
            return {**base, "resolution": "not_found", "reason": why}
        auths = [normalize(r) for r in rows]
        if year and auths[0]["citation"]["year"] and str(auths[0]["citation"]["year"]) != year.group(1):
            return {**base, "resolution": "not_found",
                    "reason": f"Resolution {num} was adopted in {auths[0]['citation']['year']}, not {year.group(1)}.",
                    "candidates": [brief(a) for a in auths]}
        return {**base, "resolution": "resolved", "authorities": auths}
    # pcij
    _, series, num = citation.key.split(":")
    rx = rf"PCIJ\s+Series\s+{re.escape(series.replace('/', ''))}\s+No\.\s*{int(num)}$"
    rows = _rows(conn, "m.title ~* %(rx)s", {"rx": rx, "member_id": member_id})
    auths = [normalize(r) for r in rows]
    majority = [a for a in auths if a["role"] == "majority"]
    if not auths:
        return {**base, "resolution": "not_found",
                "reason": f"No PCIJ Series {series}, No. {num} decision in the held collection."}
    order = {"case": 0, "advisory_opinion": 1, "order": 2}
    # The principal decision is the longest majority text of the leading kind (a merits judgment
    # over a short judgment on intervention published under the same number).
    majority.sort(key=lambda a: (order.get(a["kind"], 3), -(a.get("length") or 0)))
    return {**base, "resolution": "resolved", "authorities": majority + [a for a in auths if a["role"] != "majority"]}


def resolve_text(conn, text: str, member_id: str | None) -> list[dict[str, Any]]:
    return [resolve(conn, c, member_id) for c in extract_citations(text)]


# ---------------------------------------------------------------------------
# search_authority
# ---------------------------------------------------------------------------

def _locate(text: str, snippet: str) -> int:
    words = re.findall(r"\w+", snippet or "")[:8]
    if not words:
        return -1
    m = re.search(r"\W+".join(map(re.escape, words)), text)
    return m.start() if m else -1


_STOP = {"the", "of", "and", "to", "a", "in", "on", "for", "by", "is", "are", "be", "that", "with", "as", "or",
         "an", "its", "it", "this", "under", "what", "which", "does", "do", "how", "when", "who", "states", "state"}
# Ranking adjustments by the role of the passage that represents an authority (§22.6: the ranker is
# deterministic). Operative text and the Court's own reasoning outrank context, summaries and opinions.
_ROLE_BONUS = {"operative": 0.6, "majority": 0.3, "preamble": -0.6, "headnote": -0.8,
               "separate_opinion": -0.6, "dissent": -0.8, "declaration": -0.6}


def _terms(text: str) -> set[str]:
    return {w[:6] for w in re.findall(r"[a-z]{3,}", (text or "").lower()) if w not in _STOP}


def _best_operative(segs: list[structure.Passage], query: str) -> structure.Passage | None:
    """The operative paragraph sharing most terms with the query (at least two)."""
    want = _terms(query)
    best, score = None, 1
    for p in segs:
        if p.role != "operative":
            continue
        s = len(want & _terms(p.text))
        if s > score:
            best, score = p, s
    return best


def search(conn, query: str, member_id: str | None, *, kinds: list[str] | None = None,
           date_from: str | None = None, date_to: str | None = None, limit: int = 8,
           forum: Forum | None = None, graph_boost: bool = True) -> list[dict[str, Any]]:
    """Hybrid passage search restricted to authorities; one hit per authority.

    Ranking = cross-encoder score of the best passage, adjusted deterministically for the role of
    the representative passage, plus a citation-graph boost for authorities that several of the
    top passages themselves cite (the source of an obligation outranks texts that reaffirm it).
    """
    q = (query or "").strip()
    if not q:
        return []
    types = [t for t, k in _KIND.items() if not kinds or k in kinds]
    params: dict[str, Any] = {"member_id": member_id, "types": types,
                              "dfrom": date_from or "0001-01-01", "dto": date_to or "9999-12-31"}
    filt = "d.document_type = ANY(%(types)s) AND d.doc_date BETWEEN %(dfrom)s::date AND %(dto)s::date"
    cands: list[dict] = []
    tsq = chunk_or_tsquery(q)
    if tsq:
        cands += [{**r, "_lex": float(r["lex"])} for r in _fetch(conn, f"""
            SELECT {_SELECT}, ts_rank_cd(c.tsv, to_tsquery('english', %(tsq)s)) AS lex
            {_FROM} WHERE {ACL_SQL} AND {DOC_SQL} AND {filt} AND c.tsv @@ to_tsquery('english', %(tsq)s)
            ORDER BY lex DESC LIMIT 80""", {**params, "tsq": tsq})]
    vec = _embed(q)
    if vec:
        cands += [{**r, "_vec": float(r["sim"])} for r in _fetch(conn, f"""
            SELECT {_SELECT}, 1 - (c.embedding <=> %(v)s::vector) AS sim
            {_FROM} WHERE {ACL_SQL} AND {DOC_SQL} AND {filt} AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %(v)s::vector LIMIT 80""", {**params, "v": vec})]
    ranked = rank_passages(q, _collapse(cands), limit=max(limit * 4, 24), per_doc=1)
    best = {r["document_id"]: r for r in ranked}
    base_score = {did: float(r.get("score") or 0.0) for did, r in best.items()}

    # Citations named in the query come first, whatever the ranker thinks.
    named: list[str] = []
    for res in resolve_text(conn, q, member_id):
        for a in res.get("authorities", [])[:1]:
            named.append(a["document_id"])

    # Citation graph: authorities cited by two or more of the top passages.
    cited_by: dict[str, int] = {}
    if graph_boost:
        counts: dict[str, int] = {}
        for r in ranked[:20]:
            for key in {c.key for c in extract_citations(r.get("text") or "") if c.key.split(":")[0] in _HELD}:
                counts[key] = counts.get(key, 0) + 1
        # The graph adds candidates; relevance still ranks them. A cited authority is scored by the
        # cross-encoder on its own best operative paragraph, plus a small bonus per citing passage.
        extra: list[tuple[str, int, dict]] = []
        for key, n in sorted(counts.items(), key=lambda kv: -kv[1])[:5]:
            if n < 2:
                continue
            res = resolve(conn, Citation(raw=key, key=key, system="international", kind="", start=0, end=0), member_id)
            for a in res.get("authorities", [])[:1]:
                if kinds and a["kind"] not in kinds:
                    continue
                if not (params["dfrom"] <= (a["decision_date"] or "") <= params["dto"]):
                    continue
                extra.append((a["document_id"], n, a))
        if extra:
            texts = {r["document_id"]: r["body"] for r in _fetch(
                conn, "SELECT document_id, body FROM documents WHERE document_id = ANY(%(ids)s)",
                {"ids": [d for d, _, _ in extra]})}
            rows = []
            for did, n, a in extra:
                segs = passages(a, texts.get(did) or "")
                rep = _best_operative(segs, q) or next((p for p in segs if p.role in ("operative", "majority")), None)
                rows.append({"title": a["title"], "text": rep.text if rep else (texts.get(did) or "")[:1200]})
            for (did, n, _), ce in zip(extra, _cross_encode(q, rows)):
                cited_by[did] = n
                base_score[did] = max(base_score.get(did, float("-inf")), float(ce)) + 0.3 * n

    pool = list(dict.fromkeys(named + sorted(base_score, key=lambda d: -base_score[d])))[: max(limit * 2, 12)]
    if not pool:
        return []
    meta = {r["document_id"]: r for r in _rows(conn, "d.document_id = ANY(%(ids)s)",
                                                {"ids": pool, "member_id": member_id}, limit=len(pool))}
    bodies = {r["document_id"]: r["body"] for r in _fetch(
        conn, "SELECT document_id, body FROM documents WHERE document_id = ANY(%(ids)s)", {"ids": pool})}
    hits: list[dict[str, Any]] = []
    for did in pool:
        if did not in meta:
            continue  # not accessible
        a = normalize(meta[did])
        text = bodies.get(did) or ""
        snippet = " ".join(str((best.get(did) or {}).get("text") or "").split())
        segs = passages(a, text)
        pos = _locate(text, snippet) if snippet else -1
        seg = structure.role_at(segs, pos) if pos >= 0 else None
        if a["provider_kind"] == "unsc" and (seg is None or seg.role != "operative"):
            op = _best_operative(segs, q)
            if op is not None:
                seg, pos, snippet = op, op.start, " ".join(op.text.split())
        if seg is None and a["provider_kind"] == "pcij" and segs:
            seg = segs[0]
        hit = brief(a, label(a, forum, seg) if (seg or a["provider_kind"] == "pcij") else label(a, forum))
        if seg is not None:
            hit["passage"] = {"role": seg.role, "para": seg.para_label,
                              "page": structure.page_at(structure.page_offsets(text), pos) if pos >= 0 and a["provider_kind"] == "pcij" else None}
        hit["snippet"] = snippet[:320] if snippet else " ".join(text.split())[:320]
        score = base_score.get(did, 0.0) + _ROLE_BONUS.get(seg.role if seg else "", 0.0)
        hit["score"] = round(score, 3)
        hit["named_in_query"] = did in named
        if did in cited_by:
            hit["cited_by_results"] = cited_by[did]
        hits.append(hit)
    hits.sort(key=lambda h: (not h["named_in_query"], -h["score"]))
    return hits[:limit]


# ---------------------------------------------------------------------------
# get_citing_authorities and status
# ---------------------------------------------------------------------------

_TREATMENT = [
    ("terminated", re.compile(r"terminat|shall\s+cease|decides\s+to\s+end|ended\s+the\s+mandate", re.I)),
    ("superseded", re.compile(r"supersed|replac", re.I)),
    ("extended", re.compile(r"extend|renew|prolong", re.I)),
    ("applied", re.compile(r"implement|comply|compliance|pursuant\s+to|in\s+accordance\s+with", re.I)),
    ("recalled", re.compile(r"recall|reaffirm|recalling|reaffirming|referring", re.I)),
]


def _clause_around(text: str, start: int, end: int) -> str:
    a = max(text.rfind(";", 0, start), text.rfind(",\n", 0, start), text.rfind(".\n", 0, start), start - 400)
    b_candidates = [i for i in (text.find(";", end), text.find(",\n", end), text.find(".\n", end)) if i != -1]
    b = min(b_candidates + [end + 400])
    return " ".join(text[a + 1:b].split())


def citing(conn, aid: str, member_id: str | None, *, limit: int = 20) -> dict[str, Any]:
    a = get(conn, aid, member_id)
    if not a:
        return {"error": "Authority not found or not accessible."}
    out: list[dict[str, Any]] = []
    if a["provider_kind"] == "unsc":
        num, year = a["citation"]["number"], a["citation"]["year"]
        rx = rf"(resolution|S/RES/)\s*{num}\s*\(\s*{year}\s*\)"
        rows = _fetch(conn, f"""
            SELECT d.document_id, d.title, d.doc_date, d.body {_AUTH_FROM}
            WHERE {_ACL} AND d.document_type = 'Security Council Resolution' AND d.document_id <> %(id)s
              AND d.doc_date >= %(dt)s::date AND d.body ~* %(rx)s
            ORDER BY d.doc_date LIMIT %(lim)s""",
            {"member_id": member_id, "id": a["document_id"], "dt": a["decision_date"] or "0001-01-01", "rx": rx, "lim": limit})
        pat = re.compile(rx, re.I)
        for r in rows:
            text = r["body"] or ""
            segs = structure.segment_resolution(text)
            # First mention in the official text; an editorial summary above it does not count.
            m, seg = None, None
            for mm in pat.finditer(text):
                where = structure.role_at(segs, mm.start())
                if where is None or where.role != "headnote":
                    m, seg = mm, where
                    break
            if m is None:
                continue
            clause = _clause_around(text, m.start(), m.end())
            treatment = next((t for t, trx in _TREATMENT if trx.search(clause)), "cited")
            if seg is not None and seg.role == "preamble" and treatment in ("terminated", "superseded", "extended"):
                treatment = "recalled"  # a preamble mentions; only operative text acts on a resolution
            num2 = _UNSC_TITLE.search(r["title"] or "")
            out.append({"authority_id": authority_id(r["document_id"]), "document_id": r["document_id"],
                        "citation": f"S/RES/{num2.group('num')} ({num2.group('year')})" if num2 else r["title"],
                        "date": r["doc_date"].isoformat() if r.get("doc_date") else None,
                        "treatment": treatment, "treatment_source": "derived",
                        "in": seg.role if seg else None, "para": seg.para_label if seg else None,
                        "context": clause[:300]})
    else:
        name = (a.get("case_name") or "").split("(")[0].strip()
        series, number = a["citation"]["series"], a["citation"]["number"]
        if name:
            rx = rf"(Series\s+{re.escape(series or '')}\s*,?\s*No\.?\s*{number}\M|{re.escape(name)})"
            rows = _fetch(conn, f"""
                SELECT d.document_id, d.title, d.doc_date, d.body, m.title AS matter_title {_AUTH_FROM}
                WHERE {_ACL} AND d.document_type = ANY(%(types)s) AND d.matter_id <> %(mid)s
                  AND d.doc_date > %(dt)s::date AND d.body ~* %(rx)s
                ORDER BY d.doc_date LIMIT %(lim)s""",
                {"member_id": member_id, "types": ["Judgment", "Order", "Advisory Opinion"], "mid": a["matter_id"],
                 "dt": a["decision_date"] or "0001-01-01", "rx": rx, "lim": limit})
            pat = re.compile(rx.replace(r"\M", r"\b"), re.I)
            for r in rows:
                text = r["body"] or ""
                m = pat.search(text)
                out.append({"authority_id": authority_id(r["document_id"]), "document_id": r["document_id"],
                            "citation": (r.get("matter_title") or r["title"]),
                            "date": r["doc_date"].isoformat() if r.get("doc_date") else None,
                            "treatment": "mentioned", "treatment_source": "derived",
                            "role": (structure.opinion_heading(text) or ("majority",))[0],
                            "page": structure.page_at(structure.page_offsets(text), m.start()) if m else None,
                            "context": _clause_around(text, m.start(), m.end())[:300] if m else ""})
    return {"authority": brief(a), "citing": out, "count": len(out),
            "note": "Treatment is derived from the text of later authorities in the firm's collection, not from a citator."}


def status(conn, aid: str, member_id: str | None, *, as_of: str | None = None) -> dict[str, Any]:
    a = get(conn, aid, member_id)
    if not a:
        return {"error": "Authority not found or not accessible."}
    as_of_d = date.fromisoformat(as_of) if as_of else date.today()
    signals: list[dict[str, Any]] = []
    signal, notes = "unknown", []
    if a["provider_kind"] == "unsc":
        if a.get("mandate_until") and date.fromisoformat(a["mandate_until"]) < as_of_d:
            signals.append({"type": "expired_by_own_terms", "as_of": a["mandate_until"], "source": "derived"})
            signal = "expired"
            notes.append(f"The period this resolution set ran until {a['mandate_until']}; check later resolutions for the current position.")
        for c in citing(conn, aid, member_id, limit=40).get("citing", []):
            if c["date"] and date.fromisoformat(c["date"]) > as_of_d:
                continue
            if c["treatment"] in ("terminated", "superseded", "extended"):
                signals.append({"type": c["treatment"], "by": c["authority_id"], "citation": c["citation"],
                                "as_of": c["date"], "source": "derived", "para": c.get("para")})
        if any(s["type"] == "terminated" for s in signals):
            signal = "expired"
        elif any(s["type"] == "superseded" for s in signals) and signal == "unknown":
            signal = "caution"
    else:
        notes.append("No citator for PCIJ decisions. Later treatment (including by the ICJ) is not checked; "
                     "use get_citing_authorities for mentions within the PCIJ collection.")
    return {"authority": brief(a), "as_of": as_of_d.isoformat(),
            "status": {"signal": signal, "signals": signals, "source": "derived" if signals else "none",
                       "checked_at": date.today().isoformat()},
            "display": {"unknown": "Status not verified", "expired": "Expired or terminated (derived)",
                        "caution": "Caution (derived)"}.get(signal, signal),
            "notes": notes}
