"""Who made a tracked change is decided by the server (plan 22, W2b).

A Word file saved by the browser editor carries tracked changes stamped in the browser. Changes that were already in
the version the editor opened keep their author and date; every change that is new in the saved file is re-stamped
with the signed-in member and the server's time, whatever the browser wrote. A change counts as "already there" when
the base file has one of the same kind, author, date and text.
"""
from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_STORY = re.compile(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")
_TAGS = ("ins", "del", "moveFrom", "moveTo", "rPrChange", "pPrChange", "sectPrChange", "tblPrChange", "trPrChange",
         "tcPrChange", "numberingChange")


def _signature(el) -> tuple[str, str, str, str]:
    text = "".join(t.text or "" for t in el.iter(f"{{{W}}}t", f"{{{W}}}delText"))
    return (etree.QName(el).localname, el.get(f"{{{W}}}author") or "", el.get(f"{{{W}}}date") or "", text)


def _revisions(data: bytes) -> Counter:
    z = zipfile.ZipFile(io.BytesIO(data))
    seen: Counter = Counter()
    for name in z.namelist():
        if not _STORY.match(name):
            continue
        root = etree.fromstring(z.read(name))
        for tag in _TAGS:
            for el in root.iter(f"{{{W}}}{tag}"):
                seen[_signature(el)] += 1
    return seen


def restamp_new_revisions(base: bytes | None, saved: bytes, author: str, when: datetime | None = None) -> tuple[bytes, int]:
    """Return the saved file with its new tracked changes credited to ``author`` now, and how many were re-stamped."""
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    known = _revisions(base) if base else Counter()
    zin = zipfile.ZipFile(io.BytesIO(saved))
    out = io.BytesIO()
    changed = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if _STORY.match(item.filename):
                root = etree.fromstring(data)
                touched = False
                for tag in _TAGS:
                    for el in root.iter(f"{{{W}}}{tag}"):
                        sig = _signature(el)
                        if known[sig] > 0:
                            known[sig] -= 1
                            continue
                        el.set(f"{{{W}}}author", author)
                        el.set(f"{{{W}}}date", stamp)
                        changed += 1
                        touched = True
                if touched:
                    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            zout.writestr(item, data)
    return out.getvalue(), changed
