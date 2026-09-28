"""Claim-level grounding: a sentence is shown as sourced only if the cited text entails it.

Existence checks (is the quote really in the document?) are necessary but not sufficient:
"The Board approved the transfer on 12 September 2026" citing "the meeting was held on
12 September 2026" quotes the document faithfully and still misleads. This module decides,
per sentence, whether the cited span *supports* the sentence, and repairs the citation
from the same sources when a better span exists.

Pipeline, per answer (one LLM call, batched over all sentences):
  1. candidates  — sentences from the cited sources ranked by lexical overlap with the claim
                   (uncited sentences search every source, so a correct fact can be auto-cited)
  2. judge       — a model other than the generator labels each unit claim / non_claim and
                   picks the candidate ids that together entail it
  3. guard       — numbers, dates and amounts in the claim must appear in the chosen spans;
                   otherwise the verdict is downgraded (the judge cannot wave a figure through)
  4. offsets     — each chosen span is re-located in its source for exact char offsets

Our design (clean-room): requirement = "every displayed factual sentence is entailed by the
evidence shown for it"; see docs/plan/GROUNDING_ROADMAP.md.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from app.chat.verify_citations import locate_quote

logger = logging.getLogger(__name__)

SUPPORTED, PARTIAL, UNSUPPORTED, CONTRADICTED = "supported", "partial", "unsupported", "contradicted"

_PAGE_MARKER = re.compile(r"^\[Page (\d+)\]$", re.MULTILINE)
_SENT_END = re.compile(r"(?<=[.;!?])\s+(?=[\"'(\[]?[A-Z0-9])")
_ABBREV_END = re.compile(
    r"\b(?:v|vs|No|Nos|Ltd|Pvt|Rs|Co|Corp|Inc|Art|Arts|Reg|Regs|Sec|Cl|para|paras|p|pp|Mr|Ms|Dr|Anr|Ors|viz|i\.e|e\.g|etc|S)\.$",
    re.I,
)
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an the of to in on at by for from with and or as is are was were be been being this that these those "
    "it its which who whom whose under shall may will not no any all such other than into upon per said "
    "has have had do does did can could would should their there here also".split()
)
_MONTHS = ("january february march april may june july august september october november december").split()


@dataclass
class Source:
    """A document (or firm record) whose text a claim may cite."""

    key: str                     # caller's label: "doc-3" in chat, the DOC id in Ask the Firm
    document_id: str | None
    title: str
    text: str
    chunk_id: str | None = None  # set when the source is a single retrieved passage


@dataclass
class Span:
    key: str
    document_id: str | None
    title: str
    quote: str
    start: int
    end: int
    page: int | None = None
    chunk_id: str | None = None


@dataclass
class Claim:
    """One displayed unit (sentence or list item) and the sources it cites."""

    text: str
    cited: list[str] = field(default_factory=list)        # source keys the answer cited
    quotes: list[str] = field(default_factory=list)       # quotes the generator offered, if any
    kind: str = "claim"                                    # claim | non_claim | absence
    under_suggestion: bool = False                         # a list item under "you could refer to:"
    support: str | None = None
    spans: list[Span] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("quotes", None)
        return d


# ---------------------------------------------------------------------------
# Source segmentation and candidate retrieval
# ---------------------------------------------------------------------------

def segment(text: str) -> list[tuple[int, int]]:
    """Sentence spans (start, end) over a source, never crossing a page marker, blank line or heading.

    Very long sentences (statutory provisos) are kept whole: splitting them would cut meaning.
    """
    spans: list[tuple[int, int]] = []
    # Blank out page markers (same length, so offsets still index the original text).
    masked = _PAGE_MARKER.sub(lambda m: " " * len(m.group(0)), text)
    for block in re.finditer(r"[^\n]*\S[^\n]*(?:\n[^\n]*\S[^\n]*)*", masked):
        chunk, base = block.group(0), block.start()
        for sub_s, sub_e in _heading_split(chunk):
            _sentences(chunk[sub_s:sub_e], base + sub_s, spans)
    return spans


_HEADING_WORD = re.compile(r"^(?:ARTICLE|SECTION|CLAUSE|SCHEDULE|EXHIBIT|ANNEX|PART|CHAPTER)\b", re.I)
_CONNECTOR_END = re.compile(r"(?:[,;:(\-–—]|\b(?:of|the|and|or|to|in|for|by|with|a|an|on|at|under|per|as))$", re.I)


def _heading_split(block: str) -> list[tuple[int, int]]:
    """Split heading lines ("Approval of transfer of shares") from the paragraph under them.

    PDF text wraps mid-sentence, so a newline only ends a unit when the line before it is
    short, does not end in a connector, and the next line starts like a new sentence.
    """
    out: list[tuple[int, int]] = []
    start = 0
    line_start = 0
    for m in re.finditer(r"\n", block):
        line = block[line_start:m.start()].strip()
        nxt = block[m.end():m.end() + 1]
        line_start = m.end()
        heading_line = bool(_HEADING_WORD.match(line)) and len(line) < 150
        short_line = len(line) < 60 and not _CONNECTOR_END.search(line) and not line.endswith(".")
        if line and (heading_line or short_line) and (nxt.isupper() or nxt.isdigit() or nxt in "(\"'"):
            out.append((start, m.start()))
            start = m.end()
    out.append((start, len(block)))
    return [(s, e) for s, e in out if block[s:e].strip()]


def _sentences(chunk: str, base: int, spans: list[tuple[int, int]]) -> None:
    """Append sentence ranges of ``chunk`` (offset by ``base``) to ``spans``."""
    pos = 0
    pieces: list[tuple[int, int]] = []
    for m in _SENT_END.finditer(chunk):
        if _ABBREV_END.search(chunk[pos:m.start()].rstrip()):
            continue
        pieces.append((pos, m.start()))
        pos = m.end()
    pieces.append((pos, len(chunk)))
    for s, e in pieces:
        seg = chunk[s:e].strip()
        if len(seg) < 12:
            continue
        lead = len(chunk[s:e]) - len(chunk[s:e].lstrip())
        spans.append((base + s + lead, base + s + lead + len(seg)))


def _norm_number(tok: str) -> str:
    return tok.replace(",", "").lstrip("0") or "0"


_DOTTED_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")
_SCALED = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(crores?|lakhs?|lacs?|million|billion)\b", re.I)
_SCALE = {"crore": 10**7, "lakh": 10**5, "lac": 10**5, "million": 10**6, "billion": 10**9}


def key_facts(text: str) -> set[str]:
    """Numbers, amounts, dates and percentages, normalised so equal values compare equal.

    "12.09.2026" and "12 September 2026" both give {"12", "september", "2026"};
    "186 crore" and "186,00,00,000" both give "1860000000".
    """
    low = text.lower()
    facts: set[str] = set()

    def dates(m: re.Match[str]) -> str:
        d, mth, y = m.groups()
        if 1 <= int(mth) <= 12:
            facts.update({_norm_number(d), _MONTHS[int(mth) - 1], y})
        return " "

    low = _DOTTED_DATE.sub(dates, low)

    def scaled(m: re.Match[str]) -> str:
        unit = m.group(2).rstrip("s")
        try:
            value = float(m.group(1).replace(",", "")) * _SCALE[unit]
            facts.add(str(int(round(value))))
        except (KeyError, ValueError):
            pass
        return " "

    low = _SCALED.sub(scaled, low)
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", low):
        facts.add(_norm_number(m.group(0).rstrip(".,")))
    for month in _MONTHS:
        if re.search(rf"\b{month}\b", low):
            facts.add(month)
    return facts


def facts_of_evidence(text: str) -> set[str]:
    return key_facts(text)


def missing_facts(claim: str, evidence: str) -> set[str]:
    """Figures in the claim that do not appear in the evidence (after normalisation)."""
    need = key_facts(claim) - {"1"}  # list numbering and "one" noise
    have = facts_of_evidence(evidence)
    # Amounts written with Indian grouping (1,20,00,000) and plain (12000000) compare equal.
    return {f for f in need if f not in have}


def _stem(w: str) -> str:
    """Light stemming so "shares"/"share" and "approved"/"approval" meet in ranking."""
    for suffix in ("ation", "ing", "ed", "al", "es", "s"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


def _terms(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


# A span that is only a heading or title ("Approval of transfer of shares") names a topic; it
# cannot state that something happened.
def is_heading(text: str) -> bool:
    t = " ".join(text.split())
    return len(t) < 90 and len(t.split()) <= 12 and not re.search(r"[.;:,\"”]$", t)


_NEGATION = re.compile(
    r"\b(?:not|no|none|nothing|neither|nor|without|absent|cannot|could not|unable|lacks?|silent|"
    r"does not|do not|did not|is not|are not|there is no|there are no)\b|n't\b",
    re.I,
)
_SUGGESTION = re.compile(
    r"\b(?:let me know|would you like|you may wish|you (?:could|should|may|might) (?:refer|consult|upload|provide|check)|"
    r"refer to|please|upload|I can|I will|I'll|I would|if you (?:need|want|have)|would (?:typically |usually )?be found in|"
    r"(?:you )?would need|consult)\b",
    re.I,
)
_FACTUAL_CUE = re.compile(r"\d|\b(?:Regulations?|Section|Act|Rules?|Article|Clause|Order|Schedule)\b")


def _guard_kind(kind: str, text: str, under_suggestion: bool = False) -> str:
    """The verifier may not wave a factual sentence past verification by labelling it."""
    if kind == "absence" and not _NEGATION.search(text):
        return "claim"
    # A bare name in a "you could refer to:" list is a pointer; one that says what the law provides is not.
    pointer = under_suggestion and len(text.split()) <= 14 and not re.search(r"\b(?:provides?|requires?|governs?|means|states?)\b", text)
    if kind == "non_claim" and _FACTUAL_CUE.search(text) and not (
        pointer or _SUGGESTION.search(text) or _NEGATION.search(text) or text.rstrip().endswith("?")
    ):
        return "claim"
    return kind


def rank_candidates(claim: str, sources: list[Source], k: int) -> list[tuple[Source, int, int, float]]:
    q = _terms(claim)
    if not q:
        return []
    qset = set(q)
    nums = key_facts(claim)
    scored: list[tuple[Source, int, int, float]] = []
    for src in sources:
        segs = segment(src.text)
        for n, (s, e) in enumerate(segs):
            seg = src.text[s:e]
            overlap = len(qset & set(_terms(seg)))
            if not overlap:
                continue
            num_hits = len(nums & facts_of_evidence(seg))
            score = overlap / (len(qset) ** 0.5) + 1.5 * num_hits
            scored.append((src, s, e, score))
            if is_heading(seg) and n + 1 < len(segs):
                # A heading names a topic; the paragraph under it is what states anything.
                ns, ne = segs[n + 1]
                scored.append((src, ns, ne, score * 0.95))
    scored.sort(key=lambda t: -t[3])
    seen: set[tuple[str, int]] = set()
    out = []
    for item in scored:
        sig = (item[0].key, item[1])
        if sig not in seen:
            seen.add(sig)
            out.append(item)
    return out[:k]


def _page_at(text: str, offset: int) -> int | None:
    page = None
    for m in _PAGE_MARKER.finditer(text):
        if m.start() > offset:
            break
        page = int(m.group(1))
    return page


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------

JUDGE_PROMPT = """You check a legal answer before a lawyer sees it. Each numbered UNIT is one sentence of the answer. \
Under it are CANDIDATE passages copied verbatim from the firm's documents and records.

