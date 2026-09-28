"""The KM panel: which matters, which documents and which people an Ask the Firm answer is about.

Ask the Firm is the firm's knowledge desk, so every answer carries the three things a KM lawyer
looks up — not only passages. Built from records and the evidence already gathered; no LLM.

  matters   — asked-about matters, matters of the relevant documents, similar matters from the
              resolver, and matters linked in ``relationships`` (precedent, follow-up, similar facts)
  documents — the relevant documents (cited ones are flagged after the answer is grounded)
  people    — who is staffed on those matters (lead first), who wrote the documents, and who
              specialises in the topic

Every row says *why* it is there. All reads honour the matter ACL: a restricted matter, its team
and its documents never appear.
"""
from __future__ import annotations

import time
from typing import Any

from app.km.scope import ACL_SQL, DOC_SQL, _fetch

MAX_MATTERS = 8
MAX_DOCUMENTS = 10
MAX_PEOPLE = 8
_RELATED_TYPES = ("precedent_for", "follow_up_to", "similar_facts", "same_client")
_REL_LABEL = {
    "precedent_for": "precedent", "follow_up_to": "follow-up matter",
    "similar_facts": "similar facts", "same_client": "same client",
}
# Lower sorts first. Scope beats evidence beats similarity beats relationships.
_TIER = {"asked": 0, "evidence": 1, "similar": 2, "related": 3}


def _add_matter(found: dict[str, dict], matter_id: str, tier: str, why: str, score: float) -> None:
    row = found.get(matter_id)
    if row is None:
        found[matter_id] = {"matter_id": matter_id, "tier": tier, "why": [why], "score": score}
        return
    if _TIER[tier] < _TIER[row["tier"]]:
        row["tier"] = tier
    if why not in row["why"]:
        row["why"].append(why)
    row["score"] = max(row["score"], score)


def _related(conn, seed_ids: list[str], member_id: str | None) -> list[dict]:
    if not seed_ids:
        return []
    return _fetch(
        conn,
        f"""
        SELECT DISTINCT ON (m.matter_id) m.matter_id, r.rel_type,
               (SELECT v.matter_code FROM matters v
                 WHERE v.matter_id = CASE WHEN r.source_id = ANY(%(ids)s) THEN r.source_id ELSE r.target_id END) AS via
        FROM relationships r
        JOIN matters m ON m.matter_id = CASE WHEN r.source_id = ANY(%(ids)s) THEN r.target_id ELSE r.source_id END
        JOIN permissions p ON p.matter_id = m.matter_id
        WHERE (r.source_id = ANY(%(ids)s) OR r.target_id = ANY(%(ids)s))
          AND r.rel_type = ANY(%(types)s)
          AND m.matter_id <> ALL(%(ids)s)
          AND {ACL_SQL}
        ORDER BY m.matter_id, array_position(%(types)s, r.rel_type)
        """,
        {"ids": seed_ids, "types": list(_RELATED_TYPES), "member_id": member_id},
    )


def _matter_rows(conn, ids: list[str], member_id: str | None) -> dict[str, dict]:
    """Compact matter rows, ACL-checked; a matter missing here is dropped from the panel."""
    if not ids:
        return {}
    rows = _fetch(
        conn,
        f"""
        SELECT m.matter_id, m.matter_code, m.title, cl.name AS client_name, m.practice_area, m.status,
               m.opened_date, m.closed_date,
               (SELECT count(*) FROM documents d WHERE d.matter_id = m.matter_id AND {DOC_SQL}) AS document_count,
               (SELECT mb.name FROM matter_members mm JOIN members mb USING (member_id)
                 WHERE mm.matter_id = m.matter_id AND lower(coalesce(mm.role_on_matter, '')) = 'lead'
                 ORDER BY mb.member_id LIMIT 1) AS lead
        FROM matters m
        JOIN clients cl ON cl.client_id = m.client_id
        JOIN permissions p ON p.matter_id = m.matter_id
        WHERE {ACL_SQL} AND m.matter_id = ANY(%(ids)s)
        """,
        {"ids": ids, "member_id": member_id},
    )
    return {r["matter_id"]: r for r in rows}


