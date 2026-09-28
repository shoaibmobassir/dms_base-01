"""Four ways to edit a long document, compared on the same tasks and model (plan 15, Part D2).

Every architecture takes the document's paragraphs and an instruction and returns the edited
paragraphs plus cost figures (model calls, largest prompt, wall time).

  baseline   — today's design: read the document (as much as fits), return ≤ 20 quote-anchored
               edits; each is applied at the first place its quote occurs
  navigate   — the real Assistant agent with the B1 tools (outline, section/page reads, find,
               propose_edits); edits come from its edit_proposals events
  mapreduce  — a planner names the terms a changed paragraph must contain; paragraphs are
               screened by those terms; parallel section editors return paragraph-id operations
  hybrid     — mapreduce, but a literal substitution the planner declares mechanical is applied
               by code to every paragraph (no model reads them); semantic parts go to editors

Paragraph-id operations: {"op": "replace"|"insert_after"|"delete", "pid": int, "text": str}.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from app.chat.verify_citations import locate_quote
from evals.long_doc.generate import paged_text

BASELINE_MAX_CHARS = 360_000   # what one prompt can hold alongside instructions (~90k tokens)
EDITOR_CHUNK = 40              # paragraphs per section-editor call
MAX_EDITS_TODAY = 20           # app/chat/tools/review_tools.py MAX_EDITS


@dataclass
class Run:
    paragraphs: list[str]
    calls: int = 0
    peak_prompt_chars: int = 0
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


class Meter:
    """Wraps the model call to count calls and the largest prompt."""

    def __init__(self, llm: Callable[[list[dict], bool], str]):
        self.llm, self.calls, self.peak = llm, 0, 0

    def __call__(self, messages: list[dict], json_mode: bool = True) -> str:
        self.calls += 1
        self.peak = max(self.peak, sum(len(m["content"]) for m in messages))
        return self.llm(messages, json_mode)


def bedrock_llm(model: str | None = None) -> Callable[[list[dict], bool], str]:
    from app.config import settings
    from app.llm.bedrock_client import chat_complete

    chosen = model or settings.bedrock_model

    def call(messages: list[dict], json_mode: bool = True) -> str:
        out = chat_complete(messages, model=chosen, temperature=0.0, max_tokens=8000, json_mode=json_mode, timeout=240.0)
        return str(out.get("content") or "")

    return call


def _json(raw: str) -> dict:
    raw = (raw or "").strip()
    if "{" in raw:
        raw = raw[raw.find("{"): raw.rfind("}") + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Applying edits
# ---------------------------------------------------------------------------

def apply_quote_edits(paras: list[str], edits: list[dict]) -> tuple[list[str], int]:
    """Today's semantics: find ``original`` (first match wins) and replace it with ``proposed``."""
    out = list(paras)
    missed = 0
    for e in edits:
        original, proposed = str(e.get("original") or ""), str(e.get("proposed") or "")
        if not original:
            missed += 1
            continue
        for i, t in enumerate(out):
            loc = locate_quote(t, original)
            if loc:
                out[i] = t[:loc.start] + proposed + t[loc.end:]
                break
        else:
            missed += 1
    flat: list[str] = []
    for t in out:  # an edit that added "\n\n" created new paragraphs; an emptied paragraph is gone
        flat += [x.strip() for x in t.split("\n\n") if x.strip()]
    return flat, missed


def apply_ops(paras: list[str], ops: list[dict]) -> tuple[list[str], int]:
    """Paragraph-id operations against the ORIGINAL numbering; invalid ids are rejected."""
    replace: dict[int, str] = {}
    delete: set[int] = set()
    after: dict[int, list[str]] = {}
    rejected = 0
    for op in ops:
        pid = op.get("pid")
        if not isinstance(pid, int) or not 0 <= pid < len(paras):
            rejected += 1
            continue
        kind, text = op.get("op"), str(op.get("text") or "").strip()
        if kind == "replace" and text:
            replace.setdefault(pid, text)
        elif kind == "delete":
            delete.add(pid)
        elif kind == "insert_after" and text:
            after.setdefault(pid, []).append(text)
        else:
            rejected += 1
    out: list[str] = []
    for i, t in enumerate(paras):
        if i not in delete:
            out.append(replace.get(i, t))
        out += after.get(i, [])
    return out, rejected


