"""Legal research eval (design doc §22.14): gates and scorecard evidence for R1-local.

    python evals/research/research_eval.py            # provider-level metrics (no LLM)
    python evals/research/research_eval.py --json out.json

Retrieval compares three systems on the same issue questions:
  baseline   the firm-wide search the assistant had before (search_firm_records → retrieve)
  authority  search_authority without the citation-graph candidates
  authority+graph  search_authority as shipped

Gold answers come from legal knowledge (landmark holdings and resolutions), not
from this code; binding labels are hand-assigned by legal category, and the
paragraph is located by its text. ``split`` separates items used while
building (dev) from held-out ones (test).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.caselaw.courtlistener_client import CourtListenerClient  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.research import local_provider as lp  # noqa: E402
from app.research.citations import extract_citations, parse_citation  # noqa: E402
from app.research.legal_systems import Forum, label_for  # noqa: E402
from app.research.verify import verify_citations  # noqa: E402
from app.retrieval.engine import retrieve  # noqa: E402

GOLD = Path(__file__).with_name("gold.jsonl")
MEMBER = "MEM-00001"

PARSER_CASES = [
    ("P.C.I.J., Series A, No. 10", "pcij:A:10"), ("PCIJ Ser. A/B No. 53", "pcij:A/B:53"),
    ("P.C.I.J. Series B No. 4", "pcij:B:4"), ("Series A/B, No. 63, p. 12", "pcij:A/B:63"),
    ("I.C.J. Reports 1949, p. 4", "icj:1949:4"), ("ICJ Rep 1986 14", "icj:1986:14"),
    ("S/RES/1373 (2001)", "unsc:1373"), ("S/RES/678(1990), para. 2", "unsc:678"), ("S/RES/2231", "unsc:2231"),
    ("Security Council resolution 242 (1967)", "unsc:242"), ("resolutions 1267 (1999)", "unsc:1267"),
    ("SC Res. 2375", "unsc:2375"), ("UNSC Resolution 1540 (2004)", "unsc:1540"), ("UNSCR 1718", "unsc:1718"),
    ("1155 U.N.T.S. 331", "unts:1155:331"), ("UNTS vol. 1155, p. 331", "unts:1155:331"),
    ("(2008) 4 SCC 755", "in:scc:2008:4:755"), ("AIR 1973 SC 1461", "in:air:1973:sc:1461"),
    ("2023 SCC OnLine SC 123", "in:scconline:2023:sc:123"), ("Civil Appeal No. 10046 of 2025", "in:civil-appeal:10046:2025"),
    ("Civil Appeal Nos. 5399 of 2016", "in:civil-appeal:5399:2016"), ("Appeal No. 163 of 2018", "in:appeal:163:2018"),
    ("APL. 163 of 2018", "in:appeal:163:2018"), ("Petition No. 310/MP/2026", "in:petition:310/MP/2026"),
    ("Petition No. 22 of 2026", "in:petition:22:2026"), ("I.A. No. 1097 of 2026", "in:ia:1097:2026"),
    ("Section 62 of the Electricity Act, 2003", "in:act:electricity-act-2003:s62"),
    ("s. 111(2) of the Electricity Act, 2003", "in:act:electricity-act-2003:s111(2)"),
    ("467 U.S. 837", "us:467 u.s. 837"), ("28 U.S.C. § 1331", "us:28 u.s.c. § 1331"),
]


def _keys_from_hits(hits: list[dict]) -> list[str]:
    out: list[str] = []
    for h in hits:
        k = h.get("key")
        if k and k not in out:
            out.append(k)
    return out


def _baseline_keys(conn, query: str) -> list[str]:
    hits, _ = retrieve(conn, query, MEMBER, k=10)
    keys: list[str] = []
    for h in hits:
        a = lp.get(conn, str(h.get("document_id") or ""), MEMBER)
        k = a["citation"]["key"] if a else None
        if k and k not in keys:
            keys.append(k)
    return keys


def _rank(keys: list[str], expect: list[str]) -> int | None:
    for i, k in enumerate(keys, 1):
        if k in expect:
            return i
    return None


def _summ(ranks: list[int | None]) -> dict[str, float]:
    n = len(ranks) or 1
    return {
        "n": len(ranks),
        "r@1": round(sum(1 for r in ranks if r and r <= 1) / n, 3),
        "r@5": round(sum(1 for r in ranks if r and r <= 5) / n, 3),
        "r@10": round(sum(1 for r in ranks if r and r <= 10) / n, 3),
        "mrr": round(sum(1 / r for r in ranks if r) / n, 3),
    }


def eval_retrieval(conn, items: list[dict]) -> dict[str, Any]:
    systems = {
        "baseline": lambda q: _baseline_keys(conn, q),
        "authority": lambda q: _keys_from_hits(lp.search(conn, q, MEMBER, limit=10, graph_boost=False)),
        "authority+graph": lambda q: _keys_from_hits(lp.search(conn, q, MEMBER, limit=10, graph_boost=True)),
    }
    lp.search(conn, "warm up the models", MEMBER, limit=1)
    rows = []
    lat: dict[str, list[float]] = {s: [] for s in systems}
    for it in items:
        row = {"id": it["id"], "split": it["split"], "collection": it["expect_any"][0].split(":")[0]}
        for name, fn in systems.items():
            t = time.perf_counter()
            keys = fn(it["query"])
            lat[name].append(time.perf_counter() - t)
            row[name] = _rank(keys, it["expect_any"])
            if name == "authority+graph" and not row[name]:
                row["top3"] = keys[:3]
        rows.append(row)
    out: dict[str, Any] = {"rows": rows}
    for name in systems:
        out[name] = {
            "all": _summ([r[name] for r in rows]),
            "test": _summ([r[name] for r in rows if r["split"] == "test"]),
            "pcij": _summ([r[name] for r in rows if r["collection"] == "pcij"]),
            "unsc": _summ([r[name] for r in rows if r["collection"] == "unsc"]),
            "p50_s": round(statistics.median(lat[name]), 2),
        }
    return out


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").lower()


def eval_binding(conn, items: list[dict]) -> dict[str, Any]:
    rows = []
    for it in items:
        res = lp.resolve(conn, parse_citation(it["citation"]), MEMBER)
        if res["resolution"] != "resolved":
            rows.append({**it, "got": None, "ok": False, "why": res.get("reason")})
            continue
        auths = res["authorities"]
        if auths[0]["provider_kind"] == "unsc":
            a = auths[0]
            segs = lp.passages(a, lp.body(conn, a["authority_id"], MEMBER) or "")
            want = _norm(it["para_contains"])
            seg = next((p for p in segs if p.role == "operative" and want in _norm(p.text)), None)
            if seg is None:
                seg = next((p for p in segs if want in _norm(p.text)), None)
            got = label_for(a, Forum("international"), {"role": seg.role, "lead_verb": seg.lead_verb, "para": seg.para} if seg else None)
            rows.append({**it, "got": got.label, "found_as": seg.role if seg else None,
                         "para": seg.para_label if seg else None, "ok": got.label == it["expect_label"]})
        else:
            a = next((x for x in auths if x["role"] == it.get("role", "majority")), auths[0])
            forum = Forum("international", matter_id=a["matter_id"] if it.get("forum_matter") == "same" else "MTR-OTHER")
            got = label_for(a, forum)
            rows.append({**it, "got": got.label, "ok": got.label == it["expect_label"]})
    def acc(rs):
        return round(sum(r["ok"] for r in rs) / (len(rs) or 1), 3)
    return {"accuracy": acc(rows), "accuracy_excl_hard": acc([r for r in rows if not r.get("hard")]),
            "test_accuracy": acc([r for r in rows if r["split"] == "test"]), "n": len(rows),
            "misses": [{k: r.get(k) for k in ("id", "citation", "expect_label", "got", "found_as", "hard", "why")}
                       for r in rows if not r["ok"]]}


def eval_existence(conn, retrieval_items: list[dict]) -> dict[str, Any]:
    real, fake = [], []
    for it in retrieval_items:
        key = it["expect_any"][0]
        if not key.startswith("unsc:"):
            continue
        n = int(key.split(":")[1])
        res = lp.resolve(conn, parse_citation(f"S/RES/{n}"), MEMBER)
        if res["resolution"] != "resolved":
            continue
        year = res["authorities"][0]["citation"]["year"]
        real.append(f"S/RES/{n} ({year})")
        fake.append(f"S/RES/{n} ({year + 1})")
        fake.append(f"S/RES/{n + 5000} ({year})")
    real += ["P.C.I.J., Series A, No. 10", "P.C.I.J., Series B, No. 5", "P.C.I.J., Series A/B, No. 53"]
    fake += [f"P.C.I.J., Series A, No. {n}" for n in (25, 26, 31, 40)] + ["P.C.I.J., Series C, No. 1"]
    unheld = ["I.C.J. Reports 1986, p. 14", "(2008) 4 SCC 755", "Section 62 of the Electricity Act, 2003", "467 U.S. 837"]
    text = lambda cites: " ".join(f"See {c}." for c in cites)  # noqa: E731
    v_real = verify_citations(conn, text(real), MEMBER)["citations"]
    v_fake = verify_citations(conn, text(fake), MEMBER)["citations"]
    v_unheld = verify_citations(conn, text(unheld), MEMBER)["citations"]
    false_verified = [r["citation"] for r in v_fake + v_unheld if r["verdict"] != "not_verified"]
    return {"real": len(real), "real_verified_rate": round(sum(r["verdict"] != "not_verified" for r in v_real) / (len(v_real) or 1), 3),
            "planted_fakes": len(v_fake), "unheld": len(v_unheld), "false_verified": false_verified,
            "false_verified_rate": round(len(false_verified) / (len(v_fake) + len(v_unheld) or 1), 3)}


def eval_pinpoints(conn, retrieval_items: list[dict]) -> dict[str, Any]:
    good, bad = [], []
    for it in retrieval_items[:]:
        key = it["expect_any"][0]
        if not key.startswith("unsc:"):
            continue
        res = lp.resolve(conn, parse_citation(f"S/RES/{key.split(':')[1]}"), MEMBER)
        if res["resolution"] != "resolved":
            continue
        a = res["authorities"][0]
        ops = [p for p in lp.passages(a, lp.body(conn, a["authority_id"], MEMBER) or "") if p.role == "operative" and str(p.para_label).isdigit()]
        if not ops:
            continue
        cite = f"S/RES/{a['citation']['number']} ({a['citation']['year']})"
        good.append(f"{cite}, para. {ops[0].para}")
        bad.append(f"{cite}, para. {len(ops) + 3}")
    good += ["P.C.I.J., Series A, No. 10, p. 5"]
    bad += ["P.C.I.J., Series A, No. 10, p. 900", "P.C.I.J., Series B, No. 5, p. 400"]
    vg = verify_citations(conn, " ".join(f"See {c}." for c in good), MEMBER)["citations"]
    vb = verify_citations(conn, " ".join(f"See {c}." for c in bad), MEMBER)["citations"]
    return {"valid": len(vg), "valid_without_issue": round(sum(not r["issues"] for r in vg) / (len(vg) or 1), 3),
            "wrong": len(vb), "wrong_flagged": round(sum(bool(r["issues"]) for r in vb) / (len(vb) or 1), 3)}


def eval_outage() -> dict[str, Any]:
    client = CourtListenerClient(api_token="eval")
    client.base_url = "http://127.0.0.1:9/api"  # nothing listens: a provider outage
    op = asyncio.run(client.verify_citation("467 U.S. 837"))
    return {"resolution": op.resolution, "verified": op.verified, "ok": not op.verified}


def eval_parser() -> dict[str, Any]:
    misses = [(t, k) for t, k in PARSER_CASES if (parse_citation(f"As in {t}, so here.") or type("x", (), {"key": None})).key != k]
    return {"n": len(PARSER_CASES), "recall": round(1 - len(misses) / len(PARSER_CASES), 3), "misses": misses}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write the full report here")
    args = ap.parse_args()
    items = [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]
    retrieval_items = [i for i in items if i["type"] == "retrieval"]
    binding_items = [i for i in items if i["type"] == "binding"]
    with connect() as conn:
        report = {
            "parser": eval_parser(),
            "existence": eval_existence(conn, retrieval_items),
            "pinpoints": eval_pinpoints(conn, retrieval_items),
            "outage": eval_outage(),
            "binding": eval_binding(conn, binding_items),
            "retrieval": eval_retrieval(conn, retrieval_items),
        }
    gates = {
        "hallucinated/false-verified citations = 0": not report["existence"]["false_verified"],
        "provider failure never verified": report["outage"]["ok"],
        "parser recall >= 0.95": report["parser"]["recall"] >= 0.95,
        "binding-label accuracy >= 0.90 (excl. hard)": report["binding"]["accuracy_excl_hard"] >= 0.90,
        "wrong pinpoints flagged = 100%": report["pinpoints"]["wrong_flagged"] == 1.0,
    }
    report["gates"] = gates
    r = report["retrieval"]
    print("\nRetrieval (expected authority rank; all / held-out test / PCIJ / UNSC):")
    for name in ("baseline", "authority", "authority+graph"):
        s = r[name]
        print(f"  {name:16} all R@1 {s['all']['r@1']:.2f} R@5 {s['all']['r@5']:.2f} R@10 {s['all']['r@10']:.2f} MRR {s['all']['mrr']:.2f}"
              f" | test R@5 {s['test']['r@5']:.2f} MRR {s['test']['mrr']:.2f} | pcij R@5 {s['pcij']['r@5']:.2f} | unsc R@5 {s['unsc']['r@5']:.2f} | p50 {s['p50_s']}s")
    print(f"\nBinding labels: {report['binding']['accuracy']:.2f} (excl. hard {report['binding']['accuracy_excl_hard']:.2f}); misses: {report['binding']['misses']}")
    print(f"Existence: real verified {report['existence']['real_verified_rate']:.2f} of {report['existence']['real']}; "
          f"false-verified {len(report['existence']['false_verified'])} of {report['existence']['planted_fakes'] + report['existence']['unheld']}")
    print(f"Pinpoints: valid clean {report['pinpoints']['valid_without_issue']:.2f}; wrong flagged {report['pinpoints']['wrong_flagged']:.2f}")
    print(f"Parser recall {report['parser']['recall']:.2f} misses {report['parser']['misses']}; outage verified={report['outage']['verified']}")
    print("\nGates:")
    for g, ok in gates.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {g}")
    misses = [row for row in r["rows"] if not row["authority+graph"] or row["authority+graph"] > 5]
    if misses:
        print("\nRetrieval misses at 5 (authority+graph):", [(m["id"], m["authority+graph"], m.get("top3")) for m in misses])
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
