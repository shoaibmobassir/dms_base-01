"""Plan edits to a long document without reading all of it into one prompt (plan 15, B4).

Chosen by experiment (docs/experiments/long_doc_editing_2026-09-28.md): reading the whole
document and returning quote-anchored edits (today's design) and an agent navigating the
document both fail on long documents — global changes exceed the edit cap, paragraphs cannot
be inserted or deleted, and turns run out of time. This engine is the "hybrid" design:

  1. plan      a model sees the instruction and the document OUTLINE (not the text) and names
               search terms, whole sections, clause numbers and literal substitutions
  2. substitute literal substitutions are applied by code to every paragraph (case-sensitive
               unless the find text is lower case), then VERIFIED in batches of 10 — a paragraph
               the verifier does not confirm is reverted
  3. edit      paragraphs matching the plan (minus those already changed) go to parallel editors;
               each may change only its EDITABLE paragraphs, and returns span edits (old → new
               inside a paragraph), new paragraphs or deletions — code applies them, so text the
               model did not mean to touch cannot drift
  4. verify    every editor span edit is verified like a substitution

The result is paragraph-id operations against the ORIGINAL numbering:
{"op": "replace"|"insert_after"|"delete", "pid": int, "text": str} — the input of
``app.drafting.docx_tracked.apply_tracked_changes``.
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

EDITOR_CHUNK = 40
VERIFY_CHUNK = 10
PAGE_CHARS = 3000

LLM = Callable[[list[dict[str, str]]], str]

PLANNER_PROMPT = """You plan an edit to a long legal document. You see the INSTRUCTION and the document OUTLINE (section ids, titles, pages), not its text.
Return JSON:
{"search_terms": [...],    // short literal phrases (case-insensitive); every paragraph that may need changing contains at least one
 "sections": [...],        // outline section ids whose EVERY paragraph may need changing (e.g. a section to delete); else []
 "clause_numbers": [...],  // clause numbers named in the instruction, e.g. "7.3"
 "substitutions": [...]}   // literal replacements the instruction implies wherever they apply:
                           // {"find": "...", "replace": "...", "whole_word": true}; [] if none
Choose search_terms generously (several spellings) - a paragraph not found cannot be edited. Substitutions are checked
paragraph by paragraph before they are kept, so propose them whenever the change is a literal replacement."""

EDITOR_PROMPT = """You edit part of a long legal document. Apply the INSTRUCTION only to the PARAGRAPHS shown (each has an id).
Return JSON {"ops":[
  {"op":"span","pid":123,"old":"exact text inside that paragraph","new":"replacement"},
  {"op":"insert_after","pid":123,"text":"new paragraph"},
  {"op":"delete","pid":123}]}
