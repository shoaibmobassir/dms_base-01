"""Word comments in and out of a .docx (plan 18, R5).

Reading: ``comments.xml`` (text, author, date), ``commentsExtended.xml`` (``paraIdParent`` makes a
reply, ``done`` marks a thread resolved), ``commentsIds.xml`` (a durable id Word keeps across
saves) and the ``commentRangeStart``/``End`` anchors in the body (the commented text).

Writing: comments made in Precentis — threads and replies — are added to the file the way
Word writes them (a comment, its anchor range around the quoted text, a reference run, an
entry in commentsExtended), under the author's name; the resolved state of every thread is
written as Word's "done". Comments already in the file keep their XML.

Identity: a comment's ``external_id`` is Word's durable id when present, else its paraId.
Comments written from Precentis get a paraId derived from the annotation id, so writing the
same thread twice, or reading back a file we wrote, never duplicates it.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from lxml import etree

from app.documents.docx_review import Package, _final_text, author_name, q

W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
W16CID = "http://schemas.microsoft.com/office/word/2016/wordml/cid"
W16CEX = "http://schemas.microsoft.com/office/word/2018/wordml/cex"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

COMMENTS = "word/comments.xml"
EXTENDED = "word/commentsExtended.xml"
IDS = "word/commentsIds.xml"
EXTENSIBLE = "word/commentsExtensible.xml"
PEOPLE = "word/people.xml"
RELS = "word/_rels/document.xml.rels"
TYPES = "[Content_Types].xml"

_PART_TYPES = {
    COMMENTS: ("http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"),
    EXTENDED: ("http://schemas.microsoft.com/office/2011/relationships/commentsExtended",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml"),
}


def _attr(el, ns: str, name: str) -> str | None:
    return el.get(f"{{{ns}}}{name}")


# ── reading ──────────────────────────────────────────────────────────────────

def _anchors(pkg: Package) -> dict[str, dict]:
    """w:id → {quote, pid} from the commentRangeStart/End markers in the body."""
    body = pkg.document.find(q("body"))
    paras = body.findall(q("p"))
    top = {}
    for i, p in enumerate(paras):
        top[id(p)] = i
    open_ids: dict[str, list[str]] = {}
    pid_of: dict[str, int | None] = {}
    for el in body.iter():
        tag = el.tag
        if tag == q("commentRangeStart"):
            cid = el.get(q("id"))
            open_ids[cid] = []
            owner = el
            while owner is not None and owner.tag != q("p"):
                owner = owner.getparent()
            if owner is None:  # between paragraphs: the next paragraph holds the text
                owner = el.getnext()
            pid_of[cid] = top.get(id(owner)) if owner is not None else None
        elif tag == q("commentRangeEnd"):
            cid = el.get(q("id"))
            if cid in open_ids:
                open_ids[cid] = open_ids[cid]  # closed below
                open_ids.setdefault("__closed__" + cid, open_ids.pop(cid))
        elif tag in (q("t"), q("tab"), q("br")) and open_ids:
            if any(a.tag in (q("del"), q("moveFrom")) for a in el.iterancestors()):
                continue
            piece = (el.text or "") if tag == q("t") else ("\t" if tag == q("tab") else "\n")
            for cid, parts in open_ids.items():
                if not cid.startswith("__closed__"):
                    parts.append(piece)
    out = {}
    for key, parts in open_ids.items():
        cid = key.removeprefix("__closed__")
        out[cid] = {"quote": " ".join("".join(parts).split())[:2000], "pid": pid_of.get(cid)}
    return out


def read_comments(data: bytes) -> list[dict]:
    """Every comment in the file: {id, para_id, durable_id, parent_para_id, done, author, initials,
    date, text, quote, pid}. Replies carry ``parent_para_id``."""
    pkg = Package(data)
    if not pkg.has(COMMENTS):
        return []
    ext: dict[str, dict] = {}
    if pkg.has(EXTENDED):
        for e in pkg.xml(EXTENDED).iter(f"{{{W15}}}commentEx"):
            ext[_attr(e, W15, "paraId")] = {"parent": _attr(e, W15, "paraIdParent"), "done": _attr(e, W15, "done") == "1"}
    durable: dict[str, str] = {}
    if pkg.has(IDS):
        for e in pkg.xml(IDS).iter(f"{{{W16CID}}}commentId"):
            durable[_attr(e, W16CID, "paraId")] = _attr(e, W16CID, "durableId")
    anchors = _anchors(pkg)
    out = []
    for c in pkg.xml(COMMENTS).findall(q("comment")):
        paras = c.findall(q("p"))
        para_id = _attr(paras[-1], W14, "paraId") if paras else None
        info = ext.get(para_id, {})
        text = "\n".join(_final_text(p) for p in paras).strip()
        anchor = anchors.get(c.get(q("id")), {})
        out.append({
            "id": c.get(q("id")), "para_id": para_id, "durable_id": durable.get(para_id),
            "parent_para_id": info.get("parent"), "done": bool(info.get("done")),
            "author": author_name(c.get(q("author"))), "initials": c.get(q("initials")),
            "date": c.get(q("date")), "text": text, "quote": anchor.get("quote", ""), "pid": anchor.get("pid"),
        })
    return out


def external_id(comment: dict) -> str:
    return comment.get("durable_id") or comment.get("para_id") or f"id:{comment['id']}"


def para_id_for(annotation_id: str) -> str:
    """The paraId a Precentis comment is written with (stable; below 0x80000000 as Word requires)."""
    n = int(hashlib.sha1(annotation_id.encode()).hexdigest()[:8], 16) & 0x7FFFFFFE
    return f"{max(n, 1):08X}"


# ── writing ──────────────────────────────────────────────────────────────────

def _ensure_part(pkg: Package, name: str, root_tag: str, nsmap: dict) -> etree._Element:
    if pkg.has(name):
        return pkg.xml(name)
    root = etree.Element(root_tag, nsmap=nsmap)
    pkg.set_xml(name, root)
    rel_type, content_type = _PART_TYPES[name]
    rels = pkg.xml(RELS)
    ids = {r.get("Id") for r in rels}
    n = 1
    while f"rIdPct{n}" in ids:
        n += 1
    etree.SubElement(rels, f"{{{REL}}}Relationship", Id=f"rIdPct{n}", Type=rel_type, Target=name.removeprefix("word/"))
    types = pkg.xml(TYPES)
    if not any(o.get("PartName") == "/" + name for o in types.iter(f"{{{CT}}}Override")):
        etree.SubElement(types, f"{{{CT}}}Override", PartName="/" + name, ContentType=content_type)
    return root


def _text_runs(p) -> list:
    """Runs whose text shows in the Final view, in order."""
    return [r for r in p.iter(q("r"))
            if not any(a.tag in (q("del"), q("moveFrom")) for a in r.iterancestors())
            and (r.find(q("t")) is not None or r.find(q("tab")) is not None or r.find(q("br")) is not None)]


def _run_text(r) -> str:
    return "".join((c.text or "") if c.tag == q("t") else ("\t" if c.tag == q("tab") else "\n")
                   for c in r if c.tag in (q("t"), q("tab"), q("br")))


def _split_run_at(run, offset: int):
    """Split a run carrying one w:t at ``offset``; returns the run that starts at the offset."""
    ts = run.findall(q("t"))
    if len(ts) != 1 or any(c.tag in (q("tab"), q("br")) for c in run):
        return run  # not a plain text run: anchor at its edge rather than split it
    text = ts[0].text or ""
    if offset <= 0 or offset >= len(text):
        return run
    second = etree.fromstring(etree.tostring(run))
    ts[0].text = text[:offset]
    ts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    st = second.find(q("t"))
    st.text = text[offset:]
    st.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    run.addnext(second)
    return second


def _locate(p, quote: str) -> tuple | None:
    """(start run, end run) spanning the first occurrence of ``quote`` in paragraph p's text."""
    runs = _text_runs(p)
    if not runs or not quote.strip():
        return None
    texts = [_run_text(r) for r in runs]
    full = "".join(texts)
    # Search with whitespace runs collapsed (as quotes are stored), then map back to raw offsets.
    norm, raw_at = [], []
    for i, ch in enumerate(full):
        if ch.isspace():
            if norm and norm[-1] == " ":
                continue
            norm.append(" ")
        else:
            norm.append(ch)
        raw_at.append(i)
    norm_q = " ".join(quote.split())
    at = "".join(norm).find(norm_q)
    if at < 0:
        return None
    idx = raw_at[at]
    end = raw_at[at + len(norm_q) - 1] + 1
    pos = 0
    start_run = end_run = None
    for r, t in zip(runs, texts):
        lo, hi = pos, pos + len(t)
        if start_run is None and lo <= idx < hi:
            start_run = _split_run_at(r, idx - lo)
            if start_run is not r:  # split: the remainder is the new run, positions shift
                r = start_run
                t = t[idx - lo:]
                lo = idx
                hi = lo + len(t)
        if start_run is not None and lo < end <= hi:
            _split_run_at(r, end - lo)
            end_run = r
            break
        pos = hi
    if start_run is None:
        return None
    return start_run, (end_run if end_run is not None else start_run)


