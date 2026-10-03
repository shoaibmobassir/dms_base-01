"""Word review: who changed what in a .docx, and accepting or rejecting it (plan 18, R1).

Word records every tracked change with its author and time (ECMA-376 §17.13). This module
reads them the way Word's reviewing pane shows them and resolves any set of them:

    insert / move_to          accept: keep the text        reject: remove it
    delete / move_from        accept: remove the text      reject: restore it
    format / paragraph_format accept: keep new formatting  reject: restore the old
    paragraph_delete          accept: join with the next paragraph (as Word does)   reject: keep
    paragraph_insert          accept: keep the paragraph break                      reject: join
    row_insert / row_delete   (table rows) as insert / delete

Everything here works on the package's XML directly, so parts it does not touch (styles,
headers, comments, numbering, media) are written back byte for byte. Revisions in
headers, footers and notes are counted; resolving them is not supported yet.
"""
from __future__ import annotations

import io
import re
import zipfile
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Iterable

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"


def q(tag: str) -> str:
    return f"{{{W}}}{tag}"


# Run-level containers and their types.
CONTAINERS = {q("ins"): "insert", q("del"): "delete", q("moveFrom"): "move_from", q("moveTo"): "move_to"}
PROPERTY_CHANGES = {q("rPrChange"): "format", q("pPrChange"): "paragraph_format", q("tblPrChange"): "table_format",
                    q("trPrChange"): "table_format", q("tcPrChange"): "table_format", q("tblGridChange"): "table_format",
                    q("sectPrChange"): "section_format", q("tblPrExChange"): "table_format", q("numberingChange"): "format"}
MOVE_RANGES = {q("moveFromRangeStart"), q("moveFromRangeEnd"), q("moveToRangeStart"), q("moveToRangeEnd")}
OTHER_PARTS = re.compile(r"^word/(header\d*|footer\d*|footnotes|endnotes)\.xml$")


# ── the package ──────────────────────────────────────────────────────────────

class Package:
    """A .docx opened for editing its XML parts; everything else is copied unchanged."""

    def __init__(self, data: bytes):
        self._zip = zipfile.ZipFile(io.BytesIO(data))
        self.names = self._zip.namelist()
        self._parts: dict[str, etree._Element] = {}

    def has(self, name: str) -> bool:
        return name in self.names or name in self._parts

    def xml(self, name: str) -> etree._Element:
        if name not in self._parts:
            self._parts[name] = etree.fromstring(self._zip.read(name))
        return self._parts[name]

    def set_xml(self, name: str, root: etree._Element) -> None:
        self._parts[name] = root
        if name not in self.names:
            self.names.append(name)

    @property
    def document(self) -> etree._Element:
        return self.xml("word/document.xml")

    def save(self) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for name in self.names:
                if name in self._parts:
                    z.writestr(name, etree.tostring(self._parts[name], xml_declaration=True, encoding="UTF-8", standalone=True))
                else:
                    info = self._zip.getinfo(name)
                    z.writestr(info, self._zip.read(name))
        return out.getvalue()


def _body(pkg: Package) -> etree._Element:
    return pkg.document.find(q("body"))


def _local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


# ── reading ──────────────────────────────────────────────────────────────────

@dataclass
class Revision:
    key: str                 # "r<n>": position among the body's revisions (stable for one file)
    type: str
    author: str
    date: str | None
    pid: int | None          # body paragraph index (python-docx Document.paragraphs); None inside tables
    table: bool
    text: str = ""
    detail: str = ""


@dataclass
class Change:
    """Revisions grouped like Word's reviewing pane: same paragraph, author and type."""
    id: str
    type: str
    author: str
    date: str | None
    last_date: str | None
    pid: int | None
    table: bool
    keys: list[str] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)
    detail: str = ""
    context: str = ""
    paragraph: bool = False   # includes the paragraph break itself (a whole paragraph added or removed)


# A paragraph break's revision is shown with the same person's text change in that paragraph.
_GROUP_AS = {"paragraph_insert": "insert", "paragraph_delete": "delete"}


def _revision_elements(body: etree._Element) -> list[etree._Element]:
    """Every tracked-change element in document order (paragraph marks and row marks included)."""
    out = []
    for el in body.iter():
        tag = el.tag
        if tag in CONTAINERS or tag in PROPERTY_CHANGES:
            out.append(el)
        elif tag in (q("cellIns"), q("cellDel")):
            out.append(el)
    return out