# ---------------------------------------------------------------------------
# Architectures
# ---------------------------------------------------------------------------

BASELINE_PROMPT = """You edit a legal document for a lawyer. Apply the INSTRUCTION to the DOCUMENT.
Return JSON {"edits":[{"original":"exact text copied from the document","proposed":"replacement text"}]}.
"original" must be copied verbatim (without [Page N] markers) and be long enough to be unique. Use "" as
"proposed" to delete. To insert a paragraph, use the preceding paragraph as "original" and repeat it in
"proposed" followed by a blank line and the new paragraph. At most 20 edits."""


def baseline(paras: list[str], instruction: str, llm) -> Run:
    t0 = time.perf_counter()
    meter = Meter(llm)
    text = paged_text(paras)
    run = Run(paragraphs=paras)
    if len(text) > BASELINE_MAX_CHARS:
        run.notes.append(f"document truncated to {BASELINE_MAX_CHARS} of {len(text)} chars")
        text = text[:BASELINE_MAX_CHARS]
    data = _json(meter([{"role": "system", "content": BASELINE_PROMPT},
                        {"role": "user", "content": f"INSTRUCTION: {instruction}\n\nDOCUMENT:\n{text}"}]))
    edits = (data.get("edits") or [])[:MAX_EDITS_TODAY]
    run.paragraphs, missed = apply_quote_edits(paras, edits)
    if missed:
        run.notes.append(f"{missed} edits not located")
    run.calls, run.peak_prompt_chars, run.seconds = meter.calls, meter.peak, time.perf_counter() - t0
    return run


def navigate(paras: list[str], instruction: str, llm=None) -> Run:
    """The production Assistant agent (B1 tools); edits applied from its propose_edits events."""
    from app.chat import agent
    from app.chat.tools.document_tools import DocEntry

    t0 = time.perf_counter()
    text = paged_text(paras)
    index = {"doc-0": DocEntry("doc-0", "DOC-LONGEDIT", "Master Services Agreement.docx", text=text)}
    peak = [0]
    real = agent._call_llm

    def metered(messages, tools, model=None):
        peak[0] = max(peak[0], sum(len(str(m.get("content") or "")) for m in messages))
        return real(messages, tools, model)

    agent._call_llm = metered
    try:
        out = agent.run_chat_agent_sync(None, f"{instruction}\n\nThe document is doc-0. Propose the edits.", [], index,
                                        mode="answer")
    finally:
        agent._call_llm = real
    edits = [e for ev in out["events"] if ev.get("type") == "edit_proposals" for e in ev.get("edits") or []]
    run = Run(paragraphs=paras)
    run.paragraphs, missed = apply_quote_edits(paras, edits)
    t = out.get("timings") or {}
    run.calls = len(t.get("llm_ms") or [])
    run.peak_prompt_chars = peak[0]
    run.seconds = time.perf_counter() - t0
    if missed:
        run.notes.append(f"{missed} edits not located")
    if t.get("wrap_up"):
        run.notes.append("turn ran out of time/rounds")
    return run


PLANNER_PROMPT = """You plan an edit to a long legal document. You see the INSTRUCTION and the document OUTLINE (not its text).
Return JSON:
{"search_terms": [...],   // short literal phrases (case-insensitive); EVERY paragraph that may need changing contains at least one
 "clause_numbers": [...], // clause numbers named in the instruction, e.g. "7.3"
 "mechanical": [...],     // ONLY for pure literal substitutions that apply wherever the text occurs:
                          // {"find": "...", "replace": "...", "whole_word": true, "case_sensitive": true}
 "semantic": true|false}  // true if some change needs judgment (which occurrences, rewording, insertion, deletion)
Choose search_terms generously (several spellings, e.g. "30 days", "thirty (30) days") - a missed paragraph cannot be edited."""