def _reference_run(comment_id: str):
    r = etree.Element(q("r"))
    rpr = etree.SubElement(r, q("rPr"))
    etree.SubElement(rpr, q("rStyle"), {q("val"): "CommentReference"})
    etree.SubElement(r, q("commentReference"), {q("id"): comment_id})
    return r


def _comment_element(comment_id: str, para_id: str, author: str, date: str, text: str):
    initials = "".join(w[0] for w in author.split()[:3]).upper() or "P"
    c = etree.Element(q("comment"), {q("id"): comment_id, q("author"): author, q("date"): date, q("initials"): initials})
    p = etree.SubElement(c, q("p"), {f"{{{W14}}}paraId": para_id, f"{{{W14}}}textId": "77777777"})
    ppr = etree.SubElement(p, q("pPr"))
    etree.SubElement(ppr, q("pStyle"), {q("val"): "CommentText"})
    ref = etree.SubElement(p, q("r"))
    rpr = etree.SubElement(ref, q("rPr"))
    etree.SubElement(rpr, q("rStyle"), {q("val"): "CommentReference"})
    etree.SubElement(ref, q("annotationRef"))
    lines = text.split("\n")
    run = etree.SubElement(p, q("r"))
    for i, line in enumerate(lines):
        if i:
            etree.SubElement(run, q("br"))
        t = etree.SubElement(run, q("t"))
        t.text = line
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return c