def _mark_kind(el) -> str | None:
    """A w:ins / w:del that marks a paragraph mark (inside pPr/rPr) or a table row (inside trPr)."""
    parent = el.getparent()
    if parent is None:
        return None
    if parent.tag == q("rPr") and parent.getparent() is not None and parent.getparent().tag == q("pPr"):
        return "paragraph"
    if parent.tag == q("trPr"):
        return "row"
    return None


def _type_of(el) -> str:
    if el.tag in PROPERTY_CHANGES:
        return PROPERTY_CHANGES[el.tag]
    if el.tag == q("cellIns"):
        return "cell_insert"
    if el.tag == q("cellDel"):
        return "cell_delete"
    mark = _mark_kind(el)
    base = CONTAINERS[el.tag]
    if mark == "paragraph":
        return {"insert": "paragraph_insert", "delete": "paragraph_delete",
                "move_to": "paragraph_insert", "move_from": "paragraph_delete"}[base]
    if mark == "row":
        return {"insert": "row_insert", "delete": "row_delete"}.get(base, base)
    return base


def _text_of(el) -> str:
    parts = []
    for t in el.iter(q("t"), q("delText"), q("tab"), q("br")):
        if t.tag in (q("t"), q("delText")):
            parts.append(t.text or "")
        elif t.tag == q("tab"):
            parts.append("\t")
        else:
            parts.append("\n")
    return "".join(parts)


_PROP_WORDS = {
    "b": "bold", "bCs": "bold", "i": "italic", "iCs": "italic", "u": "underline", "strike": "strikethrough",
    "dstrike": "double strikethrough", "sz": "font size", "szCs": "font size", "color": "font colour", "rFonts": "font",
    "highlight": "highlight", "caps": "capitals", "smallCaps": "small capitals", "vertAlign": "superscript/subscript",
    "pStyle": "style", "jc": "alignment", "ind": "indent", "spacing": "spacing", "numPr": "numbering",
    "keepNext": "keep with next", "keepLines": "keep lines together", "tabs": "tabs", "rStyle": "character style",
    "lang": "language", "shd": "shading", "pBdr": "borders", "outlineLvl": "outline level",
}
_TOGGLES = {"b", "i", "u", "strike", "dstrike", "caps", "smallCaps"}


def _props(el) -> dict[str, str]:
    out = {}
    if el is None:
        return out
    for c in el:
        name = _local(c)
        if not name or name.endswith("Change") or name in ("rPr", "sectPr", "ins", "del", "moveFrom", "moveTo"):
            continue
        val = c.get(q("val"))
        out[name] = val if val is not None else "1"
    return out


def _describe_format(change) -> str:
    """"Bold added · Style: Heading 2 → Normal" from the new and the recorded old properties."""
    new = _props(change.getparent())
    old_el = change.find("*")
    old = _props(old_el)
    words = []
    for name in sorted(set(new) | set(old)):
        a, b = old.get(name), new.get(name)
        if a == b:
            continue
        label = _PROP_WORDS.get(name, name)
        if name in _TOGGLES:
            on_b = b is not None and b not in ("0", "false", "none")
            on_a = a is not None and a not in ("0", "false", "none")
            if on_a != on_b:
                words.append(f"{label.capitalize()} {'added' if on_b else 'removed'}")
            continue
        if name == "pStyle":
            words.append(f"Style: {a or 'Normal'} → {b or 'Normal'}")
            continue
        words.append(f"{label.capitalize()} changed")
    seen = []
    for w in words:
        if w not in seen:
            seen.append(w)
    return " · ".join(seen) or "Formatted"


def _paragraph_index(body) -> tuple[list, dict[int, int]]:
    """Body paragraphs outside tables (python-docx numbering) and id(element) → index.

    The list must stay referenced while the ids are used: lxml hands out proxy objects,
    and a proxy that is released can come back with a different id."""
    paras = body.findall(q("p"))
    return paras, {id(p): i for i, p in enumerate(paras)}


def _owner_paragraph(el):
    p = el
    while p is not None and p.tag != q("p"):
        p = p.getparent()
    return p


def _in_table(el) -> bool:
    return any(a.tag == q("tbl") for a in el.iterancestors())


def read_revisions(data: bytes) -> list[Revision]:
    pkg = Package(data)
    body = _body(pkg)
    paras, index = _paragraph_index(body)
    elements = _revision_elements(body)
    out = []
    for n, el in enumerate(elements):
        kind = _type_of(el)
        p = _owner_paragraph(el)
        text = ""
        detail = ""
        if kind in ("insert", "delete", "move_from", "move_to"):
            text = _text_of(el)
        elif kind in ("format", "paragraph_format", "table_format", "section_format"):
            detail = _describe_format(el)
            run = el.getparent().getparent() if el.tag == q("rPrChange") else None
            if run is not None and run.tag == q("r"):
                text = _text_of(run)
        out.append(Revision(key=f"r{n}", type=kind, author=author_name(el.get(q("author"))), date=el.get(q("date")),
                            pid=index.get(id(p)) if p is not None else None, table=_in_table(el), text=text, detail=detail))
    del paras
    return out