EDITOR_PROMPT = """You edit part of a long legal document. Apply the INSTRUCTION only to the PARAGRAPHS shown (each has an id).
Return JSON {"ops":[{"op":"replace","pid":123,"text":"full new paragraph text"},
                    {"op":"insert_after","pid":123,"text":"new paragraph"},
                    {"op":"delete","pid":123}]}
Return {"ops":[]} if none of these paragraphs needs a change. Keep every paragraph you replace identical except for the
change itself (same numbering, wording and punctuation). Only use ids shown."""


def _plan(paras: list[str], instruction: str, meter: Meter) -> dict:
    from app.chat import doc_nav

    outline = doc_nav.outline_rows(paged_text(paras), limit=400)
    lines = "\n".join(f"{r['section_id']} {r['title']} (pages {r['pages']})" for r in outline)
    return _json(meter([{"role": "system", "content": PLANNER_PROMPT},
                        {"role": "user", "content": f"INSTRUCTION: {instruction}\n\nOUTLINE:\n{lines}"}]))


def _candidates(paras: list[str], plan: dict) -> list[int]:
    terms = [str(t).lower() for t in plan.get("search_terms") or [] if str(t).strip()]
    nums = [str(n).strip() for n in plan.get("clause_numbers") or [] if str(n).strip()]
    if not terms and not nums:
        return list(range(len(paras)))
    hit = []
    for i, t in enumerate(paras):
        low = t.lower()
        if any(term in low for term in terms) or any(re.match(rf"^{re.escape(n)}\.?\s", t) for n in nums):
            hit.append(i)
    return hit


def _edit_candidates(paras: list[str], instruction: str, cand: list[int], meter: Meter) -> list[dict]:
    chunks = [cand[i:i + EDITOR_CHUNK] for i in range(0, len(cand), EDITOR_CHUNK)]

    def edit(chunk: list[int]) -> list[dict]:
        shown = sorted({j for i in chunk for j in (i - 1, i, i + 1) if 0 <= j < len(paras)})
        body = "\n".join(f"[p{j}] {paras[j]}" for j in shown)
        data = _json(meter([{"role": "system", "content": EDITOR_PROMPT},
                            {"role": "user", "content": f"INSTRUCTION: {instruction}\n\nPARAGRAPHS:\n{body}"}]))
        allowed = set(shown)
        ops = []
        for op in data.get("ops") or []:
            try:
                op["pid"] = int(str(op.get("pid")).lstrip("p"))
            except (TypeError, ValueError):
                continue
            if op["pid"] in allowed:
                ops.append(op)
        return ops

    with ThreadPoolExecutor(max_workers=16) as pool:
        return [op for ops in pool.map(edit, chunks) for op in ops]


def mapreduce(paras: list[str], instruction: str, llm, *, mechanical: bool = False) -> Run:
    t0 = time.perf_counter()
    meter = Meter(llm)
    plan = _plan(paras, instruction, meter)
    run = Run(paragraphs=paras)
    work = list(paras)
    mech = plan.get("mechanical") or [] if mechanical else []
    for m in mech:
        find, repl = str(m.get("find") or ""), str(m.get("replace") or "")
        if not find:
            continue
        pat = re.escape(find)
        if m.get("whole_word", True):
            pat = rf"(?<![\w]){pat}(?![\w])"
        rx = re.compile(pat, 0 if m.get("case_sensitive", True) else re.I)
        work = [rx.sub(repl, t) for t in work]
    if mech:
        run.notes.append(f"mechanical: {len(mech)} substitution(s) applied by code")
    if mech and not plan.get("semantic"):
        run.paragraphs = work
    else:
        cand = _candidates(work, plan)
        run.notes.append(f"{len(cand)} candidate paragraphs of {len(work)}")
        ops = _edit_candidates(work, instruction, cand, meter)
        run.paragraphs, rejected = apply_ops(work, ops)
        if rejected:
            run.notes.append(f"{rejected} ops rejected")
    run.calls, run.peak_prompt_chars, run.seconds = meter.calls, meter.peak, time.perf_counter() - t0
    return run