def write_comments(data: bytes, threads: list[dict]) -> tuple[bytes, dict[str, str]]:
    """Bring the file's comments in line with Precentis.

    ``threads``: comments in thread order (roots before their replies), each
    {annotation_id, parent_id, source, external_id, author, date, text, status, quote, pid}.
    Returns (new file, {annotation_id: external_id written}).
    """
    pkg = Package(data)
    existing = read_comments(data)
    by_external = {external_id(c): c for c in existing}
    by_para = {c["para_id"]: c for c in existing if c["para_id"]}
    body = pkg.document.find(q("body"))
    paras = body.findall(q("p"))
    comments = _ensure_part(pkg, COMMENTS, q("comments"), {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
                                                          "w14": W14})
    extended = _ensure_part(pkg, EXTENDED, f"{{{W15}}}commentsEx", {"w15": W15})
    ex_by_para = {_attr(e, W15, "paraId"): e for e in extended.iter(f"{{{W15}}}commentEx")}
    used_ids = {int(c.get(q("id"))) for c in comments.findall(q("comment")) if (c.get(q("id")) or "").isdigit()}
    next_id = max(used_ids | {-1}) + 1
    written: dict[str, str] = {}
    para_of: dict[str, str] = {}   # annotation_id → paraId (for replies' parents)
    cid_of: dict[str, str] = {}    # annotation_id → w:id

    for t in threads:
        ext = t.get("external_id")
        known = by_external.get(ext) if ext else None
        if known is None and ext and ext in by_para:
            known = by_para[ext]
        if known is not None:
            para_of[t["annotation_id"]] = known["para_id"]
            cid_of[t["annotation_id"]] = known["id"]
            if t.get("parent_id") is None and known["para_id"]:
                done = "1" if t.get("status") == "resolved" else "0"
                e = ex_by_para.get(known["para_id"])
                if e is None:
                    e = etree.SubElement(extended, f"{{{W15}}}commentEx", {f"{{{W15}}}paraId": known["para_id"]})
                    ex_by_para[known["para_id"]] = e
                e.set(f"{{{W15}}}done", done)
            continue
        if t.get("source") == "word":
            continue  # a Word comment no longer in this file: not ours to recreate
        para_id = para_id_for(t["annotation_id"])
        while para_id in by_para:
            para_id = f"{(int(para_id, 16) + 1) & 0x7FFFFFFE:08X}"
        comment_id = str(next_id)
        next_id += 1
        date = t.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        comments.append(_comment_element(comment_id, para_id, t.get("author") or "Precentis", date, t.get("text") or ""))
        parent = t.get("parent_id")
        ex_attrs = {f"{{{W15}}}paraId": para_id, f"{{{W15}}}done": "1" if (not parent and t.get("status") == "resolved") else "0"}
        if parent and parent in para_of:
            ex_attrs[f"{{{W15}}}paraIdParent"] = para_of[parent]
        ex_by_para[para_id] = etree.SubElement(extended, f"{{{W15}}}commentEx", ex_attrs)
        _anchor(body, paras, comment_id, t, cid_of.get(parent) if parent else None)
        by_para[para_id] = {"para_id": para_id, "id": comment_id}
        para_of[t["annotation_id"]] = para_id
        cid_of[t["annotation_id"]] = comment_id
        written[t["annotation_id"]] = para_id
        _extras(pkg, para_id, t.get("author") or "Precentis", date)
    return pkg.save(), written


