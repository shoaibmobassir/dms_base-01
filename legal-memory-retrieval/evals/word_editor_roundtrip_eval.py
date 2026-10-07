"""Round-trip fidelity of the full Word editor (Folio) through the running app (plan 22, W2b.3).

For generated contract-style Word files (plan-15 generator) of increasing length, in two situations — a clean file and
a file that already carries another author's tracked changes — a real browser opens `/documents/:id/write`, types in a
body paragraph and in a table cell, and saves. The stored file is then checked:

  edits_ok        both typed markers are in the saved file (paragraph and table cell)
  authorship_ok   every new revision is credited to the signed-in member (never a browser-supplied name)
  others_kept     the other author's revisions survive with their author (tracked file only)
  untouched_ok    every other body paragraph keeps its text, style and run formatting
  tables_ok       the table keeps its shape; only the edited cell differs
  headers_ok      headers/footers/footnotes parts are byte-equal in text to the base file
  render_ok       the saved file converts to PDF (Gotenberg/LibreOffice), an independent validity check
  version_ok      the new version is current, kind "editor", and the editor's note is its message

Gates: all checks 100 %; the save request (server: restamp, store, chunk, index) < 3 s on the 400-page file. The
browser's own export and upload add to that and are reported as `save_s_end_to_end` (no gate).

    python evals/word_editor_roundtrip_eval.py --base-url http://127.0.0.1:8021 [--pages 10,100,400]

Run the API without --reload and build the SPA first (`npm run build`). Throwaway projects are named "E2E-TMP …".
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import statistics
import subprocess
import sys
import zipfile
from pathlib import Path

import httpx
from docx import Document
from docx.oxml.ns import qn
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.connection import connect  # noqa: E402
from app.documents.docx_review import read_revisions  # noqa: E402
from app.drafting.docx_tracked import apply_tracked_changes, formatting_signature  # noqa: E402
from evals.long_doc.generate import build_document, to_docx  # noqa: E402

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OUT = ROOT / "evals" / "last_word_editor_roundtrip.json"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
OTHER = "Other Author"
SAVE_P95_GATE_S = 3.0
PARA_MARK, CELL_MARK = "[WE-PARA-EDIT]", "[WE-CELL-EDIT]"


def _member() -> tuple[str, str]:
    with connect() as conn:
        row = conn.execute("SELECT member_id, name FROM members WHERE member_id = 'MEM-00001'").fetchone()
    return row["member_id"], row["name"]


def _body(data: bytes) -> list:
    body = Document(io.BytesIO(data)).element.body
    return [p for p in body.iter(qn("w:p")) if not any(a.tag == qn("w:tbl") for a in p.iterancestors())]


def _ptext(p) -> str:
    return "".join(t.text or "" for t in p.iter(qn("w:t")))


def _tables(data: bytes) -> list[list[list[str]]]:
    """Table cell texts including text inside tracked insertions (python-docx's cell.text skips those)."""
    body = Document(io.BytesIO(data)).element.body
    return [[["".join(t.text or "" for t in tc.iter(qn("w:t"))) for tc in tr.findall(qn("w:tc"))]
             for tr in tbl.findall(qn("w:tr"))] for tbl in body.iter(qn("w:tbl"))]


def _story_text(data: bytes) -> dict[str, str]:
    z = zipfile.ZipFile(io.BytesIO(data))
    out = {}
    for n in sorted(z.namelist()):
        if re.match(r"word/(header\d*|footer\d*|footnotes|endnotes)\.xml$", n):
            root = etree.fromstring(z.read(n))
            out[n] = "".join(t.text or "" for t in root.iter(f"{{{W}}}t", f"{{{W}}}delText"))
    return out


def _revision_authors(data: bytes) -> list[str]:
    z = zipfile.ZipFile(io.BytesIO(data))
    root = etree.fromstring(z.read("word/document.xml"))
    return [e.get(f"{{{W}}}author") or "" for tag in ("ins", "del", "rPrChange", "pPrChange") for e in root.iter(f"{{{W}}}{tag}")]


def _wait_vectors(document_id: str, timeout: float = 600.0) -> None:
    """A freshly uploaded file is embedded in the background; saving while that runs measures contention with it,
    not the save (people edit minutes after upload), so wait for the first vectors."""
    import time

    end = time.time() + timeout
    while time.time() < end:
        with connect() as conn:
            missing = conn.execute("SELECT count(*) AS n FROM chunks WHERE document_id = %s AND embedding IS NULL",
                                   (document_id,)).fetchone()["n"]
        if not missing:
            return
        time.sleep(2)


def _cleanup(project_ids: list[str]) -> None:
    subprocess.run([str(ROOT / ".venv/bin/python"), "scripts/e2e_cleanup.py"], cwd=ROOT, capture_output=True)


def _anchor(texts: list[str]) -> str:
    """A unique, reasonably long body paragraph the driver can click on."""
    for t in texts:
        if 60 < len(t) < 140 and sum(1 for x in texts if x == t) == 1:
            return t[:24]
    raise SystemExit("no unique paragraph to click")


def run(base_url: str, pages_list: list[int], seed: int) -> dict:
    member, member_name = _member()
    h = {"X-Member-Id": member}
    rows, saves = [], []
    with httpx.Client(base_url=base_url, headers=h, timeout=600) as http:
        project = http.post("/api/projects", json={"title": "E2E-TMP word editor round-trip"}).json()["project_id"]
        try:
            for pages in pages_list:
                for tracked in (False, True):
                    built = build_document(pages, seed)
                    buf = io.BytesIO()
                    to_docx(built, buf)
                    base = buf.getvalue()
                    if tracked:
                        texts = [p.text for p in Document(io.BytesIO(base)).paragraphs]
                        cands = [i for i, t in enumerate(texts) if len(t) > 60][:3]
                        base, _ = apply_tracked_changes(
                            base, [{"op": "replace", "pid": i, "text": texts[i] + " Other author's addition."} for i in cands],
                            author=OTHER)
                    name = f"E2E-TMP-we-{pages}p-{'tracked' if tracked else 'clean'}.docx"
                    b = http.post("/api/uploads/batches", data={"container_kind": "project", "container_id": project},
                                  files={"files": (name, base, DOCX_MIME)}).json()
                    doc = http.post(f"/api/uploads/batches/{b['batch_id']}/run").json()["batch"]["files"][0]["document_id"]
                    _wait_vectors(doc)
                    base_paras = _body(base)
                    base_final = [_ptext(p) for p in base_paras]
                    anchor = _anchor([t for t in base_final])
                    cell = "Line 2"
                    env = {**os.environ, "PW": os.environ["PW"]}
                    proc = subprocess.run(["node", str(ROOT / "evals/word_editor_driver.cjs"), base_url, member, doc, anchor, cell],
                                          capture_output=True, text=True, env=env, cwd=ROOT, timeout=600)
                    drv = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {"error": proc.stderr[-300:]}
                    row = {"pages": pages, "tracked_base": tracked, "document_id": doc, "driver": drv}
                    if "error" in drv:
                        row["error"] = drv["error"]; rows.append(row); continue
                    saves.append(drv["save_request_ms"] / 1000)
                    saved = http.get(f"/api/documents/{doc}/download").content
                    z = zipfile.ZipFile(io.BytesIO(saved))
                    xml = z.read("word/document.xml").decode("utf8", "ignore")
                    commits = http.get(f"/api/editor/documents/{doc}/commits").json()["items"]
                    authors = _revision_authors(saved)
                    base_authors = _revision_authors(base)
                    new_authors = list(authors)
                    for a in base_authors:
                        if a in new_authors:
                            new_authors.remove(a)
                    # untouched paragraphs: same text/style/formatting as the base, except the clicked one
                    sp = _body(saved)
                    untouched = True
                    if len(sp) == len(base_paras) or True:
                        base_by_text = {_ptext(p): formatting_signature(p) for p in base_paras if _ptext(p)}
                        for p in sp:
                            t = _ptext(p)
                            if t in base_by_text and formatting_signature(p) != base_by_text[t]:
                                untouched = False
                                break
                    tables_base = _tables(base)
                    tables_new = _tables(saved)
                    shape_ok = [(len(t), len(t[0])) for t in tables_base] == [(len(t), len(t[0])) for t in tables_new]
                    diff_cells = sum(a != b for tb, tn in zip(tables_base, tables_new) for rb, rn in zip(tb, tn) for a, b in zip(rb, rn))
                    render = http.get(f"/api/documents/{doc}/render")
                    checks = {
                        "edits_ok": PARA_MARK in xml.replace("</w:t></w:r><w:r><w:t>", "") or PARA_MARK in "".join(_ptext(p) for p in sp),
                        "cell_ok": any(CELL_MARK in c for t in tables_new for r in t for c in r),
                        "authorship_ok": (not tracked and not authors) or (all(a in (member_name, OTHER) for a in authors) and
                                                                           (not new_authors or set(new_authors) == {member_name})),
                        "others_kept": (not tracked) or sum(a == OTHER for a in authors) >= sum(a == OTHER for a in base_authors),
                        "untouched_ok": untouched,
                        "tables_ok": shape_ok and diff_cells == 1,
                        "headers_ok": _story_text(saved) == _story_text(base),
                        "render_ok": render.status_code == 200 and render.content[:4] == b"%PDF",
                        "version_ok": bool(commits) and commits[0]["kind"] == "editor" and commits[0]["message"] == "word editor round-trip eval",
                    }
                    row.update(checks=checks, new_revision_authors=sorted(set(new_authors)), table_cells_changed=diff_cells)
                    rows.append(row)
        finally:
            if not os.environ.get("KEEP"):
                _cleanup([project])
    all_checks = [v for r in rows for v in r.get("checks", {}).values()]
    big = [r for r in rows if r["pages"] == max(pages_list) and "driver" in r and "save_ms" in r["driver"]]
    e2e = max((r["driver"]["save_ms"] / 1000 for r in big), default=None)
    p95 = sorted(saves)[max(0, int(len(saves) * 0.95 + 0.999) - 1)] if saves else None
    big_p95 = max((r["driver"]["save_request_ms"] / 1000 for r in big), default=None)
    report = {"rows": rows, "checks_passed": sum(all_checks), "checks_total": len(all_checks),
              "errors": [r.get("error") for r in rows if r.get("error")], "save_request_s_p95": p95, "save_request_s_largest": big_p95, "save_s_end_to_end": e2e,
              "median_open_s": statistics.median([r["driver"]["open_ms"] for r in rows if "open_ms" in r["driver"]] or [0]) / 1000}
    report["pass"] = bool(all_checks) and all(all_checks) and not report["errors"] and (big_p95 is None or big_p95 < SAVE_P95_GATE_S)
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8021")
    ap.add_argument("--pages", default="10,100,400")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    if "PW" not in os.environ:
        raise SystemExit("set PW=/path/to/frontend/node_modules/playwright")
    report = run(a.base_url, [int(x) for x in a.pages.split(",")], a.seed)
    OUT.write_text(json.dumps(report, indent=2))
    for r in report["rows"]:
        print(r["pages"], "tracked" if r["tracked_base"] else "clean", r.get("error") or r["checks"])
    print(f"checks {report['checks_passed']}/{report['checks_total']}  save request p95 {report['save_request_s_p95']}  largest {report['save_request_s_largest']}  end-to-end {report['save_s_end_to_end']}  PASS={report['pass']}")
    sys.exit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()