Use "span" for any change inside a paragraph: "old" must be copied exactly from that paragraph and be as short as possible
while unique in it. Return {"ops":[]} if nothing here needs a change.
Only paragraphs marked EDITABLE may be changed; CONTEXT paragraphs are shown for reference only.
Adding words to an existing clause (e.g. a sentence at its end) is a "span" edit on that clause: use its last words as
"old" and repeat them in "new" followed by the addition. Use insert_after only for a new, separately numbered paragraph."""

VERIFY_PROMPT = """A change was applied to the paragraphs below. Each is shown BEFORE and AFTER, and its exact CHANGES are listed as
[-removed-]{+added+} with a few words of context. For EACH paragraph decide whether the INSTRUCTION requires EVERY change shown in it. Answer
change=false if any single change is not required (e.g. a clause's own number altered when only references were meant to
change). Judge the meaning: a defined term is capitalised and a lower-case generic word is not that term; a notice, cure
or retention period is not a payment period.
Return JSON {"decisions":[{"id":123,"change":true,"why":"<=12 words"}]} with one entry per paragraph."""


_TOKEN = re.compile(r"\s+|[^\s]+")
_GLOBAL = re.compile(r"\b(every|everywhere|throughout|all|each|any)\b", re.I)
_QUOTED = re.compile(r"[“\"'‘][^”\"'’]*[”\"'’]")
# An instruction about the document's numbering or headings concerns every heading, whatever search terms the
# planner chose (a renumbering once reached only one of the four headings that needed it).
_STRUCTURE = re.compile(r"\b(?:re-?number\w*|numbering|headings?|sequential\w*|consecutive\w*)\b", re.I)
_LEADING_NUMBER = re.compile(r"^\s*(?:[A-Z]?\d+(?:\.\d+)*[A-Z]?\.?|[A-Z]\d+(?:\.\d+)*)\s")


def show_changes(before: str, after: str, context: int = 6) -> str:
    """Word-level diff: "…context [-old-]{+new+} context…" for each changed place."""
    from app.documents.tokens import tokenize, word_ops

    a, b = tokenize(before), tokenize(after)
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in word_ops(a, b):
        if tag == "equal":
            continue
        left = "".join(a[max(0, i1 - context):i1]).lstrip()
        right = "".join(a[i2:i2 + context]).rstrip()
        removed = "".join(a[i1:i2]).strip()
        added = "".join(b[j1:j2]).strip()
        change = (f"[-{removed}-]" if removed else "") + (f"{{+{added}+}}" if added else "")
        prefix = "…" if i1 - context > 0 else ""
        parts.append(f"{prefix}{left}{change}{right}…")
    return "  |  ".join(parts)


@dataclass
class EditPlan:
    ops: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)
    calls: int = 0
    peak_prompt_chars: int = 0
    ms: float = 0.0


def default_llm(model: str | None = None) -> LLM:
    import httpx

    from app.config import settings
    from app.llm.bedrock_client import chat_complete

    chosen = model or settings.edit_model or settings.bedrock_model

    def call(messages: list[dict[str, str]]) -> str:
        for attempt in (1, 2):  # one retry on a provider 5xx
            try:
                out = chat_complete(messages, model=chosen, temperature=0.0, max_tokens=8000, json_mode=True, timeout=240.0)
                return str(out.get("content") or "")
            except httpx.HTTPStatusError as exc:
                if attempt == 2 or exc.response is None or exc.response.status_code < 500:
                    raise
                time.sleep(2)
        return ""

    return call


class _Meter:
    def __init__(self, llm: LLM):
        self.llm, self.calls, self.peak = llm, 0, 0

    def __call__(self, messages: list[dict[str, str]]) -> dict:
        self.calls += 1
        self.peak = max(self.peak, sum(len(m["content"]) for m in messages))
        raw = (self.llm(messages) or "").strip()
        if "{" in raw:
            raw = raw[raw.find("{"): raw.rfind("}") + 1]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}


def paged(paragraphs: list[str]) -> tuple[str, list[int]]:
    """Paragraphs as paged text ("[Page N]" markers) and each paragraph's offset in it."""
    parts, offsets, pos, size, page = ["[Page 1]"], [], len("[Page 1]"), 0, 1
    for t in paragraphs:
        if size > PAGE_CHARS:
            page += 1
            marker = f"[Page {page}]"
            parts.append(marker)
            pos += 2 + len(marker)
            size = 0
        pos += 2
        offsets.append(pos)
        parts.append(t)
        pos += len(t)
        size += len(t)
    return "\n\n".join(parts), offsets


def _plan(paragraphs: list[str], instruction: str, meter: _Meter):
    from app.chat import doc_nav

    text, offsets = paged(paragraphs)
    sections = doc_nav.outline(text)
    outline = "\n".join(f"{s.section_id} {s.title} (pages {s.pages()})" for s in sections)
    plan = meter([{"role": "system", "content": PLANNER_PROMPT},
                  {"role": "user", "content": f"INSTRUCTION: {instruction}\n\nOUTLINE:\n{outline}"}])
    return plan, sections, offsets


