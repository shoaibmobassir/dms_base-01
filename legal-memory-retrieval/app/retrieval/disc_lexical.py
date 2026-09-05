"""P5.6-C5.4 — Discriminative document-level lexical retrieval (theme-scoped).

Does not change production fusion/CE. Ablation-only until Doc R@20 clears a gate.

Variants (eval harness):
  A  broad OR-BM25 (C5.1 baseline)
  B  discriminative tokens + field weights
  C  B + phrase/concept lanes
  D  C + soft EL/ICA document_type prior
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from psycopg.rows import dict_row

from app.retrieval.matter_resolver import (
    MatterQueryRep,
    build_matter_query_rep,
    to_or_tsquery,
)

# Soft prior only — never a hard filter in production scoring.
EL_ICA_TYPES = frozenset({"Engagement Letter", "Initial Case Assessment"})

# Legal tokens that are often high-DF inside a theme; still kept if rare in-theme.
_ULTRA_COMMON_HINT = frozenset({
    "information", "agreement", "rights", "obligations", "party", "parties",
    "contract", "management", "investment", "engagement", "matter", "client",
    "legal", "advice", "advised", "letter", "document", "company", "ltd",
    "limited", "holdings", "services", "terms", "clause", "section",
})

_STOP = frozenset({
    "a", "an", "the", "and", "or", "of", "on", "in", "for", "to", "with",
    "we", "have", "had", "has", "been", "being", "is", "are", "was", "were",
    "do", "does", "did", "what", "which", "who", "whom", "this", "that",
    "as", "by", "from", "at", "about", "our", "their", "its", "it",
})


@dataclass
class FieldWeights:
    """Ablation knobs — not permanent production constants."""

    title: float = 10.0
    doc_type_field: float = 4.0
    metadata: float = 3.0
    body: float = 1.0
    phrase: float = 8.0
    concept: float = 6.0
    type_prior: float = 2.5


@dataclass
class DiscTokenBuckets:
    rare: list[str] = field(default_factory=list)
    moderate: list[str] = field(default_factory=list)
    common: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    term_df: dict[str, int] = field(default_factory=dict)
    n_docs: int = 0

    def discriminative_terms(self) -> list[str]:
        """Rare + moderate (+ concepts forced)."""
        seen: set[str] = set()
        out: list[str] = []
        for t in self.concepts + self.rare + self.moderate:
            key = t.lower().strip()
            if len(key) < 2 or key in seen:
                continue
            seen.add(key)
            out.append(t.strip())
        return out


@dataclass
class DocLexicalScore:
    document_id: str
    matter_id: str
    title: str
    document_type: str
    score: float
    title_score: float = 0.0
    phrase_score: float = 0.0
    concept_score: float = 0.0
    body_score: float = 0.0
    type_field_score: float = 0.0
    meta_score: float = 0.0
    type_prior_score: float = 0.0
    matched_tokens: list[str] = field(default_factory=list)
    matched_phrases: list[str] = field(default_factory=list)
    channel: str = "disc_lexical"


def _safe_tsquery(terms: Iterable[str], *, max_terms: int = 16) -> str | None:
    return to_or_tsquery(list(terms), max_terms=max_terms)


def _phrase_tsquery(phrases: list[str], *, max_phrases: int = 8) -> str | None:
    """AND within phrase, OR across phrases — prefers multi-word matches."""
    parts: list[str] = []
    for phrase in phrases[:max_phrases]:
        words = [
            w for w in re.findall(r"[A-Za-z0-9]+", phrase.lower())
            if w not in _STOP and len(w) > 1
        ]
        if len(words) >= 2:
            parts.append("(" + " & ".join(words[:4]) + ")")
        elif len(words) == 1 and words[0] not in _ULTRA_COMMON_HINT:
            parts.append(words[0])
    if not parts:
        return None
    return " | ".join(parts)


async def count_theme_docs(conn, matter_ids: list[str]) -> int:
    if not matter_ids:
        return 0
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE matter_id = ANY(%(mids)s)",
            {"mids": matter_ids},
        )
        row = await cur.fetchone()
        return int(row["n"])


async def theme_term_document_freqs(
    conn,
    matter_ids: list[str],
    terms: list[str],
) -> dict[str, int]:
    """Document frequency of each term inside theme matters (title+body)."""
    if not matter_ids or not terms:
        return {}
    uniq: list[str] = []
    seen: set[str] = set()
    for t in terms:
        key = t.lower().strip()
        if key in seen or len(key) < 2:
            continue
        seen.add(key)
        uniq.append(t.strip())

    sql = """
        WITH terms AS (
          SELECT LOWER(term) AS term
          FROM unnest(%(terms)s::text[]) AS term
        ),
        docs AS (
          SELECT
            setweight(to_tsvector('english', coalesce(d.title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(left(d.body, 4000), '')), 'D')
              AS tsv
          FROM documents d
          WHERE d.matter_id = ANY(%(mids)s)
        )
        SELECT t.term, COUNT(*)::int AS n
        FROM terms t
        JOIN docs d ON d.tsv @@ plainto_tsquery('english', t.term)
        GROUP BY t.term
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, {"mids": matter_ids, "terms": uniq})
        rows = await cur.fetchall()
    out = {t.lower(): 0 for t in uniq}
    for r in rows:
        out[str(r["term"])] = int(r["n"])
    return out