For every unit return:
- kind:
  "claim" if it states a fact about documents, parties, dates, amounts, clauses, arguments, a matter, or what a \
law or regulation says;
  "absence" if it only says that a document or the records do not contain, mention or show something;
  "non_claim" for headings, transitions, questions, offers of help, or suggestions of what to read or do next \
(a suggestion that also states what a law provides is a claim).
- elements (claims only): split the claim into its separate factual elements — each actor+action, date, amount, \
party, clause number, place, condition, and each item of a list or comparison. For each element give "use": the \
candidate ids whose text states that element. Leave "use" empty when no candidate states it. A candidate that \
only mentions the same date or topic does not state an action (a meeting "held on 12 September" does not state \
that anything was approved). A heading alone never states an element. Use only candidates listed under that unit.
- verdict: "supported" if every element is stated by its candidates; "partial" if some elements are stated and \
the rest are simply not addressed; "contradicted" if any candidate states something different (another date, \
amount, place, party, rule); "unsupported" if no element is stated.
- missing: for partial or unsupported, the elements with no candidate.

Judge only by the candidate text. Your own knowledge of the law does not count: a correct statement of law with \
no supporting candidate is "unsupported".

Return JSON only:
{"units":[{"i":1,"kind":"claim","elements":[{"element":"Board approved the transfer","use":["c4"]},\
{"element":"on 12 September 2026","use":["c2"]}],"verdict":"supported","missing":""}]}"""


LLMCall = Callable[[list[dict[str, str]]], str]


def _build_prompt(claims: list[Claim], pools: list[list[tuple[Source, int, int, float]]]) -> tuple[str, dict[str, tuple[Source, int, int]]]:
    lines: list[str] = []
    ids: dict[str, tuple[Source, int, int]] = {}
    n = 0
    for i, (claim, pool) in enumerate(zip(claims, pools), 1):
        lines.append(f"UNIT {i}: {claim.text}")
        if not pool:
            lines.append("  (no candidates)")
        for src, s, e, _ in pool:
            n += 1
            cid = f"c{n}"
            ids[cid] = (src, s, e)
            snippet = " ".join(src.text[s:e].split())
            lines.append(f"  {cid} [{src.title}]: {snippet}")
        lines.append("")
    return "\n".join(lines), ids


def _parse(raw: str) -> dict[int, dict[str, Any]]:
    raw = (raw or "").strip()
    if "{" in raw:
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    out: dict[int, dict[str, Any]] = {}
    for u in data.get("units") or []:
        try:
            out[int(u.get("i"))] = u
        except (TypeError, ValueError):
            continue
    return out


def _span(src: Source, s: int, e: int) -> Span:
    return Span(
        key=src.key, document_id=src.document_id, title=src.title,
        quote=" ".join(src.text[s:e].split()), start=s, end=e,
        page=_page_at(src.text, s), chunk_id=src.chunk_id,
    )


def _generator_spans(claim: Claim, scoped: list[Source]) -> list[tuple[Source, int, int, float]]:
    """The generator's own quotes, located exactly, go first in the candidate pool."""
    found: list[tuple[Source, int, int, float]] = []
    for src in scoped:
        for q in claim.quotes:
            loc = locate_quote(src.text, q)
            if loc:
                found.append((src, loc.start, loc.end, 99.0))
    return found


