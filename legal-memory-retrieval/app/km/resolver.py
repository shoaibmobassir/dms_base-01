"""Resolve which matter an unscoped question is about.

Title / code containment and capitalised party spans (engine_v2) miss
questions such as "the case where germany went against poland over the
factory" or "the series b deal where a seed investor sold its shares". This
resolver scores every accessible matter against the question using the
matter's identity fields — title, client, counterparty, facts, legal issues,
document titles — with IDF weighting (rare words like "chorzow" or
"northbridge" count, generic ones like "case" do not), case-insensitively.
When matter profile embeddings exist (``matter_profiles``), cosine similarity
is blended in so fact-only paraphrases with no shared words still rank.

It only *resolves* on a clear winner (absolute score and margin over the
runner-up). Otherwise it returns ranked candidates, which callers use as a
soft hint and to explain a "no matching matter" answer.
"""
from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from app.km.scope import ACL_SQL, _fetch

_GENERIC = frozenset(
    """a an and any are as at be between by can case cases concerning deal deals did dispute
    disputes do does done firm for from had has have how in into involving involved is it its
    matter matters me of on or our over please that the their them there these they this those
    to us was we went were what when where which who whom why with work worked about against
    advise advised advice act acted acting brought challenge challenged client clients side
    tell show find give list regarding related relating file filed filing documents document
    record records v vs versus""".split()
)
_FIELD_WEIGHTS = {"title": 1.0, "client": 1.0, "opposing": 1.0, "facts": 0.7, "issues": 0.6, "docs": 0.5}
_CACHE_TTL = 300.0

# Clear winner: good absolute score and a real gap to the runner-up.
RESOLVE_MIN = 0.55
RESOLVE_MARGIN = 0.12
# Dominant winner: modest score but nothing else comes close (paraphrases).
DOMINANT_MIN = 0.35
DOMINANT_MARGIN = 0.25
# Near-tied strong matters (e.g. two judgments in the same PCIJ case) scope together.
CLUSTER_MIN = 0.85
CLUSTER_BAND = 0.05
CLUSTER_MAX = 3


def _phrase(text: str) -> str:
    """Lowercase, punctuation/dash-free, single-spaced — for verbatim title containment."""
    return " " + " ".join(re.findall(r"[a-z0-9]+", (text or "").lower())) + " "


def _short_title(title: str) -> str:
    return re.split(r"\s+[—–-]\s+", title or "")[0].strip()


def _stems(text: str) -> set[str]:
    out = set()
    for tok in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if len(tok) < 3 and not tok.isdigit():
            continue
        if tok in _GENERIC:
            continue
        out.add(tok[:7])
    return out


@dataclass
class _Index:
    built_at: float
    fields: dict[str, dict[str, set[str]]]  # matter_id -> field -> stems
    phrases: dict[str, tuple[str, str]]  # matter_id -> (full title phrase, short title phrase)
    meta: dict[str, dict[str, Any]]
    idf: dict[str, float]
    n: int


_index: _Index | None = None
_lock = threading.Lock()


def _build_index(conn) -> _Index:
    rows = _fetch(
        conn,
        """
        SELECT m.matter_id, m.matter_code, m.title, cl.name AS client_name,
               coalesce(array_to_string(cl.aliases, ' '), '') AS aliases,
               coalesce(m.opposing_party, '') AS opposing_party,
               array_to_string(m.facts, ' ') AS facts,
               array_to_string(m.legal_issues, ' ') AS issues,
               m.practice_area, m.status,
               coalesce((SELECT string_agg(d.title, ' ') FROM documents d WHERE d.matter_id = m.matter_id), '') AS doc_titles
        FROM matters m JOIN clients cl ON cl.client_id = m.client_id
        """,
        {},
    )
    fields: dict[str, dict[str, set[str]]] = {}
    meta: dict[str, dict[str, Any]] = {}
    phrases: dict[str, tuple[str, str]] = {}
    df: dict[str, int] = {}
    for r in rows:
        f = {
            "title": _stems(r["title"]),
            "client": _stems(f"{r['client_name']} {r['aliases']}"),
            "opposing": _stems(r["opposing_party"]),
            "facts": _stems(r["facts"]),
            "issues": _stems(r["issues"]),
            "docs": _stems(re.sub(r"\.(docx?|pdf|txt)\b", " ", r["doc_titles"], flags=re.I)),
        }
        fields[r["matter_id"]] = f
        phrases[r["matter_id"]] = (_phrase(r["title"]), _phrase(_short_title(r["title"])))
        meta[r["matter_id"]] = {k: r[k] for k in ("matter_id", "matter_code", "title", "client_name", "opposing_party", "practice_area", "status")}
        for stem in set().union(*f.values()):
            df[stem] = df.get(stem, 0) + 1
    n = len(rows)
    idf = {s: math.log((n + 1) / (c + 1)) + 1.0 for s, c in df.items()}
    return _Index(time.monotonic(), fields, phrases, meta, idf, n)