def classify_tokens(
    rep: MatterQueryRep,
    term_df: dict[str, int],
    n_docs: int,
    *,
    rare_max: float = 0.08,
    moderate_max: float = 0.40,
) -> DiscTokenBuckets:
    """Split query tokens by in-theme DF. Concepts always preferred."""
    buckets = DiscTokenBuckets(
        phrases=list(rep.phrases[:12]),
        concepts=list(rep.concepts),
        term_df=dict(term_df),
        n_docs=n_docs,
    )
    denom = max(n_docs, 1)
    candidates = list(dict.fromkeys(
        [t for t in rep.terms if t.lower() not in _STOP]
        + [w for p in rep.phrases for w in re.findall(r"[A-Za-z0-9]+", p)
           if w.lower() not in _STOP]
    ))

    for term in candidates:
        key = term.lower()
        df = term_df.get(key, 0)
        ratio = df / denom
        # Hint-boost: ultra-common vocabulary starts as common unless rare in-theme
        if key in _ULTRA_COMMON_HINT and ratio >= rare_max:
            buckets.common.append(term)
            continue
        if ratio <= rare_max:
            buckets.rare.append(term)
        elif ratio <= moderate_max:
            buckets.moderate.append(term)
        else:
            buckets.common.append(term)

    # Ensure concepts that are single tokens land in rare if missing
    for c in rep.concepts:
        if " " in c:
            continue
        if c.lower() not in {t.lower() for t in buckets.rare + buckets.moderate}:
            buckets.rare.append(c)

    return buckets


async def build_disc_buckets(
    conn,
    question: str,
    *,
    search_text: str | None,
    matter_ids: list[str],
) -> tuple[MatterQueryRep, DiscTokenBuckets]:
    rep = build_matter_query_rep(question, search_text=search_text)
    n_docs = await count_theme_docs(conn, matter_ids)
    probe = list(dict.fromkeys(rep.terms + [c for c in rep.concepts if " " not in c]))
    dfs = await theme_term_document_freqs(conn, matter_ids, probe[:24])
    buckets = classify_tokens(rep, dfs, n_docs)
    return rep, buckets


def _match_list(haystack: str, needles: list[str]) -> list[str]:
    low = haystack.lower()
    hits: list[str] = []
    for n in needles:
        if n.lower() in low:
            hits.append(n)
    return hits