Pool = list[tuple[Source, int, int, float]]
CandidateIds = dict[str, tuple[Source, int, int]]


def _judge(claims: list[Claim], pools: list[Pool], llm: LLMCall) -> tuple[dict[int, dict[str, Any]], CandidateIds]:
    """One judge call over a batch of units; an empty verdict map means the call failed."""
    body, ids = _build_prompt(claims, pools)
    try:
        raw = llm([{"role": "system", "content": JUDGE_PROMPT}, {"role": "user", "content": body}])
        return _parse(raw), ids
    except Exception as exc:  # fail closed: nothing is marked supported without a verdict
        logger.warning("[grounding] judge failed: %s", exc)
        return {}, ids


def _judge_sharded(
    claims: list[Claim], pools: list[Pool], llm: LLMCall, batch_size: int,
) -> list[tuple[dict[str, Any] | None, CandidateIds]]:
    """Per claim: its verdict (or None) and the candidate ids it may use.

    The judge decides each unit only from the candidates listed under it, so units can be
    split across parallel calls. Output tokens dominate the call's time, so several short
    calls finish well before one long one. A failed shard fails closed for its units only.
    """
    from concurrent.futures import ThreadPoolExecutor

    size = batch_size if batch_size > 0 else len(claims)
    shards = [(claims[i:i + size], pools[i:i + size]) for i in range(0, len(claims), size)]
    if len(shards) == 1:
        results = [_judge(*shards[0], llm)]
    else:
        with ThreadPoolExecutor(max_workers=min(len(shards), 8)) as pool:
            results = list(pool.map(lambda sh: _judge(sh[0], sh[1], llm), shards))
    out: list[tuple[dict[str, Any] | None, CandidateIds]] = []
    for (shard_claims, _), (verdicts, ids) in zip(shards, results):
        out += [(verdicts.get(i), ids) for i in range(1, len(shard_claims) + 1)]
    return out


