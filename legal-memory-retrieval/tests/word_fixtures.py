"""A small Word file reviewed by three people, built in code (plan 18 tests and e2e fixture).

    p0  "Services Agreement"                         (title, no changes)
    p1  "The Supplier shall deliver [within 30 days]"  Ravi Kalra inserted "within 30 days"
    p2  "The fee is [USD 10,000] payable monthly."     Trilegal deleted "USD 10,000 "
    p3  "Confidential information stays confidential."  Kunal Lalit Kaistha made "Confidential" bold
    p4  "Termination on notice."                        clean (for editing)
    p5  "Governing law is English law."                 Trilegal inserted this whole paragraph
    p6  "Notices go to the registered office."          clean
    p7  "Payment is due on invoice." [moved to p9]       Ravi Kalra moved it (move-from here)
    p8  "Disputes go to arbitration."                   clean
    p9  "Payment is due on invoice."                    (move-to)
Comments: Ravi on p1 ("30 days"), Trilegal's reply; Kunal on p3, resolved.
"""
from __future__ import annotations

import io

from docx import Document
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"

PARAS = [
    "Services Agreement",
    "The Supplier shall deliver ",
    "The fee is ",
    "Confidential information stays confidential.",
    "Termination on notice.",
    "Governing law is English law.",
    "Notices go to the registered office.",
    "Payment is due on invoice.",
    "Disputes go to arbitration.",
    "Payment is due on invoice.",
]
AUTHORS = ("Ravi Kalra", "Trilegal", "Kunal Lalit Kaistha")


def q(t: str) -> str:
    return f"{{{W}}}{t}"


def _run(text: str, deleted: bool = False, bold: bool = False):
    r = etree.Element(q("r"))
    if bold:
        rpr = etree.SubElement(r, q("rPr"))
        etree.SubElement(rpr, q("b"))
    t = etree.SubElement(r, q("delText") if deleted else q("t"))
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return r


def _mark(tag: str, n: int, author: str, date: str):
    return etree.Element(q(tag), {q("id"): str(n), q("author"): author, q("date"): date})


def build() -> bytes:
    d = Document()
    d.add_heading(PARAS[0], level=0)
    for text in PARAS[1:]:
        d.add_paragraph(text)
    body = d.element.body
    ps = body.findall(q("p"))

    # p1: Ravi inserts "within 30 days" (commented)
    ins = _mark("ins", 101, "Ravi Kalra", "2026-09-03T14:53:00Z")
    ins.append(_run("within 30 days"))
    ps[1].append(etree.Element(q("commentRangeStart"), {q("id"): "0"}))
    ps[1].append(ins)
    ps[1].append(etree.Element(q("commentRangeEnd"), {q("id"): "0"}))
    ref = etree.SubElement(ps[1], q("r"))
    etree.SubElement(ref, q("commentReference"), {q("id"): "0"})
    ps[1].append(etree.Element(q("commentRangeStart"), {q("id"): "1"}))  # the reply shares the anchor
    ps[1].append(etree.Element(q("commentRangeEnd"), {q("id"): "1"}))

    # p2: Trilegal deletes "USD 10,000 "
    dele = _mark("del", 102, "Trilegal ", "2026-09-17T14:37:00Z")
    dele.append(_run("USD 10,000 ", deleted=True))
    ps[2].append(dele)
    ps[2].append(_run("payable monthly."))

    # p3: Kunal makes "Confidential" bold (tracked formatting)
    for c in list(ps[3]):
        if c.tag == q("r"):
            ps[3].remove(c)
    bold = _run("Confidential", bold=True)
    change = _mark("rPrChange", 103, "Kunal Lalit Kaistha", "2026-09-16T13:08:00Z")
    etree.SubElement(change, q("rPr"))
    bold.find(q("rPr")).append(change)
    ps[3].insert(0, etree.Element(q("commentRangeStart"), {q("id"): "2"}))
    ps[3].append(bold)
    ps[3].append(etree.Element(q("commentRangeEnd"), {q("id"): "2"}))
    ps[3].append(_run(" information stays confidential."))

    # p5: Trilegal inserted the whole paragraph (content and mark)
    for c in list(ps[5]):
        if c.tag == q("r"):
            ps[5].remove(c)
    ins5 = _mark("ins", 104, "Trilegal", "2026-09-17T15:00:00Z")
    ins5.append(_run(PARAS[5]))
    ps[5].append(ins5)
    ppr = ps[5].find(q("pPr"))
    if ppr is None:
        ppr = etree.Element(q("pPr"))
        ps[5].insert(0, ppr)
    prpr = etree.SubElement(ppr, q("rPr"))
    prpr.append(_mark("ins", 105, "Trilegal", "2026-09-17T15:00:00Z"))

    # p7 → p9: Ravi moved the payment sentence
    for i, tag in ((7, "moveFrom"), (9, "moveTo")):
        for c in list(ps[i]):
            if c.tag == q("r"):
                ps[i].remove(c)
        rng = "moveFromRange" if tag == "moveFrom" else "moveToRange"
        ps[i].append(etree.Element(q(rng + "Start"), {q("id"): str(200 + i), q("name"): "move1",
                                                        q("author"): "Ravi Kalra", q("date"): "2026-09-04T09:25:00Z"}))
        m = _mark(tag, 110 + i, "Ravi Kalra", "2026-09-04T09:25:00Z")
        m.append(_run(PARAS[7], deleted=tag == "moveFrom"))
        ps[i].append(m)
        ps[i].append(etree.Element(q(rng + "End"), {q("id"): str(200 + i)}))

    buf = io.BytesIO()
    d.save(buf)
    return _add_comments(buf.getvalue())


def _add_comments(data: bytes) -> bytes:
    """comments.xml + commentsExtended.xml: Ravi's thread with Trilegal's reply; Kunal's resolved note."""
    from app.documents.docx_comments import COMMENTS, EXTENDED, _comment_element, _ensure_part
    from app.documents.docx_review import Package

    pkg = Package(data)
    comments = _ensure_part(pkg, COMMENTS, q("comments"), {"w": W, "w14": W14})
    extended = _ensure_part(pkg, EXTENDED, f"{{{W15}}}commentsEx", {"w15": W15})
    for cid, para, author, date, text in (
        ("0", "0A000001", "Ravi Kalra", "2026-09-03T15:00:00Z", "Is 30 days agreed with the client?"),
        ("1", "0A000002", "Trilegal ", "2026-09-17T15:20:00Z", "Yes — confirmed on the call."),
        ("2", "0A000003", "Kunal Lalit Kaistha", "2026-09-16T14:16:00Z", "Defined term: keep bold."),
    ):
        comments.append(_comment_element(cid, para, author, date, text))
    etree.SubElement(extended, f"{{{W15}}}commentEx", {f"{{{W15}}}paraId": "0A000001", f"{{{W15}}}done": "0"})
    etree.SubElement(extended, f"{{{W15}}}commentEx", {f"{{{W15}}}paraId": "0A000002", f"{{{W15}}}paraIdParent": "0A000001",
                                                        f"{{{W15}}}done": "0"})
    etree.SubElement(extended, f"{{{W15}}}commentEx", {f"{{{W15}}}paraId": "0A000003", f"{{{W15}}}done": "1"})
    return pkg.save()


if __name__ == "__main__":  # python -m tests.word_fixtures <out.docx>
    import sys

    open(sys.argv[1], "wb").write(build())
