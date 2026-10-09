"""False corrections on PDF text: how many reading artifacts would the Assistant have shown as "fixes"?

    OBJECT_STORE_ROOT=<path to data/object_store> python evals/pdf_artifact_eval.py

Artifacts are mined from the real uploaded PDFs in the database, on the pages the page-provenance detector marks as
scanned (text read by OCR):

  glued     a one-off token that is a common word joined to a function word ("knowledgeand")
  look-alike a one-off token one OCR confusion away from a common word of the same document ("arnount")

Each becomes a proposal "replace the phrase around it with the corrected phrase". Before this change the only test
was that the phrase exists in the extracted text, which it always does, so every one was shown. The guard's
false-correction rate is the share still shown.

Controls that must NOT be blocked (their pass rate is the guard's cost):
  numbers        a changed amount or section number in the same phrase, on a scanned page
  word swaps     a change between two common real words of the document (one letter apart), on a scanned page
  typos in Word  the same artifacts proposed against an editable (docx) source: a real typo fix there is legitimate
  born-digital   the look-alike typo on a born-digital PDF page (text is what the author typed)
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.chat.tools.edit_guard import review_edit  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.documents.text_origin import BORN_DIGITAL, SCANNED_OCR, source_info  # noqa: E402
from app.research.ocr_match import _fold  # noqa: E402

FUNCTION = ("and", "of", "the", "to", "in", "by", "for", "or", "on", "with", "that", "is", "be", "as")
WORD = re.compile(r"[A-Za-z]+")


def _window(text: str, start: int, end: int, words: int = 3) -> tuple[int, int]:
    """Span covering ``words`` words either side of text[start:end], on one line of text."""
    lo, hi = start, end
    for _ in range(words):
        m = re.search(r"\S+\s+$", text[max(0, lo - 30):lo])
        lo = lo - len(m.group(0)) if m else lo
    for _ in range(words):
        m = re.match(r"\s+\S+", text[hi:hi + 30])
        hi = hi + len(m.group(0)) if m else hi
    return lo, hi


def mine(conn) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {"glued": [], "look-alike": [], "numbers": [], "word swaps": [],
                                  "typos in Word": [], "born-digital": []}
    docs = conn.execute("SELECT document_id, title, body FROM documents WHERE mime_type = 'application/pdf'").fetchall()
    for d in docs:
        info = source_info(conn, d["document_id"])
        if info["format"] != "pdf" or not info["origins"]:
            continue
        body = d["body"]
        pages = body.split("\f")
        counts = Counter(w.lower() for w in WORD.findall(body))
        common = {w for w, n in counts.items() if n >= 3 and len(w) >= 4}
        for n, origin in enumerate(info["origins"], start=1):
            if n > len(pages):
                break
            page = pages[n - 1]
            for m in WORD.finditer(page):
                tok, low = m.group(0), m.group(0).lower()
                if counts[low] != 1 or len(low) < 6:
                    continue
                fix = None
                for f in FUNCTION:
                    if low.endswith(f) and low[:-len(f)] in common:
                        fix, kind = tok[:-len(f)] + " " + tok[-len(f):], "glued"
                        break
                    if low.startswith(f) and low[len(f):] in common and len(low) - len(f) >= 5:
                        fix, kind = tok[:len(f)] + " " + tok[len(f):], "glued"
                        break
                if fix is None:
                    for w in common:
                        if abs(len(w) - len(low)) <= 1 and w != low and _fold(w)[0] and _fold(low)[0] and (
                                _fold(w)[0] == _fold(low)[0] or (len(_fold(w)[0]) == len(_fold(low)[0])
                                and sum(a != b for a, b in zip(_fold(w)[0], _fold(low)[0])) <= 1)):
                            fix, kind = w if tok.islower() else w.capitalize(), "look-alike"
                            break
                if fix is None:
                    continue
                lo, hi = _window(page, m.start(), m.end())
                orig = page[lo:hi].strip()
                prop = (page[lo:m.start()] + fix + page[m.end():hi]).strip()
                base = {"doc": d["document_id"], "page": n, "original": orig, "proposed": prop, "doc_text": body}
                if origin == SCANNED_OCR:
                    out[kind].append({**base, "origin": SCANNED_OCR, "format": "pdf"})
                    out["typos in Word"].append({**base, "origin": None, "format": "docx", "kind": kind})
                elif kind == "look-alike":
                    out["born-digital"].append({**base, "origin": BORN_DIGITAL, "format": "pdf"})
            if origin == SCANNED_OCR:
                for m in re.finditer(r"\b\d[\d,.]*\d\b", page):
                    lo, hi = _window(page, m.start(), m.end())
                    orig = page[lo:hi].strip()
                    changed = str(int(re.sub(r"\D", "", m.group(0))[:6] or 0) + 30)
                    out["numbers"].append({"doc": d["document_id"], "page": n, "original": orig,
                                           "proposed": orig.replace(m.group(0), changed, 1), "doc_text": body,
                                           "origin": SCANNED_OCR, "format": "pdf"})
                    if len(out["numbers"]) > 400:
                        break
        pairs = [(a, b) for a in common for b in common if a < b and len(a) == len(b) and len(a) >= 5
                 and sum(x != y for x, y in zip(a, b)) == 1]
        for a, b in pairs[:15]:
            if info["scanned_pages"]:
                out["word swaps"].append({"doc": d["document_id"], "page": info["scanned_pages"][0],
                                          "original": f"the {a} shall", "proposed": f"the {b} shall", "doc_text": body,
                                          "origin": SCANNED_OCR, "format": "pdf"})
    out["synthetic glued"], out["synthetic look-alike"] = _synthesize(conn, docs)
    return out


def _synthesize(conn, docs) -> tuple[list[dict], list[dict]]:
    """Inject the two artifact kinds into scanned-page phrases: spaces dropped, and 'm' read as 'rn'."""
    glued: list[dict] = []
    lookalike: list[dict] = []
    for d in docs:
        info = source_info(conn, d["document_id"])
        if info["format"] != "pdf" or not info["scanned_pages"]:
            continue
        body = d["body"]
        pages = body.split("\f")
        counts = Counter(w.lower() for w in WORD.findall(body))
        for n in info["scanned_pages"]:
            if n > len(pages):
                continue
            page = pages[n - 1]
            for m in re.finditer(r"\b([A-Za-z]{5,})\s+(and|of|the|to|for|with)\b", page):
                if counts[m.group(1).lower()] < 2:
                    continue
                lo, hi = _window(page, m.start(), m.end())
                good = page[lo:hi].strip()
                bad = good.replace(m.group(0), m.group(1) + m.group(2), 1)
                if bad != good and counts[(m.group(1) + m.group(2)).lower()] == 0:
                    glued.append({"doc": d["document_id"], "page": n, "original": bad, "proposed": good,
                                  "doc_text": body, "origin": SCANNED_OCR, "format": "pdf"})
            for m in re.finditer(r"\b[A-Za-z]*m[A-Za-z]*\b", page):
                w = m.group(0)
                if len(w) < 5 or counts[w.lower()] < 3:
                    continue
                corrupt = w.replace("m", "rn", 1)
                if counts[corrupt.lower()] != 0:
                    continue
                lo, hi = _window(page, m.start(), m.end())
                good = page[lo:hi].strip()
                lookalike.append({"doc": d["document_id"], "page": n, "original": good.replace(w, corrupt, 1),
                                  "proposed": good, "doc_text": body.replace(w, corrupt, 1),
                                  "origin": SCANNED_OCR, "format": "pdf"})
    return glued[:300], lookalike[:300]


def main() -> None:
    with connect() as conn:
        sets = mine(conn)
    expect_blocked = {"glued", "look-alike", "synthetic glued", "synthetic look-alike"}
    report: dict[str, dict] = {}
    for name, items in sets.items():
        shown = [it for it in items if review_edit(it["original"], it["proposed"], source_format=it["format"],
                                                    origin=it["origin"], doc_text=it["doc_text"]) is None]
        report[name] = {"n": len(items), "shown": len(shown), "blocked": len(items) - len(shown),
                        "examples_shown": [f'{s["original"][:60]!r} -> {s["proposed"][:60]!r}' for s in shown[:3]]}
    glue_or_ocr = sum(report[k]["n"] for k in expect_blocked)
    leaked = sum(report[k]["shown"] for k in expect_blocked)
    controls = {k: v for k, v in report.items() if k not in expect_blocked}
    summary = {
        "artifacts_real": report["glued"]["n"] + report["look-alike"]["n"],
        "artifacts_synthetic": report["synthetic glued"]["n"] + report["synthetic look-alike"]["n"],
        "false_correction_rate_real_after": round((report["glued"]["shown"] + report["look-alike"]["shown"]) / max(1, report["glued"]["n"] + report["look-alike"]["n"]), 3),
        "false_correction_rate_before": 1.0 if glue_or_ocr else None,  # located in the text => always shown
        "false_correction_rate_after": round(leaked / glue_or_ocr, 3) if glue_or_ocr else None,
        "controls_kept": {k: (round(v["shown"] / v["n"], 3) if v["n"] else None) for k, v in controls.items()},
    }
    out = {"summary": summary, "sets": report}
    Path(__file__).with_name("pdf_artifact_results.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(summary, indent=2))
    for k, v in report.items():
        print(f"{k:14} n={v['n']:4} shown={v['shown']:4} blocked={v['blocked']:4}", *v["examples_shown"][:2], sep="\n    " if v["shown"] else " ")


if __name__ == "__main__":
    main()