def verify_claims(
    claims: list[Claim],
    sources: list[Source],
    llm: LLMCall,
    *,
    per_claim: int = 6,
    auto_cite: bool = True,
    batch_size: int | None = None,
) -> list[Claim]:
    """Label each claim supported / partial / unsupported and attach verified spans.

    ``batch_size`` units go to each judge call (0 = one call for all); default from
    ``settings.grounding_verify_batch``.
    """
    if not claims:
        return claims
    if batch_size is None:
        from app.config import settings

        batch_size = settings.grounding_verify_batch
    pools: list[list[tuple[Source, int, int, float]]] = []
    for c in claims:
        cited = set(c.cited)
        scoped = [s for s in sources if s.key in cited]
        # A cited document is searched first; the rest of the evidence can still supply
        # a supporting span (the generator often cites the right fact to the wrong source).
        pool = _generator_spans(c, scoped or sources) + rank_candidates(c.text, scoped, per_claim)
        if auto_cite:
            pool += rank_candidates(c.text, [s for s in sources if s.key not in cited], 3 if scoped else per_claim)
        # Deduplicate overlapping picks from the same source.
        seen: set[tuple[str, int]] = set()
        uniq = []
        for item in pool:
            sig = (item[0].key, item[1])
            if sig not in seen:
                seen.add(sig)
                uniq.append(item)
        pools.append(uniq[: per_claim + 4])

    for c, (v, ids) in zip(claims, _judge_sharded(claims, pools, llm, batch_size)):
        if v is None:
            c.support, c.reason = UNSUPPORTED, "not verified"
            c.kind = "claim"
            continue
        kind = _guard_kind(str(v.get("kind") or "claim"), c.text, c.under_suggestion)
        c.kind = kind if kind in ("non_claim", "absence") else "claim"
        if c.kind != "claim":
            # Absence cannot be proven by a citation; pointing at an unrelated clause would mislead.
            c.support = None
            continue
        elements = [e for e in v.get("elements") or [] if isinstance(e, dict)]

        def states_fact(x: str) -> bool:
            src, s, e = ids[x]
            # Firm records (matter, person: no document_id) are short "Field: value" lines that
            # look like headings but are data; the heading rule is for document text only.
            return src.document_id is None or not is_heading(src.text[s:e])

        def usable(e: dict) -> list[str]:
            got = [x for x in e.get("use") or [] if x in ids]
            # An element resting only on headings has no source that states it.
            return got if any(states_fact(x) for x in got) else []

        picked: list[str] = []
        for e in elements:
            picked += usable(e)
        picked += [x for x in v.get("use") or [] if x in ids]  # older single-list form
        chosen = [ids[x] for x in dict.fromkeys(picked)]
        c.spans = [_span(src, s, e) for src, s, e in chosen]
        verdict = v.get("verdict")
        c.support = verdict if verdict in (SUPPORTED, PARTIAL, UNSUPPORTED, CONTRADICTED) else UNSUPPORTED
        c.reason = str(v.get("missing") or "")
        unmapped = [str(e.get("element")) for e in elements if not usable(e)]
        if c.support == SUPPORTED and unmapped:
            # The verdict must agree with the element map: an element with no source is not supported.
            c.support, c.reason = PARTIAL, "no source for: " + "; ".join(unmapped)
        if not c.spans and c.support != CONTRADICTED:
            c.support = UNSUPPORTED
        elif c.support == SUPPORTED:
            gap = missing_facts(c.text, " ".join(sp.quote for sp in c.spans))
            if gap:
                c.support, c.reason = PARTIAL, "figures not in cited text: " + ", ".join(sorted(gap))
    return claims