def hybrid(paras: list[str], instruction: str, llm) -> Run:
    return mapreduce(paras, instruction, llm, mechanical=True)


ARCHITECTURES: dict[str, Callable[..., Run]] = {
    "baseline": baseline, "navigate": navigate, "mapreduce": mapreduce, "hybrid": hybrid,
}


# ---------------------------------------------------------------------------
# v2 — fixes from the first run (see docs/experiments/long_doc_editing_*.md)
#   1. editors return SPAN edits (old → new inside one paragraph), applied by code: untouched
#      text cannot drift the way whole-paragraph rewrites did
#   2. the planner may name whole outline sections (a schedule's body does not repeat its title)
#   3. every code-applied substitution is VERIFIED paragraph by paragraph (batched yes/no);
#      paragraphs the verifier rejects are reverted — a literal find/replace is never trusted blind
# ---------------------------------------------------------------------------

PLANNER_V2 = """You plan an edit to a long legal document. You see the INSTRUCTION and the document OUTLINE (section ids, titles, pages), not its text.
Return JSON:
{"search_terms": [...],    // short literal phrases (case-insensitive); every paragraph that may need changing contains at least one
 "sections": [...],        // outline section ids whose EVERY paragraph may need changing (e.g. a section to delete); else []
 "clause_numbers": [...],  // clause numbers named in the instruction, e.g. "7.3"
 "substitutions": [...]}   // literal replacements the instruction implies wherever they apply:
                           // {"find": "...", "replace": "...", "whole_word": true, "case_sensitive": true}; [] if none
Choose search_terms generously (several spellings) — a paragraph not found cannot be edited. Substitutions will be
checked paragraph by paragraph before they are kept, so propose them whenever the change is a literal replacement."""

EDITOR_V2 = """You edit part of a long legal document. Apply the INSTRUCTION only to the PARAGRAPHS shown (each has an id).
Return JSON {"ops":[
  {"op":"span","pid":123,"old":"exact text inside that paragraph","new":"replacement"},  // smallest change; repeat for several spots
  {"op":"insert_after","pid":123,"text":"new paragraph"},
  {"op":"delete","pid":123}]}
Use "span" for any change inside a paragraph: "old" must be copied exactly from that paragraph and be as short as possible
while unique in it. Return {"ops":[]} if nothing here needs a change. Only use ids shown."""

VERIFY_PROMPT = """A literal substitution was applied to the paragraphs below. For each, decide whether the INSTRUCTION really
requires this paragraph to change. Answer from the instruction's meaning, not from the words alone.
Return JSON {"keep":[ids that should change], "revert":[ids that should not]}."""


def apply_v2_ops(paras: list[str], ops: list[dict]) -> tuple[list[str], int]:
    work = list(paras)
    rejected = 0
    structural = []
    for op in ops:
        pid = op.get("pid")
        if not isinstance(pid, int) or not 0 <= pid < len(paras):
            rejected += 1
            continue
        if op.get("op") == "span":
            old, new = str(op.get("old") or ""), str(op.get("new") if op.get("new") is not None else "")
            if old and old in work[pid]:
                work[pid] = work[pid].replace(old, new, 1)
            else:
                rejected += 1
        else:
            structural.append(op)
    out, rej2 = apply_ops(work, structural)
    return out, rejected + rej2


def _plan_v2(paras: list[str], instruction: str, meter: Meter) -> tuple[dict, list]:
    from app.chat import doc_nav

    text = paged_text(paras)
    sections = doc_nav.outline(text)
    lines = "\n".join(f"{s.section_id} {s.title} (pages {s.pages()})" for s in sections)
    plan = _json(meter([{"role": "system", "content": PLANNER_V2},
                        {"role": "user", "content": f"INSTRUCTION: {instruction}\n\nOUTLINE:\n{lines}"}]))
    return plan, sections


