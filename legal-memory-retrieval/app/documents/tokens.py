"""One word-level diff for every place that shows or writes a change between two texts.

Splitting on spaces alone treats ``1,20,00,000.`` as one word, so changing the amount also strikes and re-inserts the full
stop, and splitting finer than a word would show ``17`` as ``~~1~~7``. Tokens here are:

- a run of white space,
- a number with its separators kept whole (``1,20,00,000``, ``12.02.2025``, ``10:30``, ``1.25``),
- a word, with an inner apostrophe or hyphen kept (``Hon’ble``, ``issue-wise``),
- any other single character (punctuation stays out of the number or word beside it).

``"".join(tokenize(text)) == text`` always, so a diff can be written back exactly.

``word_ops`` returns difflib-style opcodes, except that changes separated only by white space are one change: a
reviewer reads "the parties shall → each party must" as one edit, not three with spaces between them.
"""
from __future__ import annotations

import difflib
import re

TOKEN = re.compile(r"\s+|\d[\d,./:\-]*\d|\d|[^\W\d_]+(?:['’\-][^\W\d_]+)*|\S")


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text)


def word_ops(a: list[str], b: list[str]) -> list[tuple[str, int, int, int, int]]:
    """Opcodes ``(tag, i1, i2, j1, j2)`` over token lists; adjacent changes joined across white space."""
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()

    def glue(k: int) -> bool:
        tag, i1, i2, _, _ = ops[k]
        if not (tag == "equal" and 0 < k < len(ops) - 1 and all(t.isspace() for t in a[i1:i2])):
            return False
        before, after = ops[k - 1][0], ops[k + 1][0]
        # two plain deletions (or two plain insertions) around a space stay as they are: merging would turn the
        # space into a struck-and-reinserted one
        return "equal" not in (before, after) and not (before == after and before in ("delete", "insert"))

    merged: list[tuple[str, int, int, int, int]] = []
    group: list[tuple[str, int, int, int, int]] = []

    def flush() -> None:
        if not group:
            return
        i1, i2, j1, j2 = group[0][1], group[-1][2], group[0][3], group[-1][4]
        tag = "replace" if i2 > i1 and j2 > j1 else "delete" if i2 > i1 else "insert"
        merged.append((tag, i1, i2, j1, j2))
        group.clear()

    for k, op in enumerate(ops):
        if op[0] != "equal" or (group and glue(k)):
            group.append(op)
        else:
            flush()
            merged.append(op)
    flush()
    return merged