ABSENCE_PROMPT = """Each numbered STATEMENT says that documents do not contain, mention or show something. \
Under it are CANDIDATE passages from the full text of those documents.

For each statement decide whether any candidate actually states the thing the statement says is missing \
(for example, a statement "no disclosure about employees" is wrong if a candidate discloses employee resignations). \
A candidate that only mentions the same topic without stating the missing thing does not count. Headings alone \
do not count.

Return JSON only: {"units":[{"i":1,"found":["c2"],"what":"<a few words>"}]} with an empty "found" list when no \
candidate states it."""


def check_absences(claims: list[Claim], sources: list[Source], llm: LLMCall, *, per_claim: int = 8) -> None:
    """Remove "the records do not contain X" when the full documents do contain X.

    Absence statements are otherwise judged only against the passages retrieved for the answer,
    so a retrieval miss would turn into a confident false negative.
    """
    targets = [c for c in claims if c.kind == "absence"]
    if not targets or not sources:
        return
    pools = [rank_candidates(c.text, sources, per_claim) for c in targets]
    body, ids = _build_prompt(targets, pools)
    body = body.replace("UNIT ", "STATEMENT ")
    try:
        verdicts = _parse(llm([{"role": "system", "content": ABSENCE_PROMPT}, {"role": "user", "content": body}]))
    except Exception as exc:  # fail closed: an unchecked absence claim is not shown as fact
        logger.warning("[grounding] absence check failed: %s", exc)
        for c in targets:
            c.kind, c.support, c.reason = "claim", UNSUPPORTED, "absence not checked"
        return
    for i, c in enumerate(targets, 1):
        v = verdicts.get(i) or {}
        found = [ids[x] for x in v.get("found") or [] if x in ids]
        found = [f for f in found if not is_heading(f[0].text[f[1]:f[2]])]
        if found:
            c.kind, c.support = "claim", CONTRADICTED
            c.spans = [_span(src, s, e) for src, s, e in found]
            c.reason = "the documents do state this: " + str(v.get("what") or "")