def _section_paragraphs(paras: list[str], sections, wanted: list[str]) -> set[int]:
    """Paragraph ids whose text falls inside the named outline sections of the paged text."""
    wanted_set = {str(w) for w in wanted}
    spans = [(s.start, s.end) for s in sections if s.section_id in wanted_set]
    if not spans:
        return set()
    text = paged_text(paras)
    out, pos = set(), 0
    for i, t in enumerate(paras):
        at = text.find(t, pos)
        if at < 0:
            continue
        pos = at + len(t)
        if any(s <= at < e for s, e in spans):
            out.add(i)
    return out


def _verify(original: list[str], work: list[str], changed: list[int], instruction: str, meter: Meter) -> set[int]:
    """Ids whose substitution the instruction does not require (to revert)."""
    chunks = [changed[i:i + EDITOR_CHUNK] for i in range(0, len(changed), EDITOR_CHUNK)]

    def ask(chunk: list[int]) -> set[int]:
        body = "\n".join(f"[p{i}] BEFORE: {original[i]}\n      AFTER:  {work[i]}" for i in chunk)
        data = _json(meter([{"role": "system", "content": VERIFY_PROMPT},
                            {"role": "user", "content": f"INSTRUCTION: {instruction}\n\nPARAGRAPHS:\n{body}"}]))
        ids = set()
        for x in data.get("revert") or []:
            try:
                ids.add(int(str(x).lstrip("p")))
            except ValueError:
                continue
        return ids & set(chunk)

    with ThreadPoolExecutor(max_workers=16) as pool:
        return set().union(*pool.map(ask, chunks)) if chunks else set()


def _edit_candidates_v2(paras: list[str], instruction: str, cand: list[int], meter: Meter) -> list[dict]:
    chunks = [cand[i:i + EDITOR_CHUNK] for i in range(0, len(cand), EDITOR_CHUNK)]

    def edit(chunk: list[int]) -> list[dict]:
        shown = sorted({j for i in chunk for j in (i - 1, i, i + 1) if 0 <= j < len(paras)})
        body = "\n".join(f"[p{j}] {paras[j]}" for j in shown)
        data = _json(meter([{"role": "system", "content": EDITOR_V2},
                            {"role": "user", "content": f"INSTRUCTION: {instruction}\n\nPARAGRAPHS:\n{body}"}]))
        ops = []
        for op in data.get("ops") or []:
            try:
                op["pid"] = int(str(op.get("pid")).lstrip("p"))
            except (TypeError, ValueError):
                continue
            if op["pid"] in shown:
                ops.append(op)
        return ops

    with ThreadPoolExecutor(max_workers=16) as pool:
        return [op for ops in pool.map(edit, chunks) for op in ops]


def mapreduce_v2(paras: list[str], instruction: str, llm, *, substitute: bool = False, verify_all: bool = False) -> Run:
    t0 = time.perf_counter()
    meter = Meter(llm)
    plan, sections = _plan_v2(paras, instruction, meter)
    run = Run(paragraphs=paras)
    work = list(paras)
    handled: set[int] = set()
    if substitute and plan.get("substitutions"):
        for m in plan["substitutions"]:
            find, repl = str(m.get("find") or ""), str(m.get("replace") or "")
            if not find:
                continue
            pat = re.escape(find)
            if m.get("whole_word", True):
                pat = rf"(?<![\w]){pat}(?![\w])"
            rx = re.compile(pat, 0 if m.get("case_sensitive", True) else re.I)
            work = [rx.sub(repl, t) for t in work]
        changed = [i for i, (a, b) in enumerate(zip(paras, work)) if a != b]
        revert = _verify(paras, work, changed, instruction, meter)
        for i in revert:
            work[i] = paras[i]
        handled = set(changed) - revert
        run.notes.append(f"substitution changed {len(changed)} paragraphs; verifier reverted {len(revert)}")
    cand = set(_candidates(work, plan)) | _section_paragraphs(work, sections, plan.get("sections") or [])
    cand -= handled  # already changed by a verified substitution
    run.notes.append(f"{len(cand)} candidate paragraphs for editors")
    ops = _edit_candidates_v2(work, instruction, sorted(cand), meter)
    if verify_all:
        # v3: an editor's in-paragraph change is checked like a substitution; structural ops
        # (insert / delete) are kept as proposed.
        spans = [op for op in ops if op.get("op") == "span"]
        after, _ = apply_v2_ops(work, spans)
        changed = [i for i, (a, b) in enumerate(zip(work, after)) if a != b]
        revert = _verify(work, after, changed, instruction, meter)
        ops = [op for op in ops if not (op.get("op") == "span" and op.get("pid") in revert)]
        run.notes.append(f"editors changed {len(changed)} paragraphs; verifier reverted {len(revert)}")
    run.paragraphs, rejected = apply_v2_ops(work, ops)
    if rejected:
        run.notes.append(f"{rejected} ops rejected")
    run.calls, run.peak_prompt_chars, run.seconds = meter.calls, meter.peak, time.perf_counter() - t0
    return run