def _get_index(conn) -> _Index:
    global _index
    with _lock:
        if _index is None or time.monotonic() - _index.built_at > _CACHE_TTL:
            _index = _build_index(conn)
        return _index


def invalidate() -> None:
    global _index
    with _lock:
        _index = None


def _accessible_ids(conn, member_id: str | None) -> set[str]:
    rows = _fetch(
        conn,
        f"SELECT p.matter_id FROM permissions p WHERE {ACL_SQL}",
        {"member_id": member_id},
    )
    return {r["matter_id"] for r in rows}


def _vector_scores(conn, question: str, ids: set[str]) -> dict[str, float]:
    """Cosine similarity to matter profile embeddings, if the table exists."""
    try:
        exists = _fetch(conn, "SELECT to_regclass('public.matter_profiles') IS NOT NULL AS ok", {})[0]["ok"]
        if not exists:
            return {}
        from app.retrieval.engine_v2 import _get_embedder

        vec = _get_embedder().encode([question])[0]
        literal = "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
        rows = _fetch(
            conn,
            """
            SELECT matter_id, 1 - (embedding <=> %(v)s::vector) AS sim
            FROM matter_profiles WHERE embedding IS NOT NULL AND matter_id = ANY(%(ids)s)
            ORDER BY (embedding <=> %(v)s::vector) + 0 LIMIT 25
            """,
            {"v": literal, "ids": list(ids)},
        )
        return {r["matter_id"]: float(r["sim"]) for r in rows}
    except Exception:
        return {}


@dataclass
class Resolution:
    resolved: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    method: str = "none"
    top_score: float = 0.0
    margin: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "resolved": [c["matter_id"] for c in self.resolved],
            "top_score": round(self.top_score, 3),
            "margin": round(self.margin, 3),
            "candidates": [
                {k: c.get(k) for k in ("matter_id", "matter_code", "title", "client_name", "score", "lexical", "vector")}
                for c in self.candidates[:5]
            ],
        }


def resolve_matter(conn, question: str, member_id: str | None, *, top: int = 8) -> Resolution:
    idx = _get_index(conn)
    q = _stems(question)
    if not q:
        return Resolution()
    allowed = _accessible_ids(conn, member_id)
    max_idf = math.log(idx.n + 1) + 1.0
    q_weight = sum(idx.idf.get(s, max_idf) for s in q)

    q_phrase = _phrase(question)
    lexical: dict[str, float] = {}
    for mid, f in idx.fields.items():
        if mid not in allowed:
            continue
        got = 0.0
        for s in q:
            w = max((_FIELD_WEIGHTS[name] for name, stems in f.items() if s in stems), default=0.0)
            if w:
                got += w * idx.idf.get(s, max_idf)
        if got:
            both_parties = bool(f["client"] & q) and bool(f["opposing"] & q)
            # A title quoted verbatim beats a longer sibling title sharing its words
            # ("Mavrommatis Jerusalem" vs "Mavrommatis Jerusalem Readaptation").
            full, short = idx.phrases[mid]
            verbatim = 0.3 if len(full) > 10 and full in q_phrase else (
                0.2 if len(short) > 10 and short in q_phrase else 0.0
            )
            lexical[mid] = min(1.3, got / q_weight + (0.15 if both_parties else 0.0) + verbatim)

    vector = _vector_scores(conn, question, allowed)
    pool = set(sorted(lexical, key=lexical.get, reverse=True)[:25]) | set(vector)
    scored = []
    for mid in pool:
        lex = lexical.get(mid, 0.0)
        vec = vector.get(mid)
        # Vector cosine for MiniLM profiles rarely exceeds ~0.7; rescale 0.25..0.65 → 0..1.
        vnorm = min(1.0, max(0.0, (vec - 0.25) / 0.40)) if vec is not None else None
        score = lex if vnorm is None else 0.65 * lex + 0.35 * vnorm
        scored.append({**idx.meta[mid], "score": round(score, 4), "lexical": round(lex, 4),
                       "vector": None if vec is None else round(vec, 4)})
    scored.sort(key=lambda c: (-c["score"], c["matter_id"]))
    res = Resolution(candidates=scored[:top])
    if not scored:
        return res
    res.top_score = scored[0]["score"]
    res.margin = scored[0]["score"] - (scored[1]["score"] if len(scored) > 1 else 0.0)
    basis = "profile" if vector else "lexical"
    cluster = [c for c in scored if c["score"] >= res.top_score - CLUSTER_BAND]
    if res.top_score >= RESOLVE_MIN and res.margin >= RESOLVE_MARGIN:
        res.resolved, res.method = [scored[0]], basis
    elif res.top_score >= DOMINANT_MIN and res.margin >= DOMINANT_MARGIN:
        res.resolved, res.method = [scored[0]], f"{basis}_dominant"
    elif res.top_score >= CLUSTER_MIN and len(cluster) <= CLUSTER_MAX:
        res.resolved, res.method = cluster, f"{basis}_cluster"
    else:
        res.method = "ambiguous" if res.top_score >= RESOLVE_MIN else "weak"
    return res