def verify_consensus(
    claims: list[Claim],
    sources: list[Source],
    llms: list[LLMCall],
    **kwargs: Any,
) -> list[Claim]:
    """Run independent verifiers and keep a sentence as "supported" only if all of them agree.

    The first verifier supplies the spans. Disagreement between "supported" and anything
    weaker gives "partial" (shown, flagged); a sentence is removed only when no verifier
    supports it, or any verifier finds it contradicted.
    """
    import copy
    from concurrent.futures import ThreadPoolExecutor

    if len(llms) <= 1:
        return verify_claims(claims, sources, llms[0], **kwargs)
    runs = [copy.deepcopy(claims) for _ in llms]
    with ThreadPoolExecutor(max_workers=len(llms)) as pool:
        list(pool.map(lambda pair: verify_claims(pair[0], sources, pair[1], **kwargs), zip(runs, llms)))
    for i, c in enumerate(claims):
        votes = [run[i] for run in runs]
        primary = votes[0]
        kinds = {v.kind for v in votes}
        if "claim" not in kinds:
            c.kind, c.support, c.spans, c.reason = primary.kind, None, [], ""
            continue
        c.kind = "claim"
        verdicts = [v.support if v.kind == "claim" else UNSUPPORTED for v in votes]
        with_spans = next((v for v in votes if v.spans), primary)
        c.spans = with_spans.spans
        if CONTRADICTED in verdicts:
            c.support = CONTRADICTED
            c.reason = next(v.reason for v in votes if v.support == CONTRADICTED)
        elif all(v == SUPPORTED for v in verdicts):
            c.support, c.reason = SUPPORTED, ""
        elif all(v == UNSUPPORTED for v in verdicts):
            c.support, c.reason = UNSUPPORTED, primary.reason
        else:
            c.support = PARTIAL
            c.reason = "; ".join(sorted({v.reason for v in votes if v.reason})) or "verifiers disagree"
            if not c.spans:
                c.support = UNSUPPORTED
    return claims