def _teams(conn, matter_ids: list[str]) -> list[dict]:
    if not matter_ids:
        return []
    return _fetch(
        conn,
        """
        SELECT mm.matter_id, mb.member_id, mb.name, mb.role, mb.office, mm.role_on_matter
        FROM matter_members mm JOIN members mb USING (member_id)
        WHERE mm.matter_id = ANY(%(ids)s)
        ORDER BY array_position(%(ids)s, mm.matter_id),
                 CASE lower(coalesce(mm.role_on_matter, '')) WHEN 'lead' THEN 0 ELSE 1 END, mb.member_id
        """,
        {"ids": matter_ids},
    )


def _authors(conn, document_ids: list[str]) -> list[dict]:
    if not document_ids:
        return []
    return _fetch(
        conn,
        """
        SELECT d.document_id, d.title, d.matter_id, mb.member_id, mb.name, mb.role, mb.office
        FROM documents d JOIN members mb ON mb.member_id = d.author_id
        WHERE d.document_id = ANY(%(ids)s)
        """,
        {"ids": document_ids},
    )


def _documents(passages: list[dict], cards: list[dict]) -> list[dict]:
    docs: dict[str, dict] = {}
    for h in passages:
        did = str(h.get("document_id") or "").upper()
        if not did or did in docs:
            continue
        docs[did] = {
            "document_id": did, "title": h.get("title"), "document_type": h.get("document_type"),
            "doc_date": h.get("doc_date"), "author_name": h.get("author_name"), "matter_id": h.get("matter_id"),
            "matter_code": h.get("matter_code"), "page_number": h.get("page_number"),
            "snippet": " ".join(str(h.get("text") or "").split())[:240], "why": "relevant passage", "cited": False,
        }
    if not docs:
        # A records-only answer ("which matters…", a matter overview): show the matters' own documents.
        for c in cards:
            for d in c.get("documents") or []:
                did = str(d["document_id"]).upper()
                docs.setdefault(did, {
                    "document_id": did, "title": d.get("title"), "document_type": d.get("document_type"),
                    "doc_date": d.get("doc_date"), "author_name": d.get("author_name"),
                    "matter_id": c["matter_id"], "matter_code": c.get("matter_code"), "page_number": None,
                    "snippet": "", "why": "on the matter", "cited": False,
                })
    return list(docs.values())[:MAX_DOCUMENTS]


