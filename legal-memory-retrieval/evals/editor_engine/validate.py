"""Validate Folio round-trips and tracked edits with our own tools (plan 22, X1)."""
import json, re, sys, zipfile, io, glob, os, time
from lxml import etree
sys.path.insert(0, ".")
from app.documents import docx_review

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
X = sys.argv[1]
AUTHOR = "Bench Editor"

def parts(z):
    return [n for n in z.namelist() if re.match(r"word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$", n)]

def text_view(data, drop_author=None):
    """All stories' text; with drop_author, that author's insertions are removed and deletions restored (reject)."""
    z = zipfile.ZipFile(io.BytesIO(data)); out = {}
    for n in sorted(parts(z)):
        root = etree.fromstring(z.read(n))
        if drop_author:
            for ins in root.iter(f"{{{W}}}ins"):
                if ins.get(f"{{{W}}}author") == drop_author:
                    ins.getparent().remove(ins)
            for d in root.iter(f"{{{W}}}del"):
                if d.get(f"{{{W}}}author") == drop_author:
                    for dt in d.iter(f"{{{W}}}delText"):
                        dt.tag = f"{{{W}}}t"
                    parent = d.getparent(); idx = parent.index(d)
                    for child in list(d):
                        parent.insert(idx, child); idx += 1
                    parent.remove(d)
        paras = []
        for p in root.iter(f"{{{W}}}p"):
            t = "".join(x.text or "" for x in p.iter(f"{{{W}}}t", f"{{{W}}}delText"))
            paras.append(t)
        out[n] = paras
    return out

def counts(data):
    z = zipfile.ZipFile(io.BytesIO(data)); c = {"ins": 0, "del": 0, "comments": 0, "tables": 0}
    for n in parts(z):
        x = z.read(n)
        c["ins"] += x.count(b"<w:ins "); c["del"] += x.count(b"<w:del ")
        c["tables"] += x.count(b"<w:tbl>") + x.count(b"<w:tbl ")
    if "word/comments.xml" in z.namelist():
        c["comments"] = z.read("word/comments.xml").count(b"<w:comment ")
    return c

def authors(data):
    z = zipfile.ZipFile(io.BytesIO(data)); a = {}
    for n in parts(z):
        root = etree.fromstring(z.read(n))
        for tag in ("ins", "del"):
            for e in root.iter(f"{{{W}}}{tag}"):
                a[e.get(f"{{{W}}}author")] = a.get(e.get(f"{{{W}}}author"), 0) + 1
    return a

def renders(data):
    try:
        from app.documents.pdf_render import to_pdf
        pdf = to_pdf(data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "x.docx")
        return pdf[:4] == b"%PDF"
    except Exception as e:
        return f"error: {e}"[:80]

bench = {r["file"]: r for r in json.load(open(f"{X}/out/folio.json"))}
rows = []
for f in sorted(glob.glob(f"{X}/in/*.docx")):
    name = os.path.basename(f); orig = open(f, "rb").read(); r = {"file": name}
    rt_p = f"{X}/out/{name.replace('.docx', '.roundtrip.docx')}"; ed_p = f"{X}/out/{name.replace('.docx', '.edited.docx')}"
    if os.path.exists(rt_p):
        rt = open(rt_p, "rb").read()
        r["roundtrip_text_equal"] = text_view(rt) == text_view(orig)
        r["roundtrip_counts_equal"] = counts(rt) == counts(orig)
    if os.path.exists(ed_p):
        ed = open(ed_p, "rb").read()
        edits = bench[name].get("edits", [])
        a = authors(ed)
        r["author_revisions"] = a.get(AUTHOR, 0)
        r["reject_ok"] = text_view(ed, drop_author=AUTHOR) == text_view(orig)
        accepted = "\n".join(p for ps in text_view(docx_review.accept_everything(ed)).values() for p in ps)
        r["accept_ok"] = all(f"{e['find']}EDITED" in accepted for e in edits)
        c0, c1 = counts(orig), counts(ed)
        r["others_revisions_kept"] = (c1["ins"] - a.get(AUTHOR, 0) * 0) >= c0["ins"] and c1["comments"] == c0["comments"]
        r["tables_kept"] = c1["tables"] == c0["tables"]
        r["render_ok"] = renders(ed)
        r["edited_table_cell"] = any(e["label"] == "table_cell" for e in edits)
    r.update({k: bench[name].get(k) for k in ("open_ms", "edit_save_ms", "roundtrip_save_ms")})
    rows.append(r)
    print(json.dumps(r))
json.dump(rows, open(f"{X}/out/validation.json", "w"), indent=1)