def _candidates(paragraphs: list[str], plan: dict, sections, offsets: list[int]) -> set[int]:
    # A capitalised defined term being substituted is matched with its capital: a paragraph that only has
    # the ordinary lower-case word ("a leading supplier") is not about the defined term.
    exact = {str(s.get("find")) for s in plan.get("substitutions") or [] if isinstance(s, dict)
             and str(s.get("find") or "") != str(s.get("find") or "").lower()}
    exact_lower = {e.lower() for e in exact}
    terms = [str(t).lower() for t in plan.get("search_terms") or [] if str(t).strip() and str(t).lower() not in exact_lower]
    nums = [str(n).strip() for n in plan.get("clause_numbers") or [] if str(n).strip()]
    wanted = {str(s) for s in plan.get("sections") or []}
    spans = [(s.start, s.end) for s in sections if s.section_id in wanted]
    out = set()
    for i, t in enumerate(paragraphs):
        low = t.lower()
        if any(term in low for term in terms) or any(e in t for e in exact) \
                or any(re.match(rf"^{re.escape(n)}\.?\s", t) for n in nums):
            out.add(i)
        elif any(s <= offsets[i] < e for s, e in spans):
            out.add(i)
    return out


def _verify(before: list[str], after: list[str], changed: list[int], instruction: str, meter: _Meter) -> set[int]:
    """Ids whose change the verifier does not confirm (to revert). No decision = not confirmed."""
    chunks = [changed[i:i + VERIFY_CHUNK] for i in range(0, len(changed), VERIFY_CHUNK)]

    def ask(chunk: list[int]) -> set[int]:
        body = "\n".join(f"[{i}] BEFORE: {before[i]}\n     AFTER:  {after[i]}\n     CHANGES: {show_changes(before[i], after[i])}"
                         for i in chunk)
        data = meter([{"role": "system", "content": VERIFY_PROMPT},
                      {"role": "user", "content": f"INSTRUCTION: {instruction}\n\nPARAGRAPHS:\n{body}"}])
        keep = set()
        for d in data.get("decisions") or []:
            try:
                if d.get("change") is True:
                    keep.add(int(str(d.get("id")).strip("[]p ")))
            except ValueError:
                continue
        return set(chunk) - keep

    if not chunks:
        return set()
    with ThreadPoolExecutor(max_workers=16) as pool:
        return set().union(*pool.map(ask, chunks))


def _edit(paragraphs: list[str], instruction: str, cand: list[int], meter: _Meter) -> list[dict]:
    chunks = [cand[i:i + EDITOR_CHUNK] for i in range(0, len(cand), EDITOR_CHUNK)]

    def edit(chunk: list[int]) -> list[dict]:
        editable = set(chunk)
        shown = sorted({j for i in chunk for j in (i - 1, i, i + 1) if 0 <= j < len(paragraphs)})
        body = "\n".join(f"[p{j}] {'EDITABLE' if j in editable else 'CONTEXT'}: {paragraphs[j]}" for j in shown)
        data = meter([{"role": "system", "content": EDITOR_PROMPT},
                      {"role": "user", "content": f"INSTRUCTION: {instruction}\n\nPARAGRAPHS:\n{body}"}])
        ops = []
        for op in data.get("ops") or []:
            try:
                op["pid"] = int(str(op.get("pid")).lstrip("p"))
            except (TypeError, ValueError):
                continue
            if op["pid"] in editable:
                ops.append(op)
        return ops

    if not chunks:
        return []
    with ThreadPoolExecutor(max_workers=16) as pool:
        return [op for ops in pool.map(edit, chunks) for op in ops]


def _substitute_body(pat: str, repl: str, text: str, flags: int) -> str:
    """Apply a substitution to a paragraph's text but never to its own leading clause number
    (numbering is structure, not wording: "99.9 … Clause 9" must not become "910.9 …")."""
    m = _LEADING_NUMBER.match(text)
    head, body = (text[:m.end()], text[m.end():]) if m else ("", text)
    return head + re.sub(pat, repl, body, flags=flags)


