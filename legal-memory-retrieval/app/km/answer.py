"""Ask the Firm orchestration: scope → records + passages → cited answer.

    question (+ optional structured scope)
      │
      ├─ resolve scope (explicit / "X: q" prefix / inline code)
      ├─ classify needs (people · overview · matter list)
      ├─ unscoped: resolve matter from identity fields (+ profile vectors)
      │
      ├─ evidence: matter records, team / people, client matter lists,
      │            ranked in-matter passages (or corpus passages if unscoped)
      │
      └─ LLM (JSON, temperature 0) → validate every cited id against the
         evidence → answer | not_found | deterministic records fallback
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.km import directory, passages as passage_mod
from app.km.panel import build_panel, mark_cited
from app.km.evidence import evidence_ids, matter_block, pack, person_block
from app.km.intent import classify
from app.km.docket import docket_scope_note, pin_docket
from app.km.resolver import resolve_matter
from app.km.scope import MatterRef, ScopeResolution, client_named_in, resolve_scope

logger = logging.getLogger(__name__)

SYSTEM = """You are Ask the Firm, the knowledge-management desk of a law firm. You answer lawyers' questions about the firm's own matters, documents, clients and people, using ONLY the evidence provided.

Evidence blocks are headed by an id in square brackets:
  [MTR-…] MATTER RECORD — structured matter data (parties, facts, issues, team, documents, deadlines)
  [MEM-…] PERSON — a firm member, their role, office, specialisations and matters
  [DOC-…] passage — text from a document
  CANDIDATE MATTERS — nearest records by name; they may not be what was asked about.

Rules:
1. Use only facts stated in the evidence. Never guess dates, amounts, names or outcomes.
2. Cite every factual sentence inline with the id(s) it came from, e.g. (DOC-E9058749C1) or (MTR-2026-00901) or (MEM-00001). Only cite ids that appear in the evidence.
3. Be direct: answer the question in the first sentence. Then give supporting detail. Use short paragraphs; use "- " bullet lists for lists of people, matters or documents. Keep answers under about 180 words unless the question asks for an overview, a summary or a list.
4. People questions: name each person with their role and role on the matter, citing their MEM id or the matter record.
5. Overview/"explain this" questions: cover what the matter is, the parties, key terms or issues, status, key documents and the team.
6. If the question is about a specific matter, party, event or document and none of the evidence concerns it, use status "not_found": say plainly that no matter in the records available to the user matches, and mention the closest candidate matters (cited) if any seem related.
7. If the evidence concerns the right matter but does not contain the requested fact, use status "insufficient" and say exactly what is missing, citing what you did find.