def author_name(raw: str | None) -> str:
    """Word keeps whatever the reviewer typed ("Trilegal " and "Trilegal" are one person)."""
    return " ".join((raw or "").split()) or "Unknown"


def _final_text(p) -> str:
    """A paragraph's text with every change accepted (inserted text in, deleted text out)."""
    parts = []
    for t in p.iter(q("t"), q("tab"), q("br")):
        if any(a.tag in (q("del"), q("moveFrom")) for a in t.iterancestors()):
            continue
        parts.append(t.text or "" if t.tag == q("t") else ("\t" if t.tag == q("tab") else "\n"))
    return "".join(parts)


def group_changes(data: bytes, revisions: list[Revision] | None = None) -> list[Change]:
    revs = revisions if revisions is not None else read_revisions(data)
    pkg = Package(data)
    paras = _body(pkg).findall(q("p"))
    groups: "OrderedDict[tuple, Change]" = OrderedDict()
    for r in revs:
        kind = _GROUP_AS.get(r.type, r.type)
        k = (r.pid if r.pid is not None else f"t{r.key}", r.author, kind)
        g = groups.get(k)
        if g is None:
            context = _final_text(paras[r.pid])[:160] if r.pid is not None and r.pid < len(paras) else ""
            g = Change(id=f"c{len(groups)}", type=kind, author=r.author, date=r.date, last_date=r.date, pid=r.pid,
                       table=r.table, context=context)
            groups[k] = g
        if r.type in _GROUP_AS:
            g.paragraph = True
        g.keys.append(r.key)
        if r.text.strip():
            g.texts.append(r.text)
        if r.detail and r.detail not in g.detail:
            g.detail = f"{g.detail} · {r.detail}" if g.detail else r.detail
        if r.date and (g.date is None or r.date < g.date):
            g.date = r.date
        if r.date and (g.last_date is None or r.date > g.last_date):
            g.last_date = r.date
    return list(groups.values())


def other_part_counts(data: bytes) -> dict[str, int]:
    """Revisions in headers, footers and notes (listed, not resolved here)."""
    pkg = Package(data)
    out = {}
    for name in pkg.names:
        if OTHER_PARTS.match(name):
            n = sum(1 for el in pkg.xml(name).iter() if el.tag in CONTAINERS or el.tag in PROPERTY_CHANGES)
            if n:
                out[name.split("/")[-1].removesuffix(".xml")] = n
    return out


def contributors(data: bytes, revisions: list[Revision] | None = None) -> list[dict]:
    """Per author: what they changed and when, from the tracked changes and comments in the file."""
    revs = revisions if revisions is not None else read_revisions(data)
    people: dict[str, dict] = {}

    def person(name: str) -> dict:
        return people.setdefault(name, {"author": name, "insertions": 0, "deletions": 0, "formats": 0, "moves": 0,
                                        "paragraphs": 0, "words_added": 0, "words_removed": 0, "comments": 0,
                                        "replies": 0, "first_at": None, "last_at": None})

    def seen(p: dict, when: str | None) -> None:
        if when:
            p["first_at"] = min(filter(None, [p["first_at"], when]))
            p["last_at"] = max(filter(None, [p["last_at"], when]))

    for r in revs:
        p = person(r.author)
        words = len(r.text.split())
        if r.type == "insert":
            p["insertions"] += 1
            p["words_added"] += words
        elif r.type == "delete":
            p["deletions"] += 1
            p["words_removed"] += words
        elif r.type in ("move_from", "move_to"):
            p["moves"] += 1 if r.type == "move_to" else 0
        elif r.type in ("paragraph_insert", "paragraph_delete", "row_insert", "row_delete", "cell_insert", "cell_delete"):
            p["paragraphs"] += 1
        else:
            p["formats"] += 1
        seen(p, r.date)
    from app.documents.docx_comments import read_comments

    for c in read_comments(data):
        p = person(c["author"])
        p["replies" if c["parent_para_id"] else "comments"] += 1
        seen(p, c["date"])
    return sorted(people.values(), key=lambda p: (p["last_at"] or ""), reverse=True)