def _span_problem(text: str, old: str) -> str | None:
    n = text.count(old) if old else 0
    if n == 1:
        return None
    return "its old text does not occur in the paragraph" if n == 0 else f"its old text occurs {n} times; quote more words so it is unique"


def _apply_spans(paragraphs: list[str], ops: list[dict]) -> tuple[list[str], int]:
    """Apply span edits whose ``old`` occurs exactly once in the paragraph; count the rest."""
    work, rejected = list(paragraphs), 0
    for op in ops:
        pid = op["pid"]
        old, new = str(op.get("old") or ""), str(op.get("new") if op.get("new") is not None else "")
        text = work[pid]
        if _span_problem(text, old) is None:
            work[pid] = text.replace(old, new, 1)
        elif old and text.count(old) > 1 and new.startswith(old) and text.rstrip().endswith(old.rstrip()):
            cut = text.rstrip().rfind(old.rstrip())  # "add at the end": the occurrence that ends the paragraph
            work[pid] = text[:cut] + new + text[cut + len(old.rstrip()):]
        elif old and text.count(old) > 1 and new.endswith(old) and text.lstrip().startswith(old.lstrip()):
            lead = len(text) - len(text.lstrip())
            work[pid] = text[:lead] + new + text[lead + len(old.lstrip()):]
        else:
            rejected += 1
    return work, rejected


def _repair_spans(paragraphs: list[str], instruction: str, ops: list[dict], meter: "_Meter") -> list[dict]:
    """Re-ask once, per paragraph, for span edits whose anchor is missing or ambiguous."""
    bad: dict[int, list[str]] = {}
    for op in ops:
        if op.get("op") == "span":
            problem = _span_problem(paragraphs[op["pid"]], str(op.get("old") or ""))
            if problem:
                bad.setdefault(op["pid"], []).append(f"“{str(op.get('old'))[:80]}”: {problem}")
    if not bad:
        return ops

    def ask(pid: int) -> list[dict]:
        body = (f"[p{pid}] EDITABLE: {paragraphs[pid]}\n\nYour previous span edit could not be applied: "
                + "; ".join(bad[pid]) + ". Return the corrected ops for this paragraph only.")
        data = meter([{"role": "system", "content": EDITOR_PROMPT},
                      {"role": "user", "content": f"INSTRUCTION: {instruction}\n\nPARAGRAPHS:\n{body}"}])
        fixed = []
        for op in data.get("ops") or []:
            try:
                op["pid"] = int(str(op.get("pid")).lstrip("p"))
            except (TypeError, ValueError):
                continue
            if op["pid"] == pid:
                fixed.append(op)
        return fixed

    with ThreadPoolExecutor(max_workers=8) as pool:
        repaired = [op for ops_ in pool.map(ask, list(bad)) for op in ops_]
    return [op for op in ops if not (op.get("op") == "span" and op["pid"] in bad)] + repaired