Return JSON only (no markdown fences):
{"status": "answered" | "not_found" | "insufficient", "key_finding": "<one or two sentences with citations>", "answer": "<full answer with inline citations>", "citations": ["<every id cited>"]}"""


def _llm(question: str, context: str, scope_note: str) -> tuple[str, str]:
    from app.llm.chat_gateway import chat_complete, chat_configured, preferred_provider, writer_model

    if not chat_configured():
        raise RuntimeError("chat_provider_not_configured")
    model = writer_model()
    user = f"{scope_note}Question: {question}\n\nEvidence:\n{context}"
    result = chat_complete(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        model=model,
        temperature=0.0,
        max_tokens=3000,
        json_mode=True,
        timeout=60.0,
    )
    return str(result.get("content") or ""), model


def _parse(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            payload = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _validate(payload: dict, allowed: set[str]) -> dict[str, Any]:
    status = str(payload.get("status") or "answered").lower()
    answer = str(payload.get("answer") or "").strip()
    key = str(payload.get("key_finding") or "").strip()
    listed = payload.get("citations") or []
    if isinstance(listed, str):
        listed = evidence_ids(listed)
    cited = [c for c in [str(x).upper() for x in listed] + evidence_ids(answer) + evidence_ids(key) if c in allowed]
    cited = list(dict.fromkeys(cited))
    invented = [c for c in evidence_ids(answer + " " + key) if c not in allowed]
    return {"status": status, "answer": answer, "key_finding": key, "citations": cited, "invented": invented}


def _fallback(intent, cards: list[dict], people: list[dict], passages: list[dict]) -> tuple[str, str, list[str]]:
    """Deterministic answer from structured records when the LLM is unavailable."""
    parts: list[str] = []
    cited: list[str] = []
    if intent.people:
        for c in cards[:3]:
            if c.get("team"):
                parts.append(f"Team on {c['title']} ({c['matter_id']}):\n" + "\n".join(
                    f"- {t['name']} — {t['role']}{', ' + t['role_on_matter'] if t.get('role_on_matter') else ''} ({t['member_id']})"
                    for t in c["team"]))
                cited += [c["matter_id"]] + [t["member_id"] for t in c["team"]]
        if people and not parts:
            parts.append("Firm members matching the question:\n" + "\n".join(
                f"- {p['name']} — {p['role']}, {p.get('office') or ''} ({p['member_id']})" for p in people))
            cited += [p["member_id"] for p in people]
    for c in cards[:5]:
        line = f"{c['title']} ({c['matter_id']}) — {c['matter_code']}, client {c.get('client_name')}, status {c.get('status')}."
        if c.get("facts"):
            line += " " + " ".join(c["facts"][:3])
        parts.append(line)
        cited.append(c["matter_id"])
    for h in passages[:3]:
        parts.append(f"{h['title']} ({str(h['document_id']).upper()}): " + " ".join(str(h['text']).split())[:400])
        cited.append(str(h["document_id"]).upper())
    body = "\n\n".join(parts)
    key = parts[0].split("\n")[0] if parts else ""
    return key, body, list(dict.fromkeys(cited))


def _unscoped_passages(conn, question: str, member_id: str | None) -> tuple[list[dict], dict]:
    from app.retrieval.engine import retrieve

    hits, latency = retrieve(conn, question, member_id, k=20)
    rows = [dict(h) for h in hits]
    return passage_mod.rank_passages(question, rows, limit=12, per_doc=3), latency


def _refs_from_candidates(cands: list[dict]) -> list[MatterRef]:
    return [
        MatterRef(**{k: c.get(k) for k in ("matter_id", "matter_code", "title", "client_name", "opposing_party", "practice_area", "status")},
                  method="resolver", score=float(c.get("score") or 0))
        for c in cands
    ]


@dataclass
class _Gathered:
    """Everything the answer step needs, produced by ``gather_evidence``."""

    base: dict[str, Any]
    timings: dict[str, Any]
    t0: float
    q: str
    sc: ScopeResolution
    intent: Any
    cards: list[dict] = field(default_factory=list)
    people: list[dict] = field(default_factory=list)
    passages: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    compact: bool = False
    done: bool = False  # the base is already the final result (no evidence / unknown scope)
    panel: dict[str, Any] | None = None
    docket_note: str = ""

    def panel_people(self) -> list[dict]:
        """Panel people not already in the context as a person record or a matter team."""
        known = {p["member_id"] for p in self.people} | {t["member_id"] for c in self.cards for t in c.get("team") or []}
        return [p for p in (self.panel or {}).get("people") or [] if p["member_id"] not in known]

    def context(self) -> tuple[str, set[str], str]:
        context, allowed = pack(self.cards, self.people, self.passages, self.candidates,
                                compact_cards=self.compact, budget_chars=16000)
        extra = self.panel_people()
        if extra:
            # Lets the answer name who worked on the matters behind the evidence, with a record citation.
            context += "\n\nPEOPLE CONNECTED TO THESE MATTERS AND DOCUMENTS:\n" + "\n".join(
                f"[{p['member_id']}] {p['name']}, {p['role']} — {p['why']}" for p in extra)
            allowed |= {p["member_id"].upper() for p in extra}
        note = ""
        if self.docket_note:
            note = self.docket_note
        elif self.sc.matters:
            note = f"The user scoped this question to: {self.sc.label} ({', '.join(self.sc.matter_ids[:12])}).\n"
        return context, allowed, note


def _new_base(raw_question: str, timings: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": raw_question, "answer": "", "key_finding": "", "citations": [], "abstained": True,
        "reason": "no_evidence", "provider": "none", "hits": [], "people": [], "matter_cards": [],
        "resolved_scope": None, "resolution": None, "km_intent": None, "latency_ms": timings,
        "panel": None,
    }


def gather_evidence(
    conn,
    question: str,
    member_id: str | None,
    scope: dict[str, str] | None = None,
) -> _Gathered:
    """Resolve scope and intent, then collect records and passages (no LLM)."""
    t0 = time.perf_counter()
    timings: dict[str, Any] = {}
    raw_question = (question or "").strip()
    base = _new_base(raw_question, timings)
    if not raw_question:
        return _Gathered(base, timings, t0, "", ScopeResolution(question=""), classify(""), done=True)

    t = time.perf_counter()
    sc: ScopeResolution = resolve_scope(conn, raw_question, scope, member_id)
    q = sc.question or raw_question
    intent = classify(q, scoped=bool(sc.matters))
    timings["scope_ms"] = round((time.perf_counter() - t) * 1000, 1)
    base["km_intent"] = intent.to_dict()

    if sc.unresolved:
        base.update(
            reason="scope_not_found",
            abstained=True,
            answer=f"No matter or client matching “{sc.label}” is available in the records you can access.",
            resolved_scope=sc.to_dict(),
        )
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return _Gathered(base, timings, t0, q, sc, intent, done=True)

    cards: list[dict] = []
    people: list[dict] = []
    passages: list[dict] = []
    candidates: list[dict] = []
    compact = False
    resolution = None
    engine_latency: dict = {}
    docket_note = ""

    t = time.perf_counter()
    if sc.kind == "matter":
        cards = directory.matter_cards(conn, sc.matter_ids[:3], member_id)
        passages = passage_mod.scoped_passages(conn, q, sc.matter_ids[:3], member_id, overview=intent.overview)
    elif sc.kind == "client":
        compact = True
        cards = directory.matter_cards(conn, sc.matter_ids[:12], member_id, max_docs=5)
        if not intent.matter_list and not intent.overview:
            passages = passage_mod.scoped_passages(conn, q, sc.matter_ids[:12], member_id, limit=10, per_doc=2)
    if sc.kind == "none" and intent.matter_list:
        # "which matters have we handled for Greece?" → every matter for that client.
        client_matters, client = client_named_in(conn, q, member_id)
        if client_matters:
            sc = ScopeResolution(question=q, kind="client", method="named_client", label=client,
                                 matters=client_matters)
            compact = True
            cards = directory.matter_cards(conn, sc.matter_ids[:25], member_id, max_docs=3)
    if sc.kind not in {"matter", "client"}:
        # Proceeding numbers pin before the stem resolver so a copy of the same
        # filing on another matter cannot widen the evidence.
        titled, copies, docket = pin_docket(conn, q, member_id)
        if titled and docket:
            pinned = titled[0]
            sc = ScopeResolution(
                question=q, kind="matter", method="docket", label=pinned.matter_code,
                matters=[pinned],
            )
            docket_note = docket_scope_note(docket, pinned, copies)
            cards = directory.matter_cards(conn, [pinned.matter_id], member_id)
            passages = passage_mod.scoped_passages(
                conn, q, [pinned.matter_id], member_id, overview=intent.overview,
            )
            timings["docket_ms"] = round((time.perf_counter() - t) * 1000, 1)
            base["docket"] = docket.label
            if copies:
                base["docket_copies"] = [
                    {"matter_id": c.matter_id, "matter_code": c.matter_code, "title": c.title}
                    for c in copies
                ]
        else:
            resolution = resolve_matter(conn, q, member_id)
            timings["resolver_ms"] = round((time.perf_counter() - t) * 1000, 1)
            if resolution.resolved and not (intent.people and not _mentions_matter(q)):
                ids = [c["matter_id"] for c in resolution.resolved]
                sc = ScopeResolution(question=q, kind="matter", method=f"resolver_{resolution.method}",
                                     matters=_refs_from_candidates(resolution.resolved),
                                     label=", ".join(c["matter_code"] for c in resolution.resolved))
                cards = directory.matter_cards(conn, ids, member_id)
                passages = passage_mod.scoped_passages(conn, q, ids, member_id, overview=intent.overview)
            else:
                if intent.matter_list:
                    strong = [c for c in resolution.candidates if c["score"] >= 0.35][:10]
                    if strong:
                        compact = True
                        cards = directory.matter_cards(conn, [c["matter_id"] for c in strong], member_id, max_docs=3)
                if not intent.people or _mentions_matter(q):
                    passages, engine_latency = _unscoped_passages(conn, q, member_id)
                    eng_scope = engine_latency.get("matter_scope") if isinstance(engine_latency.get("matter_scope"), dict) else {}
                    eng_ids = list(eng_scope.get("matter_ids") or [])
                    if not cards and 1 <= len(eng_ids) <= 2:
                        cards = directory.matter_cards(conn, eng_ids, member_id)
                if not cards and intent.people and resolution.method == "ambiguous":
                    # "who led X?" with near-tied matters: show each candidate's team.
                    close = [c for c in resolution.candidates if c["score"] >= resolution.top_score - 0.15][:3]
                    cards = directory.matter_cards(conn, [c["matter_id"] for c in close], member_id, max_docs=3)
                if not cards:
                    candidates = [c for c in resolution.candidates if c["score"] >= 0.2][:5]
    if intent.people and sc.kind != "matter":
        people = directory.people_search(conn, q, member_id)
    timings["evidence_ms"] = round((time.perf_counter() - t) * 1000, 1)
    experts = people if intent.people else [
        p for p in directory.people_search(conn, q, member_id, limit=3) if p["score"] >= 1.0
    ]
    panel = build_panel(
        conn, member_id=member_id, scope_ids=[c["matter_id"] for c in cards] or sc.matter_ids[:12],
        cards=cards, passages=passages, candidates=(resolution.candidates if resolution else []),
        experts=experts, people_first=intent.people and sc.kind != "matter",
    )
    timings["panel_ms"] = panel.pop("ms")
    timings["engine"] = {k: engine_latency.get(k) for k in ("intent", "matter_scope_ms", "parallel_wall_ms", "scoped", "cache", "channel_timeouts") if k in engine_latency}

    base["resolved_scope"] = sc.to_dict() if sc.matters else None
    base["resolution"] = resolution.to_dict() if resolution else None
    base["people"] = people
    base["matter_cards"] = [_card_summary(c) for c in cards]
    base["hits"] = passages
    base["panel"] = panel

    g = _Gathered(
        base, timings, t0, q, sc, intent, cards, people, passages, candidates, compact,
        panel=panel, docket_note=docket_note,
    )
    if not (cards or people or passages or candidates or panel["matters"] or panel["people"]):
        base.update(reason="no_evidence", abstained=True)
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        g.done = True
    return g



def _grounding_sources(g: "_Gathered"):
    from app.grounding import Source

    sources = [
        Source(key=str(h["document_id"]).upper(), document_id=str(h["document_id"]).upper(),
               title=str(h.get("title") or h["document_id"]), text=str(h.get("text") or ""),
               chunk_id=h.get("chunk_id"))
        for h in g.passages if h.get("text")
    ]
    sources += [Source(key=c["matter_id"], document_id=None, title=c["title"], text=matter_block(c))
                for c in g.cards]
    sources += [Source(key=p["member_id"], document_id=None, title=p["name"], text=person_block(p))
                for p in g.people]
    sources += [Source(key=p["member_id"], document_id=None, title=p["name"],
                       text=f"[{p['member_id']}] PERSON — {p['name']}, {p['role']}. {p['why']}.")
                for p in g.panel_people()]
    return sources


_FULL_TEXT_BUDGET = 400_000


def _full_documents(g: "_Gathered", conn: Any) -> list:
    """Whole documents of the matters in scope, for checking "the records do not contain X"."""
    from app.chat.tools.document_tools import fetch_document_pages, paged_text
    from app.grounding import Source

    if conn is None:
        return []
    wanted: dict[str, str] = {}
    for c in g.cards:
        for d in c.get("documents") or []:
            wanted.setdefault(str(d["document_id"]).upper(), str(d.get("title") or d["document_id"]))
    for h in g.passages:
        wanted.setdefault(str(h["document_id"]).upper(), str(h.get("title") or h["document_id"]))
    out, used = [], 0
    for doc_id, title in list(wanted.items())[:25]:
        try:
            text = paged_text(fetch_document_pages(conn, doc_id))
        except Exception as exc:  # a document that cannot be read is simply not searched
            logger.debug("full text unavailable for %s: %s", doc_id, exc)
            continue
        if used + len(text) > _FULL_TEXT_BUDGET:
            break
        used += len(text)
        out.append(Source(key=doc_id, document_id=doc_id, title=title, text=text))
    return out


def _ground(g: "_Gathered", base: dict[str, Any], conn: Any = None) -> None:
    """Check every sentence of the answer against the evidence and rewrite it.

    Sentences whose cited text does not support them are removed; document citations
    become [n] markers pointing at verified spans (``span_citations``).
    """
    from app.grounding import ground_answer, verifier_llms

    t = time.perf_counter()
    sources = _grounding_sources(g)
    full = _full_documents(g, conn) or sources
    llm = verifier_llms()
    # The key finding and the body are independent checks; run them side by side.
    with ThreadPoolExecutor(max_workers=2) as pool:
        key_job = pool.submit(ground_answer, base.get("key_finding") or "", ref_style="ids",
                              cited_keys=lambda u: u.refs, offered_quotes=lambda u: [], sources=sources,
                              llm=llm, removed_note=False, empty_message=None, full_sources=full)
        body_job = pool.submit(ground_answer, base.get("answer") or "", ref_style="ids",
                               cited_keys=lambda u: u.refs, offered_quotes=lambda u: [], sources=sources,
                               llm=llm, removed_note=False, full_sources=full)
        key, body = key_job.result(), body_job.result()
    # One numbering for the page: the key finding's citations come first.
    offset = len(key.citations)
    renum = {c["ref"]: c["ref"] + offset for c in body.citations}
    answer = re.sub(r"\[(\d{1,3})\]", lambda m: f"[{renum.get(int(m.group(1)), int(m.group(1)))}]", body.text)
    spans = key.citations + [{**c, "ref": renum[c["ref"]]} for c in body.citations]
    report = body.report()
    for k in ("checked", "supported", "partial", "contradicted", "removed"):
        report[k] = report.get(k, 0) + key.report().get(k, 0)
    report["removed_statements"] = key.removed + body.removed
    report["claims"] = key.report()["claims"] + report["claims"]
    kept = report["supported"] + report["partial"]
    base.update(answer=answer, key_finding=key.text, span_citations=spans, grounding=report)
    if report["checked"] and not kept:
        base.update(abstained=True, reason="not_supported_by_sources", status="insufficient",
                    answer="The records you can access do not contain a supported answer to this question.")
    g.timings["grounding_ms"] = round((time.perf_counter() - t) * 1000, 1)
    g.timings["grounding"] = {"key": key.timings, "body": body.timings}


def _claim_core(text: str) -> str:
    """Strip citations and punctuation so two wordings of the same claim compare equal."""
    t = re.sub(r"\[(\d{1,3}|DOC-[0-9A-F]+|MTR-[^\s)\]]+|MEM-\d+)\]", " ", text or "", flags=re.I)
    t = re.sub(r"\((?:DOC-|MTR-|MEM-)[^)]*\)", " ", t, flags=re.I)
    return re.sub(r"\W+", " ", t).lower().strip()


def _dedupe_key_finding(key: str, answer: str) -> tuple[str, str]:
    """Keep the key finding once: drop it from the body when the first paragraph repeats it."""
    key = (key or "").strip()
    answer = (answer or "").strip()
    if not key or not answer:
        return key, answer
    core = _claim_core(key)
    if len(core) < 12:
        return key, answer
    parts = re.split(r"\n\s*\n", answer, maxsplit=1)
    first = parts[0].strip()
    first_core = _claim_core(first)
    if first_core == core or first_core.startswith(core) or core.startswith(first_core):
        rest = parts[1].strip() if len(parts) > 1 else ""
        return key, rest
    # Also drop when the body's first sentence is the key finding.
    sentence = re.split(r"(?<=[.!?])\s+", first, maxsplit=1)
    if sentence and (_claim_core(sentence[0]) == core or core.startswith(_claim_core(sentence[0]))):
        remainder = (sentence[1] if len(sentence) > 1 else "").strip()
        if len(parts) > 1:
            remainder = (remainder + "\n\n" + parts[1]).strip() if remainder else parts[1].strip()
        return key, remainder
    return key, answer


def _finish(
    g: _Gathered, parsed: dict[str, Any] | None, provider: str, model: str | None, conn: Any = None,
) -> dict[str, Any]:
    """Accept a validated LLM answer, or fall back to a deterministic records answer."""
    base = g.base
    if model:
        base["model"] = model
    if parsed and parsed["answer"] and (parsed["citations"] or parsed["status"] == "not_found"):
        key, body = _dedupe_key_finding(parsed["key_finding"], parsed["answer"])
        base.update(
            answer=body, key_finding=key, citations=parsed["citations"],
            provider=provider, status=parsed["status"], invented_citations=parsed["invented"],
        )
        if parsed["status"] == "not_found":
            base.update(abstained=True, reason="no_matching_matter")
        elif parsed["status"] == "insufficient":
            base.update(abstained=False, reason="partial_evidence")
        else:
            base.update(abstained=False, reason=None)
        from app.config import settings

        if settings.grounding_enabled:
            try:
                _ground(g, base, conn)
            except Exception as exc:  # an unchecked answer is not shown as checked
                logger.error("Ask the Firm grounding failed: %s", exc)
                base.update(abstained=True, reason="grounding_failed", status="insufficient",
                            answer="The answer could not be checked against its sources, so it is not shown.",
                            key_finding="")
            else:
                key, body = _dedupe_key_finding(base.get("key_finding") or "", base.get("answer") or "")
                base.update(key_finding=key, answer=body)
    else:
        key, body, cited = _fallback(g.intent, g.cards, g.people, g.passages)
        base.update(
            answer=body, key_finding=key, citations=cited, abstained=not body,
            reason=None if body else "no_evidence",
            provider="records" if (g.cards or g.people) else f"extractive_after_{provider}",
            status="fallback",
        )
    cited = {str(c).upper() for c in base.get("citations") or [] if isinstance(c, str)}
    cited |= {str(c.get("document_id") or c.get("doc_id") or "").upper() for c in base.get("span_citations") or []}
    mark_cited(base.get("panel"), cited)
    g.timings["total_ms"] = round((time.perf_counter() - g.t0) * 1000, 1)
    return base


def ask_the_firm(
    conn,
    question: str,
    member_id: str | None,
    scope: dict[str, str] | None = None,
    *,
    use_llm: bool = True,
) -> dict[str, Any]:
    g = gather_evidence(conn, question, member_id, scope)
    if g.done:
        return g.base
    context, allowed, scope_note = g.context()
    parsed = None
    provider = "none"
    model = None
    t = time.perf_counter()
    if use_llm:
        try:
            raw, model = _llm(g.q, context, scope_note)
            payload = _parse(raw)
            if payload is not None:
                parsed = _validate(payload, allowed)
                from app.llm.chat_gateway import preferred_provider

                provider = preferred_provider()
        except Exception as exc:  # any provider failure → deterministic fallback
            logger.warning("Ask the Firm LLM failed: %s", exc)
            provider = "error"
    g.timings["llm_ms"] = round((time.perf_counter() - t) * 1000, 1)
    return _finish(g, parsed, provider, model, conn)


STREAM_FORMAT = """