def core_properties(data: bytes) -> dict[str, str | None]:
    pkg = Package(data)
    if not pkg.has("docProps/core.xml"):
        return {}
    root = pkg.xml("docProps/core.xml")
    out = {}
    for el in root:
        name = _local(el)
        if name in ("creator", "lastModifiedBy", "created", "modified", "revision", "title"):
            out[name] = (el.text or "").strip() or None
    return out


# ── resolving ────────────────────────────────────────────────────────────────

def _unwrap(el) -> None:
    parent = el.getparent()
    at = parent.index(el)
    for child in list(el):
        parent.insert(at, child)
        at += 1
    _keep_tail(el)
    parent.remove(el)


def _remove(el) -> None:
    _keep_tail(el)
    el.getparent().remove(el)


def _keep_tail(el) -> None:
    # WordprocessingML carries no mixed text, but keep any tail rather than lose it.
    if el.tail and el.tail.strip():
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent = el.getparent()
            parent.text = (parent.text or "") + el.tail


def _restore_text(el) -> None:
    """Deleted text back to normal text (w:delText → w:t, w:delInstrText → w:instrText) — but not
    text inside another deletion nested in this one, which stays deleted."""
    for t in list(el.iter(q("delText"), q("delInstrText"))):
        nested = False
        for a in t.iterancestors():
            if a is el:
                break
            if a.tag in (q("del"), q("moveFrom")):
                nested = True
                break
        if not nested:
            t.tag = q("t") if t.tag == q("delText") else q("instrText")


# Markers that may sit between two paragraphs without being content.
_BETWEEN = {q(t) for t in ("bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd", "moveFromRangeStart",
                           "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd", "proofErr", "permStart", "permEnd")}


def _join_with_next(p) -> None:
    """Remove paragraph p's break: its content moves to the start of the next paragraph (which
    keeps its own paragraph properties). The last paragraph of a container keeps its break."""
    nxt = p.getnext()
    while nxt is not None and (not isinstance(nxt.tag, str) or nxt.tag in _BETWEEN):
        nxt = nxt.getnext()
    if nxt is None or nxt.tag != q("p"):
        # Nothing to join with (last paragraph before a table or the section end): a paragraph
        # whose content is all gone goes too; one with content keeps its break.
        if not _final_text(p).strip() and p.find(f".//{q('drawing')}") is None:
            p.getparent().remove(p)
        return
    ppr = nxt.find(q("pPr"))
    at = 0 if ppr is None else nxt.index(ppr) + 1
    for child in [c for c in p if c.tag != q("pPr")]:
        nxt.insert(at, child)
        at += 1
    p.getparent().remove(p)


def _restore_properties(change) -> None:
    """Reject a property change: the properties go back to the recorded old ones."""
    holder = change.getparent()
    old = change.find("*")
    keep = {q("rPr"), q("sectPr")} if holder.tag == q("pPr") else set()
    kept = [c for c in holder if c.tag in keep]
    others = [c for c in holder if c is not change and c.tag not in keep and c.tag.endswith("Change") and c.tag in PROPERTY_CHANGES]
    for c in list(holder):
        holder.remove(c)
    for c in list(old) if old is not None else []:
        holder.append(c)
    for c in kept + others:
        holder.append(c)


def _cleanup_move_ranges(body) -> None:
    """Drop move range markers whose moved text has been resolved."""
    order = list(body.iter())
    pos = {id(e): i for i, e in enumerate(order)}
    moves = [pos[id(e)] for e in order if e.tag in (q("moveFrom"), q("moveTo"))]
    starts = {}
    for e in order:
        if e.tag in (q("moveFromRangeStart"), q("moveToRangeStart")):
            starts[(e.tag, e.get(q("id")))] = e
    ends = {}
    for e in order:
        if e.tag == q("moveFromRangeEnd"):
            ends[(q("moveFromRangeStart"), e.get(q("id")))] = e
        elif e.tag == q("moveToRangeEnd"):
            ends[(q("moveToRangeStart"), e.get(q("id")))] = e
    for key, start in starts.items():
        end = ends.get(key)
        lo = pos[id(start)]
        hi = pos[id(end)] if end is not None else len(order)
        if not any(lo < m < hi for m in moves):
            _remove(start)
            if end is not None:
                _remove(end)


def _attached(e, body) -> bool:
    return any(a is body for a in e.iterancestors())