def plan_edits(paragraphs: list[str], instruction: str, *, llm: LLM | None = None) -> EditPlan:
    """Paragraph-id operations that carry out ``instruction`` (see module docstring)."""
    t0 = time.perf_counter()
    meter = _Meter(llm or default_llm())
    plan, sections, offsets = _plan(paragraphs, instruction, meter)
    notes: list[str] = []
    work = list(paragraphs)
    handled: set[int] = set()
    subs = [s for s in plan.get("substitutions") or [] if isinstance(s, dict) and s.get("find")]
    # A capitalised defined term's lower-case twin is an ordinary word ("a leading supplier"): never substituted.
    capitalised = {str(s["find"]) for s in subs if str(s["find"]) != str(s["find"]).lower()}
    subs = [s for s in subs if not (str(s["find"]) == str(s["find"]).lower()
                                    and any(c.lower() == str(s["find"]) for c in capitalised))]
    # An instruction about named clauses, with no "every / throughout / all", changes only those clauses.
    nums = [str(n).strip() for n in plan.get("clause_numbers") or [] if str(n).strip()]
    scoped = None
    if nums and not _GLOBAL.search(_QUOTED.sub(" ", instruction)):
        scoped = {i for i, t in enumerate(paragraphs) if any(re.match(rf"^{re.escape(n)}\.?\s", t) for n in nums)}
        notes.append(f"substitutions limited to clause(s) {', '.join(nums)}")
    for s in subs:
        find, repl = str(s["find"]), str(s.get("replace") or "")
        pat = re.escape(find)
        if s.get("whole_word", True):
            pat = rf"(?<![\w]){pat}(?![\w])"
        flags = 0 if find != find.lower() else re.I  # "Supplier" (a defined term) never matches "supplier"
        work = [_substitute_body(pat, repl, t, flags) if scoped is None or i in scoped else t for i, t in enumerate(work)]
    if subs:
        changed = [i for i, (a, b) in enumerate(zip(paragraphs, work)) if a != b]
        revert = _verify(paragraphs, work, changed, instruction, meter)
        for i in revert:
            work[i] = paragraphs[i]
        handled = set(changed) - revert
        notes.append(f"substitutions changed {len(changed)} paragraphs; {len(revert)} not confirmed and reverted")

    found = _candidates(work, plan, sections, offsets)
    if _STRUCTURE.search(instruction):
        from app.chat import doc_nav

        found |= {i for i, t in enumerate(work) if doc_nav._heading(t)}
    cand = sorted(found - handled)
    ops = _repair_spans(work, instruction, _edit(work, instruction, cand, meter), meter)
    spans = [op for op in ops if op.get("op") == "span"]
    after, rejected = _apply_spans(work, spans)
    changed = [i for i, (a, b) in enumerate(zip(work, after)) if a != b]
    revert = _verify(work, after, changed, instruction, meter)
    for i in changed:
        if i not in revert:
            work[i] = after[i]
    notes.append(f"{len(cand)} paragraphs sent to editors; {len(changed)} changed; {len(revert)} not confirmed")
    if rejected:
        notes.append(f"{rejected} span edits did not match their paragraph and were dropped")

    out: list[dict[str, Any]] = [{"op": "replace", "pid": i, "text": work[i]}
                                 for i in range(len(paragraphs)) if work[i] != paragraphs[i]]
    deleted = set()
    for op in ops:
        kind = op.get("op")
        if kind == "delete" and op["pid"] not in deleted:
            deleted.add(op["pid"])
            out = [o for o in out if o["pid"] != op["pid"]]
            out.append({"op": "delete", "pid": op["pid"], "text": ""})
        elif kind == "insert_after" and str(op.get("text") or "").strip():
            out.append({"op": "insert_after", "pid": op["pid"], "text": str(op["text"]).strip()})
    out.sort(key=lambda o: (o["pid"], o["op"] == "insert_after"))
    return EditPlan(ops=out, notes=notes, calls=meter.calls, peak_prompt_chars=meter.peak,
                    ms=round((time.perf_counter() - t0) * 1000, 1))


def apply_plan(paragraphs: list[str], ops: list[dict]) -> list[str]:
    """The document after the operations (accept-all view), for previews and tests."""
    replace = {o["pid"]: o["text"] for o in ops if o["op"] == "replace"}
    delete = {o["pid"] for o in ops if o["op"] == "delete"}
    after: dict[int, list[str]] = {}
    for o in ops:
        if o["op"] == "insert_after":
            after.setdefault(o["pid"], []).append(o["text"])
    out: list[str] = []
    for i, t in enumerate(paragraphs):
        if i not in delete:
            out.append(replace.get(i, t))
        out += after.get(i, [])
    return out