def _anchor(body, paras, comment_id: str, t: dict, parent_cid: str | None) -> None:
    """Place the comment's range: beside its parent's (replies), around the quote, or at the paragraph."""
    start = etree.Element(q("commentRangeStart"), {q("id"): comment_id})
    end = etree.Element(q("commentRangeEnd"), {q("id"): comment_id})
    if parent_cid is not None:
        ps = next((e for e in body.iter(q("commentRangeStart")) if e.get(q("id")) == parent_cid), None)
        pe = next((e for e in body.iter(q("commentRangeEnd")) if e.get(q("id")) == parent_cid), None)
        if ps is not None and pe is not None:
            ps.addnext(start)
            pe.addnext(end)
            end.addnext(_reference_run(comment_id))
            return
    order = []
    pid = t.get("pid")
    if isinstance(pid, int) and 0 <= pid < len(paras):
        order.append(paras[pid])
    order += [p for p in paras if p not in order]
    quote = t.get("quote") or ""
    for p in order:
        if quote and " ".join(quote.split()) in " ".join(_final_text(p).split()):
            found = _locate(p, quote)
            if found:
                first, last = found
                first.addprevious(start)
                last.addnext(end)
                end.addnext(_reference_run(comment_id))
                return
    # Not found: the whole paragraph it was made on (or the first paragraph).
    p = order[0] if order else body.find(q("p"))
    ppr = p.find(q("pPr"))
    at = 0 if ppr is None else p.index(ppr) + 1
    p.insert(at, start)
    p.append(end)
    p.append(_reference_run(comment_id))


def _extras(pkg: Package, para_id: str, author: str, date: str) -> None:
    """Keep Word's optional comment parts consistent when the file has them."""
    rnd = int(hashlib.sha1(para_id.encode()).hexdigest()[8:16], 16) & 0x7FFFFFFE
    durable = f"{max(rnd, 1):08X}"
    if pkg.has(IDS):
        etree.SubElement(pkg.xml(IDS), f"{{{W16CID}}}commentId", {f"{{{W16CID}}}paraId": para_id, f"{{{W16CID}}}durableId": durable})
    if pkg.has(EXTENSIBLE):
        etree.SubElement(pkg.xml(EXTENSIBLE), f"{{{W16CEX}}}commentExtensible",
                         {f"{{{W16CEX}}}durableId": durable, f"{{{W16CEX}}}dateUtc": date})
    if pkg.has(PEOPLE):
        people = pkg.xml(PEOPLE)
        if not any(_attr(p, W15, "author") == author for p in people):
            person = etree.SubElement(people, f"{{{W15}}}person", {f"{{{W15}}}author": author})
            etree.SubElement(person, f"{{{W15}}}presenceInfo", {f"{{{W15}}}providerId": "None", f"{{{W15}}}userId": author})