def _resolve_elements(body, elements: Iterable, accept: bool) -> int:
    elements = list(elements)
    # Content first, then property changes, then paragraph/row marks (last to first, so joins
    # never disturb marks still to be processed).
    content = [e for e in elements if e.tag in CONTAINERS and _mark_kind(e) is None]
    props = [e for e in elements if e.tag in PROPERTY_CHANGES]
    marks = [e for e in elements if e.tag in CONTAINERS and _mark_kind(e) is not None]
    cells = [e for e in elements if e.tag in (q("cellIns"), q("cellDel"))]
    done = 0
    for e in content:
        if not _attached(e, body):
            continue  # already removed with an enclosing revision
        keep_text = (accept and e.tag in (q("ins"), q("moveTo"))) or (not accept and e.tag in (q("del"), q("moveFrom")))
        if keep_text:
            if e.tag in (q("del"), q("moveFrom")):
                _restore_text(e)
            _unwrap(e)
        else:
            _remove(e)
        done += 1
    for e in props:
        if not _attached(e, body):
            continue
        if accept:
            _remove(e)
        else:
            _restore_properties(e)
        done += 1
    for e in cells:
        if not _attached(e, body):
            continue
        drop_cell = (accept and e.tag == q("cellDel")) or (not accept and e.tag == q("cellIns"))
        tc = e.getparent().getparent() if e.getparent() is not None else None
        _remove(e)
        if drop_cell and tc is not None and tc.tag == q("tc") and tc.getparent() is not None:
            tc.getparent().remove(tc)
        done += 1
    for e in reversed(marks):
        if not _attached(e, body):
            continue
        kind = _mark_kind(e)
        removes_break = (accept and e.tag in (q("del"), q("moveFrom"))) or (not accept and e.tag in (q("ins"), q("moveTo")))
        holder = e.getparent()
        _remove(e)
        if kind == "paragraph":
            p = holder.getparent().getparent()
            if len(holder) == 0 and not holder.attrib:
                holder.getparent().remove(holder)
            if removes_break and p is not None and p.getparent() is not None:
                _join_with_next(p)
        elif kind == "row":
            tr = holder.getparent()
            if len(holder) == 0 and not holder.attrib:
                tr.remove(holder)
            if removes_break and tr is not None and tr.getparent() is not None:
                tr.getparent().remove(tr)
        done += 1
    _cleanup_move_ranges(body)
    return done


def resolve(data: bytes, keys: Iterable[str] | None, accept: bool) -> tuple[bytes, int]:
    """Accept or reject the revisions with these keys (None: every revision in the body)."""
    pkg = Package(data)
    body = _body(pkg)
    elements = _revision_elements(body)
    if keys is not None:
        wanted = set(keys)
        elements = [e for n, e in enumerate(elements) if f"r{n}" in wanted]
    n = _resolve_elements(body, elements, accept)
    return pkg.save(), n


def keys_by(data: bytes, *, authors: Iterable[str] | None = None, pids: Iterable[int] | None = None) -> list[str]:
    authors = set(authors) if authors is not None else None
    pids = set(pids) if pids is not None else None
    return [r.key for r in read_revisions(data)
            if (authors is None or r.author in authors) and (pids is None or r.pid in pids)]


def accept_everything(data: bytes) -> bytes:
    return resolve(data, None, accept=True)[0] if has_revisions(data) else data


def reject_everything(data: bytes) -> bytes:
    return resolve(data, None, accept=False)[0] if has_revisions(data) else data


def has_revisions(data: bytes) -> bool:
    try:
        xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml")
    except Exception:
        return False
    return any(tag in xml for tag in (b"<w:ins ", b"<w:del ", b"<w:moveFrom ", b"<w:moveTo ", b"Change ", b"<w:cellIns", b"<w:cellDel"))


def text_view(data: bytes, view: str = "final") -> list[str]:
    """Body paragraph texts (outside tables) as they read in the Final or the Original view."""
    resolved = accept_everything(data) if view == "final" else reject_everything(data)
    body = _body(Package(resolved))
    return [_final_text(p) for p in body.findall(q("p"))]


def paragraph_pending(data: bytes, revisions: list[Revision] | None = None) -> dict[int, list[dict]]:
    """pid → [{author, types, count}] for body paragraphs holding pending changes."""
    revs = revisions if revisions is not None else read_revisions(data)
    out: dict[int, dict[str, dict]] = {}
    for r in revs:
        if r.pid is None:
            continue
        by = out.setdefault(r.pid, {})
        e = by.setdefault(r.author, {"author": r.author, "types": [], "count": 0})
        e["count"] += 1
        if r.type not in e["types"]:
            e["types"].append(r.type)
    return {pid: list(v.values()) for pid, v in out.items()}


def as_dicts(items) -> list[dict]:
    return [asdict(i) for i in items]