Output format for this request (plain text, not JSON):
STATUS: answered | not_found | insufficient
KEY FINDING: <one or two sentences with citations>
---
<the full answer, markdown, with inline citations>"""

_HEADER_RE = re.compile(r"STATUS:\s*(\w+)\s*\n\s*KEY FINDING:\s*(.*?)\n\s*-{3,}\s*\n", re.S | re.I)


def _stream_llm(question: str, context: str, scope_note: str) -> tuple[Iterator[str], str]:
    from app.llm.chat_gateway import chat_configured, chat_stream, writer_model

    if not chat_configured():
        raise RuntimeError("chat_provider_not_configured")
    model = writer_model()
    system = SYSTEM.split("Return JSON only")[0].rstrip() + STREAM_FORMAT
    user = f"{scope_note}Question: {question}\n\nEvidence:\n{context}"
    return chat_stream(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=model, temperature=0.0, max_tokens=3000, timeout=90.0,
    ), model


def ask_the_firm_stream(
    conn,
    question: str,
    member_id: str | None,
    scope: dict[str, str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Ask the Firm as events: ``evidence`` → ``key_finding`` → ``delta``* → ``final``.

    ``final`` carries the same payload as ``ask_the_firm``; when the streamed
    answer fails validation (no valid citations) ``final`` replaces it with the
    deterministic records answer and ``replaced`` is true.
    """
    g = gather_evidence(conn, question, member_id, scope)
    yield {
        "type": "evidence",
        "resolved_scope": g.base.get("resolved_scope"),
        "km_intent": g.base.get("km_intent"),
        "resolution": g.base.get("resolution"),
        "people": g.base.get("people"),
        "matter_cards": g.base.get("matter_cards"),
        "panel": g.base.get("panel"),
        "hits": g.base.get("hits"),
        "evidence_ms": g.timings.get("evidence_ms"),
    }
    if g.done:
        yield {"type": "final", "result": g.base, "replaced": False}
        return
    context, allowed, scope_note = g.context()
    t = time.perf_counter()
    text = ""
    header: re.Match | None = None
    sent = 0
    provider, model = "none", None
    try:
        deltas, model = _stream_llm(g.q, context, scope_note)
        from app.llm.chat_gateway import preferred_provider

        provider = preferred_provider()
        for delta in deltas:
            text += delta
            if header is None:
                header = _HEADER_RE.search(text)
                if header is None:
                    continue
                g.timings["first_token_ms"] = round((time.perf_counter() - t) * 1000, 1)
                yield {"type": "key_finding", "status": header.group(1).lower(), "text": header.group(2).strip()}
                sent = header.end()
            if len(text) > sent:
                yield {"type": "delta", "text": text[sent:]}
                sent = len(text)
    except Exception as exc:  # provider failure mid-stream → deterministic answer in `final`
        logger.warning("Ask the Firm stream failed: %s", exc)
        provider = "error"
    g.timings["llm_ms"] = round((time.perf_counter() - t) * 1000, 1)
    parsed = None
    if header is not None:
        payload = {"status": header.group(1), "key_finding": header.group(2).strip(), "answer": text[header.end():].strip()}
        parsed = _validate(payload, allowed)
    elif text.strip() and provider in {"bedrock", "azure"}:
        parsed = _validate({"status": "answered", "key_finding": "", "answer": text.strip()}, allowed)
    yield {"type": "verifying"}
    result = _finish(g, parsed, provider, model, conn)
    yield {"type": "final", "result": result, "replaced": result.get("status") == "fallback"}