def build_panel(
    conn,
    *,
    member_id: str | None,
    scope_ids: list[str],
    cards: list[dict],
    passages: list[dict],
    candidates: list[dict],
    experts: list[dict],
    people_first: bool,
) -> dict[str, Any]:
    """Matters, documents and people for one answer (see module docstring)."""
    t0 = time.perf_counter()
    found: dict[str, dict] = {}
    for mid in scope_ids:
        _add_matter(found, mid, "asked", "asked about", 10.0)
    per_matter: dict[str, list[float]] = {}
    for h in passages:
        if h.get("matter_id"):
            per_matter.setdefault(h["matter_id"], []).append(float(h.get("score") or 0))
    for mid, scores in sorted(per_matter.items(), key=lambda kv: (-len(kv[1]), -max(kv[1]))):
        n = len(scores)
        _add_matter(found, mid, "evidence", f"{n} relevant passage{'s' if n != 1 else ''}", max(scores))
    for c in candidates:
        score = float(c.get("score") or 0)
        if score >= 0.35:
            _add_matter(found, c["matter_id"], "similar", f"similar matter ({score:.2f})", score)
    seeds = [mid for mid, row in found.items() if row["tier"] in ("asked", "evidence")][:2]
    for r in _related(conn, seeds, member_id):
        _add_matter(found, r["matter_id"], "related", f"{_REL_LABEL.get(r['rel_type'], r['rel_type'])} of {r['via']}", 0.0)

    ordered = sorted(found.values(), key=lambda r: (_TIER[r["tier"]], -r["score"]))
    # A client or "which matters…" question lists every asked-about matter (up to 25).
    limit = max(MAX_MATTERS, min(25, len(scope_ids)))
    documents = _documents(passages, cards)
    wanted = [r["matter_id"] for r in ordered[: limit * 2]] + [d["matter_id"] for d in documents if d["matter_id"]]
    # One ACL-checked read decides what may be shown: matters, and the matters of documents and people.
    rows = _matter_rows(conn, list(dict.fromkeys(wanted)), member_id)
    matters = []
    for r in ordered:
        info = rows.get(r["matter_id"])
        if info is None:
            continue
        # The relation chip already says "asked about" / "similar"; keep only what it does not.
        why = [w for w in r["why"] if w != "asked about" and not (r["tier"] != "similar" and w.startswith("similar matter"))]
        matters.append({**info, "why": "; ".join(why), "relation": r["tier"], "score": round(r["score"], 3)})
        if len(matters) >= limit:
            break
    visible = set(rows)
    documents = [d for d in documents if d["matter_id"] in visible]

    people: dict[str, dict] = {}

    def person(p: dict, rank: int, why: str, matter: dict | None = None) -> None:
        row = people.setdefault(p["member_id"], {
            "member_id": p["member_id"], "name": p["name"], "role": p.get("role"), "office": p.get("office"),
            "on_matters": [], "why": [], "rank": rank,
        })
        row["rank"] = min(row["rank"], rank)
        if why not in row["why"]:
            row["why"].append(why)
        if matter and all(m["matter_id"] != matter["matter_id"] for m in row["on_matters"]):
            row["on_matters"].append(matter)

    codes = {m["matter_id"]: m["matter_code"] for m in matters}
    position = {m["matter_id"]: i for i, m in enumerate(matters[:3])}
    for t in _teams(conn, list(position)):
        role_on = t.get("role_on_matter") or "Team"
        # The top matter's team first (its lead leading), then the next matter's.
        rank = 2 * position[t["matter_id"]] + (0 if role_on.lower() == "lead" else 1)
        person(t, rank, f"{role_on} on {codes[t['matter_id']]}",
               {"matter_id": t["matter_id"], "matter_code": codes[t["matter_id"]], "role_on_matter": role_on})
    for a in _authors(conn, [d["document_id"] for d in documents]):
        if a["matter_id"] in visible:
            person(a, 6, f"author of {a['title']}")
    for e in experts:
        spec = ", ".join((e.get("specializations") or [])[:2]) or ", ".join((e.get("practice_areas") or [])[:2])
        person(e, -1 if people_first else 7, f"specialises in {spec}" if spec else "relevant experience",
               None)
        for m in e.get("matters") or []:
            if m["matter_id"] in visible:
                person(e, -1 if people_first else 7, f"{m.get('role_on_matter') or 'Team'} on {m['matter_code']}",
                       {k: m.get(k) for k in ("matter_id", "matter_code", "role_on_matter")})
    ranked = sorted(people.values(), key=lambda p: (p["rank"], -len(p["on_matters"]), p["member_id"]))[:MAX_PEOPLE]
    for p in ranked:
        p["why"] = "; ".join(p["why"][:2])
        p.pop("rank")

    return {"matters": matters, "documents": documents, "people": ranked,
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


def mark_cited(panel: dict[str, Any] | None, cited_ids: set[str]) -> None:
    """After grounding: flag the documents the answer cites and list them first."""
    if not panel or not panel.get("documents"):
        return
    for d in panel["documents"]:
        d["cited"] = d["document_id"].upper() in cited_ids
        if d["cited"]:
            d["why"] = "cited in the answer"
    panel["documents"].sort(key=lambda d: not d["cited"])