def hybrid_v2(paras: list[str], instruction: str, llm) -> Run:
    return mapreduce_v2(paras, instruction, llm, substitute=True)


def hybrid_v3(paras: list[str], instruction: str, llm) -> Run:
    """hybrid_v2 + every in-paragraph change (code or editor) verified against the instruction."""
    return mapreduce_v2(paras, instruction, llm, substitute=True, verify_all=True)


ARCHITECTURES.update({"mapreduce_v2": mapreduce_v2, "hybrid_v2": hybrid_v2, "hybrid_v3": hybrid_v3})


# ---------------------------------------------------------------------------
# v4 — fixes from the v2/v3 failure samples
#   A. substitutions are case-sensitive unless the planner's find text is itself lower case
#      ("Supplier" the defined term ≠ "a leading supplier")
#   B. the verifier sees 10 paragraphs per call and must give a decision and a reason per id
#   C. editors may change only the candidate paragraphs; neighbours are shown read-only, and
#      adding words to a clause is a span edit on that clause, never a new paragraph
#   D. one retry of a model call on a server error (Bedrock 5xx)
# ---------------------------------------------------------------------------

VERIFY_V4 = """A literal substitution was applied to the paragraphs below. For EACH paragraph decide whether the INSTRUCTION
really requires this paragraph to change as shown. Judge the meaning: e.g. a defined term is capitalised and a lower-case
generic word is not that term; a notice, cure or retention period is not a payment period.
Return JSON {"decisions":[{"id":123,"change":true,"why":"<=12 words"}]} with one entry per paragraph."""

EDITOR_V4 = EDITOR_V2 + """
Only paragraphs marked EDITABLE may be changed; CONTEXT paragraphs are shown for reference only.
Adding words to an existing clause (e.g. a sentence at its end) is a "span" edit on that clause: use its last words as
"old" and repeat them in "new" followed by the addition. Use insert_after only for a new, separately numbered paragraph."""


def retrying(llm):
    import httpx

    def call(messages, json_mode=True):
        try:
            return llm(messages, json_mode)
        except httpx.HTTPStatusError as exc:
            if exc.response is None or exc.response.status_code < 500:
                raise
            time.sleep(2)
            return llm(messages, json_mode)

    return call


def _verify_v4(original: list[str], work: list[str], changed: list[int], instruction: str, meter: Meter) -> set[int]:
    chunks = [changed[i:i + 10] for i in range(0, len(changed), 10)]

    def ask(chunk: list[int]) -> set[int]:
        body = "\n".join(f"[{i}] BEFORE: {original[i]}\n     AFTER:  {work[i]}" for i in chunk)
        data = _json(meter([{"role": "system", "content": VERIFY_V4},
                            {"role": "user", "content": f"INSTRUCTION: {instruction}\n\nPARAGRAPHS:\n{body}"}]))
        keep = set()
        for d in data.get("decisions") or []:
            try:
                if d.get("change") is True:
                    keep.add(int(str(d.get("id")).lstrip("p[").rstrip("]")))
            except ValueError:
                continue
        return set(chunk) - keep  # no decision = not confirmed = revert

    with ThreadPoolExecutor(max_workers=16) as pool:
        return set().union(*pool.map(ask, chunks)) if chunks else set()