async def score_documents_disc(
    conn,
    matter_ids: list[str],
    buckets: DiscTokenBuckets,
    *,
    weights: FieldWeights | None = None,
    use_phrase: bool = False,
    use_concept: bool = False,
    use_type_prior: bool = False,
    member_id: str | None = None,
    limit: int = 500,
) -> list[DocLexicalScore]:
    """Field-weighted lexical scores for all matching docs in theme matters."""
    if not matter_ids:
        return []
    w = weights or FieldWeights()
    disc_terms = buckets.discriminative_terms()
    disc_q = _safe_tsquery(disc_terms, max_terms=16)
    phrase_q = _phrase_tsquery(buckets.phrases) if use_phrase else None
    concept_q = _safe_tsquery(buckets.concepts, max_terms=12) if use_concept else None

    if not disc_q and not phrase_q and not concept_q:
        return []

    # Fallback: if discriminative empty, use concepts+phrases only
    if not disc_q:
        disc_q = concept_q or phrase_q

    use_phrase_eff = bool(use_phrase and phrase_q)
    use_concept_eff = bool(use_concept and concept_q)
    # Never pass NULL into to_tsquery — unused lanes reuse disc_q but flags stay off
    phrase_q_sql = phrase_q or disc_q
    concept_q_sql = concept_q or disc_q

    sql = """
        SELECT d.document_id, d.matter_id, d.title, d.document_type,
               coalesce(d.folder_path, '') AS folder_path,
               left(coalesce(d.body, ''), 4000) AS body_head,
               ts_rank_cd(
                 to_tsvector('english', coalesce(d.title, '')),
                 to_tsquery('english', %(disc_q)s)
               ) AS title_score,
               ts_rank_cd(
                 to_tsvector('english', coalesce(d.document_type, '')),
                 to_tsquery('english', %(disc_q)s)
               ) AS type_field_score,
               ts_rank_cd(
                 to_tsvector('english', coalesce(d.folder_path, '')),
                 to_tsquery('english', %(disc_q)s)
               ) AS meta_score,
               ts_rank_cd(
                 to_tsvector('english', coalesce(left(d.body, 6000), '')),
                 to_tsquery('english', %(disc_q)s)
               ) AS body_doc_score,
               CASE WHEN %(use_phrase)s THEN
                 ts_rank_cd(
                   setweight(to_tsvector('english', coalesce(d.title,'')), 'A') ||
                   setweight(to_tsvector('english', coalesce(left(d.body,6000),'')), 'B'),
                   to_tsquery('english', %(phrase_q)s)
                 )
               ELSE 0.0 END AS phrase_score,
               CASE WHEN %(use_concept)s THEN
                 ts_rank_cd(
                   setweight(to_tsvector('english', coalesce(d.title,'')), 'A') ||
                   setweight(to_tsvector('english', coalesce(left(d.body,6000),'')), 'B'),
                   to_tsquery('english', %(concept_q)s)
                 )
               ELSE 0.0 END AS concept_score
        FROM documents d
        JOIN permissions p ON p.matter_id = d.matter_id
        WHERE d.matter_id = ANY(%(matter_ids)s)
          AND (
            (%(member_id)s::text IS NULL)
            OR p.restricted = FALSE
            OR %(member_id)s::text = ANY (p.allowed_members)
          )
    """
    params = {
        "matter_ids": matter_ids,
        "member_id": member_id,
        "disc_q": disc_q,
        "phrase_q": phrase_q_sql,
        "concept_q": concept_q_sql,
        "use_phrase": use_phrase_eff,
        "use_concept": use_concept_eff,
    }
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(sql, params)
        rows = list(await cur.fetchall())

    scored: list[DocLexicalScore] = []
    for r in rows:
        title_s = float(r.get("title_score") or 0)
        type_s = float(r.get("type_field_score") or 0)
        meta_s = float(r.get("meta_score") or 0)
        body_s = float(r.get("body_doc_score") or 0)
        phrase_s = float(r.get("phrase_score") or 0) if use_phrase_eff else 0.0
        concept_s = float(r.get("concept_score") or 0) if use_concept_eff else 0.0
        dtype = r.get("document_type") or ""

        lex = (
            w.title * title_s
            + w.doc_type_field * type_s
            + w.metadata * meta_s
            + w.body * body_s
            + w.phrase * phrase_s
            + w.concept * concept_s
        )
        if lex <= 0:
            continue
        # Soft prior only on lexically matched docs (never a hard type filter).
        prior = w.type_prior if (use_type_prior and dtype in EL_ICA_TYPES) else 0.0
        total = lex + prior
        hay = " ".join([
            r.get("title") or "",
            dtype,
            r.get("folder_path") or "",
            r.get("body_head") or "",
        ])
        scored.append(DocLexicalScore(
            document_id=r["document_id"],
            matter_id=r["matter_id"],
            title=r.get("title") or "",
            document_type=dtype,
            score=total,
            title_score=title_s,
            phrase_score=phrase_s,
            concept_score=concept_s,
            body_score=body_s,
            type_field_score=type_s,
            meta_score=meta_s,
            type_prior_score=prior,
            matched_tokens=_match_list(hay, disc_terms)[:12],
            matched_phrases=_match_list(hay, buckets.phrases)[:8],
            channel="disc_lexical",
        ))

    scored.sort(key=lambda x: x.score, reverse=True)
    return scored[:limit]


