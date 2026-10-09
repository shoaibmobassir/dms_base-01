"""Locate a quote in OCR'd text (1920s–30s scanned reports).

Scans read "I" as "1", "u" as "ii", "rn" for "m" and so on, so an exact or
punctuation-tolerant match misses quotes a lawyer copied from a clean edition.
This matcher compares letters only, after folding common OCR confusions, and
falls back to a bounded fuzzy comparison around anchor shingles. Standard
library only.
"""
from __future__ import annotations

import difflib
import re

MIN_RATIO = 0.85
_FOLD = str.maketrans({"1": "i", "l": "i", "|": "i", "!": "i", "0": "o"})


def _fold(text: str) -> tuple[str, list[int]]:
    """Letters only, lowercased and OCR-folded, with each kept char's offset in ``text``."""
    out: list[str] = []
    idx: list[int] = []
    low = text.lower()
    i = 0
    while i < len(low):
        ch = low[i]
        if ch == "r" and i + 1 < len(low) and low[i + 1] == "n":
            out.append("m"); idx.append(i); i += 2
            continue
        ch = ch.translate(_FOLD)
        if "a" <= ch <= "z":
            out.append(ch); idx.append(i)
        i += 1
    return "".join(out), idx


def locate_ocr(source: str, quote: str) -> tuple[int, int, float] | None:
    """(start, end, similarity) of ``quote`` in ``source``, or None."""
    s, sidx = _fold(source or "")
    q, _ = _fold(quote or "")
    if len(q) < 12 or not s:
        return None
    pos = s.find(q)
    if pos != -1:
        return sidx[pos], sidx[pos + len(q) - 1] + 1, 1.0
    k = 8
    anchors = sorted({(q[i:i + k], i) for i in range(0, len(q) - k, max(1, (len(q) - k) // 6))}, key=lambda a: a[1])
    tried: set[int] = set()
    best: tuple[int, int, float] | None = None
    for shingle, off in anchors:
        for m in re.finditer(re.escape(shingle), s):
            start = max(0, m.start() - off)
            if start in tried:
                continue
            tried.add(start)
            window = s[start:start + len(q) + len(q) // 8]
            sm = difflib.SequenceMatcher(None, q, window, autojunk=False)
            ratio = sm.ratio() if len(window) <= len(q) else max(
                sm.ratio(), difflib.SequenceMatcher(None, q, window[:len(q)], autojunk=False).ratio())
            if ratio >= MIN_RATIO and (best is None or ratio > best[2]):
                end = min(len(sidx) - 1, start + len(q) - 1)
                best = (sidx[start], sidx[end] + 1, ratio)
            if len(tried) > 200:
                return best
    return best