def _edit_candidates_v4(paras: list[str], instruction: str, cand: list[int], meter: Meter) -> list[dict]:
    chunks = [cand[i:i + EDITOR_CHUNK] for i in range(0, len(cand), EDITOR_CHUNK)]

    def edit(chunk: list[int]) -> list[dict]:
        editable = set(chunk)
        shown = sorted({j for i in chunk for j in (i - 1, i, i + 1) if 0 <= j < len(paras)})
        body = "\n".join(f"[p{j}] {'EDITABLE' if j in editable else 'CONTEXT'}: {paras[j]}" for j in shown)
        data = _json(meter([{"role": "system", "content": EDITOR_V4},
                            {"role": "user", "content": f"INSTRUCTION: {instruction}\n\nPARAGRAPHS:\n{body}"}]))
        ops = []
        for op in data.get("ops") or []:
            try:
                op["pid"] = int(str(op.get("pid")).lstrip("p"))
            except (TypeError, ValueError):
                continue
            if op["pid"] in editable:
                ops.append(op)
        return ops

    with ThreadPoolExecutor(max_workers=16) as pool:
        return [op for ops in pool.map(edit, chunks) for op in ops]


def hybrid_v4(paras: list[str], instruction: str, llm) -> Run:
    t0 = time.perf_counter()
    meter = Meter(retrying(llm))
    plan, sections = _plan_v2(paras, instruction, meter)
    run = Run(paragraphs=paras)
    work = list(paras)
    handled: set[int] = set()
    subs = plan.get("substitutions") or []
    for m in subs:
        find, repl = str(m.get("find") or ""), str(m.get("replace") or "")
        if not find:
            continue
        pat = re.escape(find)
        if m.get("whole_word", True):
            pat = rf"(?<![\w]){pat}(?![\w])"
        case_sensitive = find != find.lower()  # A: "Supplier" never matches "supplier"
        work = [re.sub(pat, repl, t, flags=0 if case_sensitive else re.I) for t in work]
    if subs:
        changed = [i for i, (a, b) in enumerate(zip(paras, work)) if a != b]
        revert = _verify_v4(paras, work, changed, instruction, meter)
        for i in revert:
            work[i] = paras[i]
        handled = set(changed) - revert
        run.notes.append(f"substitution changed {len(changed)} paragraphs; verifier reverted {len(revert)}")
    cand = set(_candidates(work, plan)) | _section_paragraphs(work, sections, plan.get("sections") or [])
    cand -= handled
    ops = _edit_candidates_v4(work, instruction, sorted(cand), meter)
    spans = [op for op in ops if op.get("op") == "span"]
    after, _ = apply_v2_ops(work, spans)
    changed = [i for i, (a, b) in enumerate(zip(work, after)) if a != b]
    revert = _verify_v4(work, after, changed, instruction, meter)
    ops = [op for op in ops if not (op.get("op") == "span" and op.get("pid") in revert)]
    run.notes.append(f"{len(cand)} candidates; editors changed {len(changed)}; verifier reverted {len(revert)}")
    run.paragraphs, rejected = apply_v2_ops(work, ops)
    if rejected:
        run.notes.append(f"{rejected} ops rejected")
    run.calls, run.peak_prompt_chars, run.seconds = meter.calls, meter.peak, time.perf_counter() - t0
    return run


ARCHITECTURES["hybrid_v4"] = hybrid_v4


def production(paras: list[str], instruction: str, llm) -> Run:
    """The shipped engine (app/editing/engine.py), scored on the same benchmark."""
    from app.editing.engine import apply_plan, plan_edits

    t0 = time.perf_counter()
    plan = plan_edits(paras, instruction, llm=retrying(lambda messages, json_mode=True: llm(messages, True)))
    return Run(paragraphs=apply_plan(paras, plan.ops), calls=plan.calls, peak_prompt_chars=plan.peak_prompt_chars,
               seconds=time.perf_counter() - t0, notes=plan.notes)


ARCHITECTURES["production"] = production
