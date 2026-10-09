"""Reject suggested edits that fix the reading of a document, not the document.

The Assistant reads text that a program extracted from a PDF. On a scanned page that text came from OCR, and OCR
drops spaces ("knowledgeand"), swaps look-alike characters ("rn" for "m") and breaks words at line ends. A
suggestion to "correct" those would change a document that is fine, and the lawyer would be told it has defects it
does not have.

Two rules, both only for PDFs (a Word or text file is the real text, so a typo fix there is a real fix):

1. **Spacing.** An edit whose only difference is spaces, hyphenation, line breaks or ligatures is dropped. Spacing in
   extracted PDF text is never evidence about the printed page.
2. **Typo on a scanned page.** An edit that changes only an odd word into a near-identical word is dropped when the
   odd word is rare in the document and the corrected word is common in it ("tbe" for "the"). Anything with a number
   in it, any insertion or deletion, and any change to a word that is itself common is kept: those are substantive.

The checks are deterministic and run on every suggestion whatever the model says. When a PDF's text cannot be
compared (no document text), rule 2 does not fire, so a real change is never dropped on a guess.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

from app.documents.text_origin import SCANNED_OCR, page_origin
from app.research.ocr_match import _fold

_INVISIBLE = re.compile(r"[\s­​-‍⁠﻿]+")
_TOKEN = re.compile(r"\w+|[^\w\s]")
_WORD = re.compile(r"[A-Za-z]+")

TYPO_DISTANCE = 1  # letters that may differ (after folding look-alikes) for a change to count as a typo
RARE_IN_DOC = 1  # the odd word occurs at most this many times in the document...
COMMON_IN_DOC = 2  # ...and the corrected word at least this many times

SPACING = "spacing, hyphenation or line-break difference only; the PDF's printed text is not known to have this defect"
NO_CHANGE = "the suggested text is the same as the original"
SCANNED_TYPO = "typo-level change to text read by OCR from a scanned page; OCR errors are not defects in the document"


def _squash(text: str) -> str:
    """Text with spaces, soft hyphens and zero-width characters removed and ligatures expanded."""
    text = re.sub(r"(?<=\w)-[ \t]*\r?\n\s*", "", text)  # a word broken with a hyphen at the end of a line
    return _INVISIBLE.sub("", unicodedata.normalize("NFKC", text)).lower()


def _distance(a: str, b: str, cap: int) -> int:
    """Levenshtein distance, giving up (returning cap + 1) once it must exceed ``cap``."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _count(word: str, text: str) -> int:
    return len(re.findall(rf"(?<![A-Za-z]){re.escape(word)}(?![A-Za-z])", text, flags=re.IGNORECASE))


def _replaced(original: str, proposed: str) -> list[tuple[str, str]] | None:
    """The (old, new) word pairs that differ, or ``None`` when any difference is an insertion or deletion."""
    a, b = _TOKEN.findall(original), _TOKEN.findall(proposed)
    pairs: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag != "replace":
            return None
        pairs.append((" ".join(a[i1:i2]), " ".join(b[j1:j2])))
    return pairs


def _is_ocr_typo(original: str, proposed: str, doc_text: str) -> bool:
    pairs = _replaced(original, proposed)
    if not pairs:
        return False
    for old, new in pairs:
        # Only the words that changed matter. A number among them is a substantive change, never a typo;
        # a number elsewhere in the phrase is just context.
        if not (_WORD.fullmatch(old) and _WORD.fullmatch(new)):
            return False
        if _distance(_fold(old)[0], _fold(new)[0], TYPO_DISTANCE) > TYPO_DISTANCE:
            return False
        if _count(old, doc_text) > RARE_IN_DOC or _count(new, doc_text) < COMMON_IN_DOC:
            return False
    return True


def review_edit(original: str, proposed: str, *, source_format: str, origin: str | None,
                doc_text: str | None = None) -> str | None:
    """Why this edit must not be shown, or ``None`` when it may be."""
    original, proposed = (original or "").strip(), (proposed or "").strip()
    if not original or not proposed:
        return None  # an insertion or a deletion is a substantive change
    if original == proposed:
        return NO_CHANGE
    if source_format != "pdf":
        return None
    if _squash(original) == _squash(proposed):
        return SPACING
    if origin == SCANNED_OCR and doc_text and _is_ocr_typo(original, proposed, doc_text):
        return SCANNED_TYPO
    return None