_MATTER_WORDS_RE = re.compile(
    r"\b(this matter|the matter|matter|case|deal|transaction|petition|work(?:ed|ing)? on|our work)\b", re.I,
)


def _mentions_matter(q: str) -> bool:
    return bool(_MATTER_WORDS_RE.search(q))


def _card_summary(c: dict) -> dict:
    return {
        "matter_id": c["matter_id"], "matter_code": c["matter_code"], "title": c["title"],
        "client_name": c.get("client_name"), "opposing_party": c.get("opposing_party"),
        "practice_area": c.get("practice_area"), "status": c.get("status"), "court": c.get("court"),
        "matter_type": c.get("matter_type"), "jurisdiction": c.get("jurisdiction"), "office": c.get("office"),
        "opened_date": str(c["opened_date"]) if c.get("opened_date") else None,
        "closed_date": str(c["closed_date"]) if c.get("closed_date") else None,
        "claim_amount": str(c["claim_amount"]) if c.get("claim_amount") is not None else None,
        "outcome": c.get("outcome"),
        "facts": list(c.get("facts") or [])[:6], "legal_issues": list(c.get("legal_issues") or [])[:6],
        "team": c.get("team") or [], "document_count": c.get("document_count", 0),
        "documents": [{k: (str(v) if k == "doc_date" and v else v) for k, v in d.items()} for d in (c.get("documents") or [])[:10]],
        "deadlines": [{k: (str(v) if k == "due_date" else v) for k, v in d.items()} for d in (c.get("deadlines") or [])[:5]],
    }