def typed_ceiling(gold: set[str], docs: list[dict[str, Any]]) -> float:
    """Fraction of gold docs that are EL/ICA (diagnostic, not a filter)."""
    if not gold:
        return 0.0
    by_id = {d["document_id"]: d.get("document_type") for d in docs}
    typed = {g for g in gold if by_id.get(g) in EL_ICA_TYPES}
    # If types unknown, caller should pass gold type map separately
    return len(typed) / len(gold)


def score_to_rank_map(scored: list[DocLexicalScore]) -> dict[str, int]:
    return {s.document_id: i + 1 for i, s in enumerate(scored)}


def gold_diagnostics(
    gold: set[str],
    scored: list[DocLexicalScore],
    *,
    top_nongold: int = 3,
) -> list[dict[str, Any]]:
    """Per-gold component scores + a few top non-gold contrast rows."""
    by_id = {s.document_id: s for s in scored}
    ranks = score_to_rank_map(scored)
    rows: list[dict[str, Any]] = []
    for gid in sorted(gold):
        s = by_id.get(gid)
        if s is None:
            rows.append({
                "document_id": gid,
                "rank": None,
                "score": None,
                "missing_from_candidates": True,
            })
            continue
        rows.append({
            "document_id": gid,
            "rank": ranks.get(gid),
            "score": round(s.score, 4),
            "title": s.title,
            "document_type": s.document_type,
            "title_score": round(s.title_score, 4),
            "phrase_score": round(s.phrase_score, 4),
            "concept_score": round(s.concept_score, 4),
            "body_score": round(s.body_score, 4),
            "type_field_score": round(s.type_field_score, 4),
            "type_prior_score": round(s.type_prior_score, 4),
            "matched_tokens": s.matched_tokens,
            "matched_phrases": s.matched_phrases,
            "missing_from_candidates": False,
        })

    contrasts: list[dict[str, Any]] = []
    for s in scored:
        if s.document_id in gold:
            continue
        contrasts.append({
            "document_id": s.document_id,
            "rank": ranks[s.document_id],
            "score": round(s.score, 4),
            "title": s.title,
            "document_type": s.document_type,
            "title_score": round(s.title_score, 4),
            "phrase_score": round(s.phrase_score, 4),
            "concept_score": round(s.concept_score, 4),
            "body_score": round(s.body_score, 4),
            "type_prior_score": round(s.type_prior_score, 4),
            "matched_tokens": s.matched_tokens,
            "matched_phrases": s.matched_phrases,
        })
        if len(contrasts) >= top_nongold:
            break

    return [{"gold": rows, "top_nongold": contrasts}]
