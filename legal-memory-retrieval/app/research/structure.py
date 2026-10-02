"""Split an authority's text into passages with a role and a locator.

The role decides what a passage may be cited for. A dissent is not the holding,
a preambular "Recalling…" is not a decision, and a library catalogue summary
printed above a resolution is not the Council's text at all.

- UN Security Council resolutions: ``headnote`` (anything before "The Security
  Council,"), ``preamble`` clauses, ``operative`` paragraphs with their number
  (explicit, or counted when the old format leaves them unnumbered).
- PCIJ decisions: ``majority`` text, and ``separate_opinion`` / ``dissent`` /
  ``declaration`` segments, which in this corpus usually arrive as their own
  documents but can also be appended to the judgment. Pages are PDF pages
  (form-feed separated), labeled ``page_kind = "pdf"``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Passage:
    role: str
    text: str
    start: int
    end: int
    page: int | None = None
    para: int | None = None
    para_label: str | None = None  # "6", or "unnumbered 2" for old formats
    lead_verb: str | None = None
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Security Council resolutions
# ---------------------------------------------------------------------------

_COUNCIL_OPEN = re.compile(r"The\s+Security\s+Council\s*,", re.I)
_CHAPTER_VII = re.compile(r"Acting\s+under\s+(?:Chapter\s+VII|Article\s+(?:39|40|41|42)\b)", re.I)

# Operative clauses open with a verb in the third person ("Decides", "Calls upon").
OPERATIVE_VERBS = {
    "decides", "demands", "authorizes", "authorises", "calls", "urges", "requests", "recommends", "encourages",
    "invites", "appeals", "reaffirms", "affirms", "condemns", "deplores", "welcomes", "expresses", "notes",
    "takes", "emphasizes", "emphasises", "underscores", "underlines", "stresses", "reiterates", "recognizes",
    "recognises", "determines", "declares", "directs", "approves", "extends", "endorses", "commends", "supports",
    "acknowledges", "considers", "insists", "instructs", "establishes", "renews", "agrees", "confirms", "notes",
    "regrets", "censures", "warns", "remains", "further", "also", "strongly", "requires", "affirms", "terminates",
    "invites", "looks", "highlights", "underlines", "decided",
}
_NUMBERED = re.compile(r"(?m)^[ \t]*(?P<num>\d{1,3})\.[ \t]+(?P<word>[A-Z][a-z]+)")
_ADVERBS = {"also", "further", "strongly", "once", "again", "hereby", "unanimously"}


def _lead_verb(text: str) -> str | None:
    words = re.findall(r"[A-Za-z]+", text[:120])
    for w in words:
        lw = w.lower()
        if lw in _ADVERBS:
            continue
        return lw
    return None


def is_chapter_vii(text: str) -> bool:
    return bool(_CHAPTER_VII.search(text or ""))


def segment_resolution(text: str) -> list[Passage]:
    text = text or ""
    out: list[Passage] = []
    m = _COUNCIL_OPEN.search(text)
    body_start = m.end() if m else 0
    if m and len(" ".join(text[: m.start()].split())) > 200:
        # Text before "The Security Council," that is longer than a masthead is an editorial summary.
        out.append(Passage(role="headnote", text=text[: m.start()].strip(), start=0, end=m.start()))

    # The operative part starts at "1." if the resolution is numbered. Paragraphs must run 1, 2, 3…:
    # a later list that restarts at 1 (an annex, a sanctions list) is part of the paragraph above it.
    ops = []
    for n in _NUMBERED.finditer(text, body_start):
        if int(n.group("num")) == len(ops) + 1:
            ops.append(n)
    if ops:
        _preamble_clauses(text, body_start, ops[0].start(), out)
        for i, n in enumerate(ops):
            end = ops[i + 1].start() if i + 1 < len(ops) else len(text)
            seg = text[n.start():end].strip()
            out.append(Passage(role="operative", text=seg, start=n.start(), end=end, para=int(n.group("num")),
                               para_label=n.group("num"), lead_verb=_lead_verb(seg[len(n.group("num")) + 1:])))
        return out

    # Unnumbered (older) format: a clause starts on a line whose first word is a participle (preamble)
    # or a third-person verb (operative), after a line that ended a clause.
    starts: list[tuple[int, str]] = []
    prev_end_ok = True
    for line in re.finditer(r"(?m)^.*$", text[body_start:]):
        raw = line.group(0)
        abs_start = body_start + line.start()
        stripped = raw.strip()
        if not stripped:
            prev_end_ok = True
            continue
        if re.fullmatch(r"[IVX]{1,5}", stripped) or re.fullmatch(r"[A-Z]\.?", stripped):
            prev_end_ok = True  # section heading (I, II, A.)
            continue
        first = re.match(r"([A-Z][a-z]+)", stripped)
        if first and prev_end_ok:
            w = first.group(1).lower()
            if w.endswith("ing") or w in ("mindful", "convinced", "concerned", "determined", "alarmed", "aware",
                                           "conscious", "gravely", "deeply", "having", "bearing", "guided", "seized"):
                starts.append((abs_start, "preamble"))
            elif w in OPERATIVE_VERBS:
                starts.append((abs_start, "operative"))
        prev_end_ok = stripped.endswith((",", ";", ":", "."))
    n_op = 0
    for i, (s, role) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        seg = text[s:end].strip()
        if role == "operative":
            n_op += 1
            out.append(Passage(role="operative", text=seg, start=s, end=end, para=n_op,
                               para_label=f"unnumbered {n_op}", lead_verb=_lead_verb(seg)))
        else:
            out.append(Passage(role="preamble", text=seg, start=s, end=end, lead_verb=_lead_verb(seg)))
    return out


def _preamble_clauses(text: str, start: int, end: int, out: list[Passage]) -> None:
    chunk = text[start:end]
    # Preambular clauses end with a comma at line end; split on lines that open with a capitalised word
    # following such a line.
    idx = [start]
    for mm in re.finditer(r",[ \t]*\n(?=[ \t]*[A-Z][a-z])", chunk):
        idx.append(start + mm.end())
    idx.append(end)
    for a, b in zip(idx, idx[1:]):
        seg = text[a:b].strip()
        if len(seg) > 15:
            out.append(Passage(role="preamble", text=seg, start=a, end=b, lead_verb=_lead_verb(seg)))


# ---------------------------------------------------------------------------
# PCIJ decisions
# ---------------------------------------------------------------------------

_OPINION_HEAD = re.compile(
    r"(?m)^[ \t\W]{0,6}(?P<kind>DISSENTING\s+OPINION|SEPARATE\s+OPINION|INDIVIDUAL\s+OPINION|OBSERVATIONS|DECLARATION)"
    r"(?:\s+(?:OF|BY)\s+(?P<who>[A-Z][A-Za-z.' \-]{2,60}?))?\s*[.\[]"
)
_ROLE_OF = {
    "DISSENTING OPINION": "dissent",
    "SEPARATE OPINION": "separate_opinion",
    "INDIVIDUAL OPINION": "separate_opinion",
    "OBSERVATIONS": "separate_opinion",
    "DECLARATION": "declaration",
}


def opinion_heading(text: str) -> tuple[str, str | None] | None:
    """(role, judge) if ``text`` opens with an opinion heading."""
    m = _OPINION_HEAD.match((text or "")[:300].lstrip())
    if not m:
        return None
    kind = re.sub(r"\s+", " ", m.group("kind"))
    who = (m.group("who") or "").strip(" .") or None
    return _ROLE_OF[kind], who


def page_offsets(text: str) -> list[int]:
    """Start offset of each PDF page (form-feed separated). One page when there are no breaks."""
    offs = [0]
    for m in re.finditer("\f", text or ""):
        offs.append(m.end())
    return offs


def page_at(offsets: list[int], pos: int) -> int:
    page = 1
    for i, o in enumerate(offsets):
        if o <= pos:
            page = i + 1
        else:
            break
    return page


def segment_decision(text: str) -> list[Passage]:
    """Majority text and opinion segments of a PCIJ decision, with PDF pages."""
    text = text or ""
    offs = page_offsets(text)
    heads = [m for m in _OPINION_HEAD.finditer(text)]
    lead = opinion_heading(text)
    cuts: list[tuple[int, str, str | None]] = [(0, lead[0] if lead else "majority", lead[1] if lead else None)]
    for m in heads:
        if not text[:m.start()].strip():
            continue  # the document's own opening heading, already in ``lead``
        kind = re.sub(r"\s+", " ", m.group("kind"))
        cuts.append((m.start(), _ROLE_OF[kind], (m.group("who") or "").strip(" .") or None))
    out: list[Passage] = []
    for i, (s, role, who) in enumerate(cuts):
        end = cuts[i + 1][0] if i + 1 < len(cuts) else len(text)
        out.append(Passage(role=role, text=text[s:end], start=s, end=end, page=page_at(offs, s),
                           extra={"judge": who, "last_page": page_at(offs, max(s, end - 1))}))
    return out


def role_at(passages: list[Passage], pos: int) -> Passage | None:
    for p in passages:
        if p.start <= pos < p.end:
            return p
    return None
