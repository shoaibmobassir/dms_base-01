"""Review many documents at once: screen → map (one model call per document) → rows.

The Assistant cannot put hundreds of documents in one prompt, and should not read them one
by one. This engine answers the same questions for every document in a set:

  resolve  — the document set, ACL-checked (≤ settings.review_max_documents)
  screen   — no model: per question, rank each document's chunks by lexical + vector match
             inside the set; ``mode="screen"`` stops here ("which documents mention X?")
  map      — one fast-model JSON call per document with only its best passages for all
             questions; every quote is located in the passages (``verified``) or flagged
  cache    — cells are cached on (passage text, questions, model), so a re-run is instant
             and an edited document is re-read

Rows are returned in the input order and can be streamed through ``on_row`` as they finish.
The reduce step (a summary over the rows) is the caller's: the Assistant reasons over the
compact table, never over raw text.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from app.api.acl import ACL_CLAUSE, doc_acl, doc_read
from app.chat.verify_citations import locate_quote

logger = logging.getLogger(__name__)

PASSAGES_PER_QUESTION = 3
MAX_PASSAGE_CHARS = 1800

MAP_PROMPT = """You review ONE document for a lawyer. Below are numbered QUESTIONS and PASSAGES copied from the document.
Answer every question only from the passages.
For each question return: "q" (its number), "answer" (short: a value, a date, a name, yes/no, or one sentence),
"quote" (the exact words copied from a passage that support the answer, at most 40 words),
"passage" (the passage number the quote comes from), and "not_found": true when the passages do not answer it
(then answer and quote are empty). Never guess; never use outside knowledge.
Return JSON only: {"answers":[{"q":1,"answer":"...","quote":"...","passage":2,"not_found":false}]}"""

LLMCall = Callable[[list[dict[str, str]]], str]


def default_llm(model: str | None = None) -> LLMCall:
    from app.config import settings
    from app.llm.chat_gateway import chat_complete, writer_model

    chosen = model or settings.review_map_model or writer_model()

    def call(messages: list[dict[str, str]]) -> str:
        out = chat_complete(messages, model=chosen, temperature=0.0, max_tokens=2000, json_mode=True, timeout=60.0)
        return str(out.get("content") or "")

    return call


def resolve_documents(conn, document_ids: list[str], member_id: str | None, limit: int) -> list[dict]:
    """The requested documents the member may see, in the requested order."""
    rows = conn.execute(
        f"""
        SELECT d.document_id, d.title, d.document_type, d.doc_date, d.matter_id, d.matter_code
        FROM documents d LEFT JOIN permissions p ON p.matter_id = d.matter_id
        WHERE d.document_id = ANY(%(ids)s) AND {doc_read('d')}
        """,
        {"ids": list(dict.fromkeys(document_ids)), "member_id": member_id},
    ).fetchall()
    by_id = {r["document_id"]: dict(r) for r in rows}
    return [by_id[i] for i in dict.fromkeys(document_ids) if i in by_id][:limit]


def screen(conn, document_ids: list[str], questions: list[str], per_question: int = PASSAGES_PER_QUESTION) -> dict[str, dict]:
    """Per document: best passages per question and a relevance score, without any model call.

    Lexical match uses an OR of the question's terms (a passage need not contain every word);
    vector similarity catches paraphrase. Each document's first and last chunks are always kept:
    legal documents put title, parties and dates at the start and the execution / adoption
    details (dates, signatories, votes) at the end.
    """
    from app.config import settings
    # The retrieval engine's embedder: the one the server warms at start-up (a second
    # instance would load cold on the first review and cost ~8 s).
    from app.retrieval.engine_v2 import _get_embedder

    vectors = _get_embedder().encode(questions)
    queries = [_distinctive_query(conn, document_ids, q) for q in questions]
    out: dict[str, dict] = {d: {"passages": {}, "score": [0.0] * len(questions)} for d in document_ids}
    for qi, (question, vec) in enumerate(zip(queries, vectors)):
        rows = conn.execute(
            """
            WITH q AS (
              SELECT NULLIF(%(q)s, '')::tsquery AS tq
            ), scored AS (
              SELECT c.document_id, c.chunk_id, c.chunk_index, c.page_number, c.text,
                     coalesce(ts_rank_cd(coalesce(c.tsv_full, c.tsv), (SELECT tq FROM q)), 0) AS lex,
                     coalesce(1 - (c.embedding <=> %(vec)s::vector), 0) AS sem
              FROM chunks c
              WHERE c.document_id = ANY(%(ids)s) AND NOT c.is_parent
            )
            SELECT * FROM (
              SELECT scored.*, row_number() OVER (PARTITION BY document_id ORDER BY lex * 2 + sem DESC) AS rn,
                     max(chunk_index) OVER (PARTITION BY document_id) AS last_index
              FROM scored
            ) x WHERE rn <= %(k)s OR chunk_index = 0 OR (%(last)s AND chunk_index = last_index)
            """,
            {"q": question, "vec": str(list(vec)), "ids": document_ids, "k": per_question, "last": settings.review_include_last_chunk},
        ).fetchall()
        for r in rows:
            doc = out[r["document_id"]]
            doc["passages"].setdefault(r["chunk_id"], {
                "chunk_id": r["chunk_id"], "chunk_index": r["chunk_index"], "page": r["page_number"],
                "text": r["text"][:MAX_PASSAGE_CHARS],
            })
            if r["rn"] <= per_question:
                doc["score"][qi] = max(doc["score"][qi], float(r["lex"]) * 2 + float(r["sem"]))
    for doc in out.values():
        doc["passages"] = sorted(doc["passages"].values(), key=lambda p: p["chunk_index"])
    return out


def _distinctive_query(conn, document_ids: list[str], question: str) -> str:
    """An OR tsquery of the question's terms, without terms most documents in the set contain.

    ts_rank has no inverse document frequency: in "does this resolution concern Cyprus?" over a
    set of resolutions, "resolution" matches everywhere and outweighs "Cyprus". A term present in
    more than half of the set does not tell documents apart, so it is dropped — unless every
    term is that common, in which case the question is about something all documents have
    (a date, a meeting) and all terms are kept.
    """
    lexemes = conn.execute("SELECT unnest(tsvector_to_array(to_tsvector('english', %s))) AS l", (question,)).fetchall()
    terms = [r["l"] for r in lexemes]
    if len(terms) <= 1:
        return " | ".join(terms)
    rows = conn.execute(
        """
        SELECT t.term, count(DISTINCT c.document_id) AS df
        FROM unnest(%(terms)s::text[]) AS t(term)
        LEFT JOIN chunks c ON c.document_id = ANY(%(ids)s) AND coalesce(c.tsv_full, c.tsv) @@ to_tsquery('english', quote_literal(t.term))
        GROUP BY t.term
        """,
        {"terms": terms, "ids": document_ids},
    ).fetchall()
    common = {r["term"] for r in rows if r["df"] > len(document_ids) / 2}
    kept = [t for t in terms if t not in common] or terms
    return " | ".join(f"'{t}'" for t in kept)


def _map_prompt(questions: list[str], passages: list[dict], title: str) -> str:
    lines = [f"DOCUMENT: {title}", "", "QUESTIONS:"]
    lines += [f"{i}. {q}" for i, q in enumerate(questions, 1)]
    lines += ["", "PASSAGES:"]
    for i, p in enumerate(passages, 1):
        page = f" (page {p['page']})" if p.get("page") else ""
        lines.append(f"[{i}]{page} {' '.join(p['text'].split())}")
    return "\n".join(lines)


def _parse(raw: str) -> dict[int, dict]:
    raw = (raw or "").strip()
    if "{" in raw:
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    out = {}
    for a in data.get("answers") or []:
        try:
            out[int(a.get("q"))] = a
        except (TypeError, ValueError):
            continue
    return out


def map_document(doc: dict, questions: list[str], passages: list[dict], llm: LLMCall) -> list[dict]:
    """One model call for one document; every quote is checked against the passages."""
    try:
        answers = _parse(llm([{"role": "system", "content": MAP_PROMPT},
                              {"role": "user", "content": _map_prompt(questions, passages, doc.get("title") or "")}]))
        failed = False
    except Exception as exc:  # one document failing must not sink the batch
        logger.warning("[review] map failed for %s: %s", doc.get("document_id"), exc)
        answers, failed = {}, True
    cells = []
    for qi, question in enumerate(questions, 1):
        a = answers.get(qi) or {}
        not_found = bool(a.get("not_found")) or not str(a.get("answer") or "").strip()
        quote = str(a.get("quote") or "").strip()
        page, verified = None, False
        if quote and not not_found:
            order = [int(a["passage"]) - 1] if str(a.get("passage") or "").isdigit() else []
            order += [i for i in range(len(passages)) if i not in order]
            for i in order:
                if 0 <= i < len(passages) and locate_quote(passages[i]["text"], quote):
                    page, verified = passages[i].get("page"), True
                    break
        cells.append({
            "question": question,
            "answer": "" if not_found else str(a.get("answer")).strip(),
            "quote": quote if not not_found else "",
            "page": page,
            "verified": verified,
            "not_found": not_found,
            "error": "model call failed" if failed else None,
        })
    return cells


def _cache_key(doc_id: str, questions: list[str], passages: list[dict], model: str) -> str:
    h = hashlib.sha256()
    for part in [doc_id, model, *questions, *(p["text"] for p in passages)]:
        h.update(part.encode("utf-8", "ignore"))
        h.update(b"\x00")
    return h.hexdigest()


def review_documents(
    conn,
    document_ids: list[str],
    questions: list[str],
    member_id: str | None,
    *,
    mode: str = "full",
    llm: LLMCall | None = None,
    model: str | None = None,
    concurrency: int | None = None,
    use_cache: bool = True,
    on_row: Callable[[dict], None] | None = None,
) -> dict[str, Any]:
    """Answer ``questions`` for every document in the set (see module docstring)."""
    from app.cache.multi_tier import CacheTier, cache_get, cache_set
    from app.config import settings

    t0 = time.perf_counter()
    questions = [q.strip() for q in questions if q and q.strip()][:10]
    docs = resolve_documents(conn, document_ids, member_id, settings.review_max_documents)
    timings: dict[str, Any] = {"resolve_ms": round((time.perf_counter() - t0) * 1000, 1)}
    if not docs or not questions:
        return {"rows": [], "questions": questions, "documents": len(docs), "timings": timings}

    t = time.perf_counter()
    screened = screen(conn, [d["document_id"] for d in docs], questions)
    timings["screen_ms"] = round((time.perf_counter() - t) * 1000, 1)
    if mode == "screen":
        rows = []
        for d in docs:
            s = screened[d["document_id"]]
            rows.append({**d, "relevance": [round(x, 3) for x in s["score"]],
                         "best_passage": (s["passages"][0]["text"][:300] if s["passages"] else "")})
        rows.sort(key=lambda r: -max(r["relevance"]))
        timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return {"rows": rows, "questions": questions, "documents": len(docs), "mode": "screen", "timings": timings}

    chosen_model = model or settings.review_map_model
    call = llm or default_llm(chosen_model)
    rows: dict[str, dict] = {}
    stats = {"model_calls": 0, "cached": 0}
    first_row_ms: list[float] = []

    def work(doc: dict) -> dict:
        passages = screened[doc["document_id"]]["passages"]
        key = _cache_key(doc["document_id"], questions, passages, chosen_model)
        if use_cache:  # a fresh run skips reading the cache but still refreshes it
            hit = cache_get(CacheTier.REVIEW, key)
            if isinstance(hit, list):
                return {**doc, "cells": hit, "cached": True}
        started = time.perf_counter()
        cells = map_document(doc, questions, passages, call)
        if not any(c["error"] for c in cells):
            cache_set(CacheTier.REVIEW, key, value=cells)
        return {**doc, "cells": cells, "cached": False, "ms": round((time.perf_counter() - started) * 1000, 1)}

    t = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, concurrency or settings.review_concurrency), thread_name_prefix="review") as pool:
        futures = {pool.submit(work, d): d["document_id"] for d in docs}
        for fut in as_completed(futures):
            row = fut.result()
            rows[row["document_id"]] = row
            stats["cached" if row["cached"] else "model_calls"] += 1
            if not first_row_ms:
                first_row_ms.append(round((time.perf_counter() - t0) * 1000, 1))
            if on_row:
                on_row(row)
    timings["map_ms"] = round((time.perf_counter() - t) * 1000, 1)
    timings["first_row_ms"] = first_row_ms[0] if first_row_ms else None
    timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    ordered = [rows[d["document_id"]] for d in docs]
    cells = [c for r in ordered for c in r["cells"]]
    return {
        "rows": ordered, "questions": questions, "documents": len(docs), "mode": "full", "model": chosen_model,
        "stats": {**stats, "answered": sum(not c["not_found"] for c in cells),
                  "verified_quotes": sum(c["verified"] for c in cells), "errors": sum(bool(c["error"]) for c in cells)},
        "timings": timings,
    }