def filter_edits(edits: list[dict[str, Any]], info: dict[str, Any], doc_text: str | None = None
                 ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split edits into (kept, rejected). Each edit has ``original``, ``proposed`` and optionally ``page``."""
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    fmt = info.get("format", "text")
    for edit in edits:
        why = review_edit(edit.get("original", ""), edit.get("proposed", ""), source_format=fmt,
                          origin=page_origin(info, edit.get("page")), doc_text=doc_text)
        if why:
            rejected.append({"original": str(edit.get("original", ""))[:80], "why": why})
        else:
            kept.append(edit)
    return kept, rejected


# --- claims in the answer's prose ----------------------------------------------------------------------

_QUOTED = re.compile(r"[\"\u201c]([^\"\u201c\u201d\n]{3,80})[\"\u201d]")
_ERROR_WORDS = re.compile(
    r"\b(missing space|extra space|no space|spacing|whitespace|ocr|typo|typographical|misspell\w*|misspelt|"
    r"spelling|illegible|garbled)\b", re.IGNORECASE)
_BARE_NUMBER_LINE = re.compile(r"^\s*[*_]*\s*\d+[.)]\s*[*_]*\s*$")
_PAGE_SPLIT = re.compile(r"^\[Page (\d+)[^\]]*\]$", re.MULTILINE)


def scan_only_words(stored_text: str, scanned_pages: list[int]) -> set[str]:
    """Lower-case words (4+ letters) that appear on scanned pages and on no born-digital page of the document."""
    if not scanned_pages:
        return set()
    parts = _PAGE_SPLIT.split(stored_text)  # [preamble, "1", page1 text, "2", page2 text, ...]
    scanned, digital = set(), set()
    for number, body in zip(parts[1::2], parts[2::2]):
        words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", body)}
        (scanned if int(number) in scanned_pages else digital).update(words)
    return scanned - digital


_ITEM_START = re.compile(r"^\s*[*_#]*\s*(\d+[.)]|[-*]\s+\*\*)")


def _items(lines: list[str]) -> list[tuple[int, int]]:
    """(start, end) line ranges of the list items / headings of an answer (end exclusive)."""
    starts = [i for i, line in enumerate(lines) if _ITEM_START.match(line)]
    if not starts:
        return []
    return [(st, starts[k + 1] if k + 1 < len(starts) else len(lines)) for k, st in enumerate(starts)]


def _is_artifact_pair(item_text: str, scan_only: set[str], doc_text: str | None) -> bool:
    """A quoted 'original' and a quoted 'fix' in one item that differ only as the reading of a scan would."""
    quotes = [q.strip() for q in _QUOTED.findall(item_text)]
    for i, first in enumerate(quotes):
        if not ({w.lower() for w in re.findall(r"[A-Za-z]{4,}", first)} & scan_only):
            continue
        for second in quotes[i + 1:]:
            if first != second and review_edit(first, second, source_format="pdf", origin=SCANNED_OCR,
                                               doc_text=doc_text) in (SPACING, SCANNED_TYPO):
                return True
    return False


def scrub_scan_claims(text: str, scan_only: set[str], doc_text: str | None = None) -> tuple[str, list[str]]:
    """Drop what the answer says about reading errors of scanned pages.

    Two things go: a line that quotes a word found only on a scanned page and calls it a spacing, OCR or spelling
    error, and a whole list item whose quoted "original" and quoted "fix" differ only as a scan's reading would
    (the same test the edit cards get). They describe the reading of the scan, not the document. Every other line
    stays, and a bare numbered heading left above a removed line goes with it.
    """
    if not text or not scan_only:
        return text, []
    lines = text.split("\n")
    drop: set[int] = set()
    removed: list[str] = []
    for start, end in _items(lines):
        item = "\n".join(lines[start:end])
        if _is_artifact_pair(item, scan_only, doc_text):
            drop.update(range(start, end))
            removed.append(lines[start].strip()[:120] or item[:120])
    for i, line in enumerate(lines):
        if i in drop:
            continue
        quoted_words = {w.lower() for q in _QUOTED.findall(line) for w in re.findall(r"[A-Za-z]{4,}", q)}
        if quoted_words & scan_only and _ERROR_WORDS.search(line):
            drop.add(i)
            removed.append(line.strip()[:120])
    kept: list[str] = []
    for i, line in enumerate(lines):
        if i in drop:
            if kept and _BARE_NUMBER_LINE.match(kept[-1]):
                kept.pop()
            continue
        kept.append(line)
    return "\n".join(kept), removed
