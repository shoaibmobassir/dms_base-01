"""Grounding eval: does every sentence a lawyer sees rest on a source that supports it?

Runs the gold questions in ``evals/grounding/gold.jsonl`` through the live HTTP API,
exactly as the UI calls it, for both surfaces:

  * ``ask``  — Ask the Firm, ``POST /api/answers``
  * ``chat`` — Assistant, ``POST /api/chat/sessions/{id}/ask`` (same agent as the stream)

Each answer is split into sentence-level units. Every unit is paired with the evidence the
lawyer is shown for it (Assistant: the quotes behind its ``[n]`` markers; Ask the Firm: the
server-side ``claims`` support when present, else the chunk each ``(DOC-…)`` chip opens).
A judge model that is neither the generator nor the in-product verifier labels each unit:

  claim / non_claim  ·  supported / partial / unsupported / no_evidence

Metrics (per surface, per category):
  citation_precision   supported / cited claims (partial counts as a miss)
  claim_coverage       cited claims / claims
  unverified_shown     claims shown without supporting evidence / claims
  fact_recall          gold facts present in the answer
  expect_ok            abstain / premise-reject items handled correctly
  parametric_claims    legal-rule claims with no supporting evidence (public-law items)

Usage:
    python evals/grounding_eval.py --surface ask,chat --base-url http://127.0.0.1:8000
    python evals/grounding_eval.py --surface chat --only acme-01,pub-01 --tag baseline
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import httpx  # noqa: E402
import psycopg  # noqa: E402

from app.llm.bedrock_client import chat_complete  # noqa: E402
from evals.km_live_eval import contains  # noqa: E402

GOLD = Path(__file__).with_name("grounding") / "gold.jsonl"
OUT_DIR = Path(__file__).with_name("grounding")
MEMBER = "MEM-00001"
JUDGE_MODEL = os.environ.get("GROUNDING_JUDGE_MODEL", "deepseek.v3.2")

_DOC_ID_RE = re.compile(r"\bDOC-[0-9A-F]{5,}\b|\bDOC-\d{5}\b")
_MARKER_RE = re.compile(r"\[(\d{1,3})\]")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\[A-Z(\"'])")
# Legal abbreviations that end with a period but do not end a sentence.
_ABBREV_END = re.compile(r"(?:\b(?:v|vs|No|Nos|Ltd|Pvt|Rs|Co|Corp|Inc|Art|Arts|Reg|Regs|Sec|Cl|para|paras|p|pp|Mr|Ms|Dr|Hon'ble|Anr|Ors|viz|i\.e|e\.g|etc)\.)$", re.I)
_LEAD_REF = re.compile(r"^(?:\s*(?:\[\d+\]|\((?:[^()]*DOC-[^()]*)\)))+")


# ---------------------------------------------------------------------------
# Answer → units
# ---------------------------------------------------------------------------

def split_units(text: str) -> list[str]:
    """Sentence-ish units from markdown prose; headings and table rules dropped."""
    units: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or re.fullmatch(r"[|\-:\s]+", line):
            continue
        if re.fullmatch(r"_\d+ statements? removed because .*_", line):
            continue
        line = re.sub(r"^([-*•]|\d+[.)])\s+", "", line).replace("**", "")
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|") if c.strip()]
            line = " | ".join(cells)
        pieces: list[str] = []
        for piece in _SENT_SPLIT.split(line):
            if pieces and _ABBREV_END.search(pieces[-1]):
                pieces[-1] = f"{pieces[-1]} {piece}"
            else:
                pieces.append(piece)
        for piece in pieces:
            piece = piece.strip()
            # "…ends here. [2] Next sentence": the marker belongs to the previous sentence.
            lead = _LEAD_REF.match(piece)
            if lead and units:
                units[-1] = f"{units[-1]} {lead.group(0).strip()}"
                piece = piece[lead.end():].strip()
            if len(piece.split()) >= 3:
                units.append(piece)
    return units


# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------

class Api:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.h = {"X-Member-Id": MEMBER, "content-type": "application/json"}
        self._titles: dict[str, str] = {}

    def matter_title(self, matter_id: str) -> str:
        if matter_id not in self._titles:
            r = httpx.get(f"{self.base}/api/matters/{matter_id}", headers=self.h, timeout=30)
            self._titles[matter_id] = (r.json() or {}).get("title") or matter_id
        return self._titles[matter_id]

    def ask(self, row: dict) -> dict:
        body: dict = {"query": row["query"], "k": 10}
        if row.get("scope"):
            body["scope"] = {"type": "matter", "value": row["scope"]}
        for _ in range(8):
            r = httpx.post(f"{self.base}/api/answers", json=body, headers=self.h, timeout=300)
            if r.status_code != 429:
                break
            time.sleep(float(r.headers.get("retry-after") or 8))
        return r.json()

    def chat(self, row: dict, mode: str) -> dict:
        s = httpx.post(f"{self.base}/api/chat/sessions", json={}, headers=self.h, timeout=30).json()
        q = row["query"]
        if row.get("scope") and self.matter_title(row["scope"]) not in q:
            q = f"In the matter {self.matter_title(row['scope'])}: {q}"
        r = httpx.post(
            f"{self.base}/api/chat/sessions/{s['id']}/ask",
            json={"content": q, "mode": mode},
            headers=self.h,
            timeout=600,
        )
        out = r.json()
        out["session_id"] = s["id"]
        return out


def _chunk_texts(chunk_ids: list[str]) -> dict[str, str]:
    if not chunk_ids:
        return {}
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        rows = conn.execute("SELECT chunk_id, text FROM chunks WHERE chunk_id = ANY(%s)", (chunk_ids,)).fetchall()
    return {r[0]: r[1] for r in rows}


def units_for_ask(resp: dict) -> tuple[str, list[dict]]:
    """Pair each sentence with the evidence the lawyer can open for it."""
    text = resp.get("answer") or ""
    # Grounded answers: [n] markers point at verified spans, exactly as the chat does.
    if resp.get("span_citations") is not None:
        key = resp.get("key_finding") or ""
        full = f"{key}\n\n{text}" if key else text
        units = units_for_markers(full, resp.get("span_citations") or [])
        verified = (resp.get("grounding") or {}).get("claims") or []
        for u in units:
            ids = re.findall(r"\b(?:MTR-\d{4}-\d+|MEM-\d+)\b", u["text"])
            if not ids:
                continue
            body = _strip_ids(u["text"])
            for c in verified:
                if _strip_ids(c.get("text", "")) == body:
                    u["evidence"] += [f"{sp.get('title')}: \"{sp.get('quote')}\"" for sp in c.get("spans") or []
                                      if not str(sp.get("key", "")).startswith("DOC-")]
            u["cited"] = True
        return full, units
    first_chunk: dict[str, str] = {}
    titles: dict[str, str] = {}
    for s in resp.get("sources") or resp.get("hits") or []:
        did = s.get("document_id")
        if did and did not in first_chunk and s.get("chunk_id"):
            first_chunk[did] = s["chunk_id"]
            titles[did] = s.get("title") or did
    texts = _chunk_texts(list(first_chunk.values()))
    units = []
    for u in split_units(text):
        ids = [d for d in dict.fromkeys(_DOC_ID_RE.findall(u))]
        ev = [f"{titles.get(d, d)}: \"{texts.get(first_chunk.get(d, ''), '')[:1500]}\"" for d in ids if d in first_chunk]
        units.append({"text": u, "evidence": ev, "cited": bool(ids)})
    return text, units


def _strip_ids(text: str) -> str:
    text = re.sub(r"\s*\[\d+\]|\s*\((?:[^()]*(?:DOC|MTR|MEM)-[^()]*)\)", "", text)
    return " ".join(text.replace("**", "").split()).rstrip(".:;")


def units_for_chat(resp: dict) -> tuple[str, list[dict]]:
    msg = resp.get("message") or {}
    text = msg.get("content") or ""
    return text, units_for_markers(text, resp.get("citations") or [])


def units_for_markers(text: str, citations: list[dict]) -> list[dict]:
    by_ref: dict[int, dict] = {}
    for c in citations:
        if isinstance(c.get("ref"), int):
            by_ref[c["ref"]] = c
    units = []
    for u in split_units(text):
        refs = [int(n) for n in _MARKER_RE.findall(u)]
        ev, verified = [], []
        for n in refs:
            c = by_ref.get(n)
            if not c:
                continue
            quotes = [q.get("quote", "") for q in c.get("quotes") or []] or [c.get("quote", "")]
            ev.append(f"{c.get('title', c.get('doc_id'))}: " + " … ".join(f"\"{q}\"" for q in quotes if q))
            verified.append(c.get("verified"))
            if c.get("support"):
                verified.append(c.get("support"))
        units.append({"text": u, "evidence": ev, "cited": bool(refs), "verified": verified})
    return units


# ---------------------------------------------------------------------------
# Judge
# ---------------------------------------------------------------------------

JUDGE_SYSTEM = """You audit a legal research answer sentence by sentence. For each numbered unit you get the \
sentence and the exact evidence text the lawyer is shown for it (possibly none).

For each unit decide:
- kind: "claim" if it asserts a fact about documents, parties, dates, amounts, clauses, arguments, a matter, \
or the content of a law/regulation; "non_claim" for framing, headings, offers of help, or statements that the \
records do not contain something.
- support (only for claims): "supported" if the evidence text on its own entails every factual element of the \
sentence; "partial" if it entails some elements but not all (e.g. the date but not the approval); "unsupported" \
if the evidence does not entail it; "no_evidence" if no evidence text is given.
- legal_rule: true if the claim states the content of a statute, regulation or case law.

Judge only against the given evidence. Your own knowledge of the law is irrelevant.
Return JSON: {"units":[{"i":1,"kind":"claim","support":"partial","legal_rule":false,"why":"<10 words"}], \
"answer_level":{"says_not_in_records":true|false,"rejects_false_premise":true|false}}"""


def judge(query: str, units: list[dict], premise_note: str | None) -> dict:
    lines = []
    for i, u in enumerate(units, 1):
        ev = "\n      ".join(u["evidence"]) if u["evidence"] else "(none)"
        lines.append(f"[{i}] SENTENCE: {u['text']}\n    EVIDENCE: {ev}")
    user = f"QUESTION: {query}\n"
    if premise_note:
        user += f"NOTE ON THE QUESTION (ground truth): {premise_note}\n"
    user += "\nUNITS:\n" + "\n".join(lines)
    for attempt in range(3):
        try:
            r = chat_complete(
                [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}],
                model=JUDGE_MODEL, temperature=0.0, max_tokens=6000, json_mode=True, timeout=180,
            )
            raw = r["content"].strip()
            raw = raw[raw.find("{"): raw.rfind("}") + 1]
            return json.loads(raw)
        except Exception as exc:  # judge hiccups should not kill a run
            err = str(exc)
            time.sleep(3 * (attempt + 1))
    return {"units": [], "answer_level": {}, "error": err}


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

_MONTH_NAMES = "January February March April May June July August September October November December".split()


def _date_forms(value: str) -> list[str]:
    """A gold "16.03.2018" also matches "16 March 2018" (and the reverse)."""
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", value.strip())
    if m and 1 <= int(m.group(2)) <= 12:
        return [value, f"{int(m.group(1))} {_MONTH_NAMES[int(m.group(2)) - 1]} {m.group(3)}"]
    return [value]


def run_one(api: Api, surface: str, row: dict, mode: str) -> dict:
    t0 = time.time()
    try:
        resp = api.ask(row) if surface == "ask" else api.chat(row, mode)
    except Exception as exc:
        return {"id": row["id"], "surface": surface, "error": str(exc)[:300]}
    latency = time.time() - t0
    text, units = units_for_ask(resp) if surface == "ask" else units_for_chat(resp)
    verdict = judge(row["query"], units, row.get("premise_note")) if units else {"units": [], "answer_level": {}}
    labels = {u.get("i"): u for u in verdict.get("units") or []}
    for i, u in enumerate(units, 1):
        u.update({k: labels.get(i, {}).get(k) for k in ("kind", "support", "legal_rule", "why")})
    facts = row.get("facts") or []
    found = [any(contains(text, a) for alt in group for a in _date_forms(alt)) for group in facts]
    return {
        "id": row["id"], "surface": surface, "category": row["category"], "expect": row["expect"],
        "query": row["query"], "answer": text, "units": units, "answer_level": verdict.get("answer_level") or {},
        "judge_error": verdict.get("error"), "fact_recall": (sum(found) / len(found)) if found else None,
        "latency_s": round(latency, 1),
        "status": resp.get("status"), "invented_citations": resp.get("invented_citations"),
    }


def summarise(results: list[dict]) -> dict:
    def block(rs: list[dict]) -> dict:
        claims = [u for r in rs for u in r.get("units", []) if u.get("kind") == "claim"]
        cited = [u for u in claims if u.get("cited")]
        sup = [u for u in cited if u.get("support") == "supported"]
        part = [u for u in cited if u.get("support") == "partial"]
        unverified = [u for u in claims if u.get("support") != "supported"]
        legal_unsup = [u for u in claims if u.get("legal_rule") and u.get("support") != "supported"]
        exp = [r for r in rs if r.get("expect") in ("abstain", "premise_reject")]
        exp_ok = [r for r in exp if (r.get("answer_level") or {}).get("says_not_in_records")
                  or (r.get("answer_level") or {}).get("rejects_false_premise")]
        fr = [r["fact_recall"] for r in rs if r.get("fact_recall") is not None]
        return {
            "n": len(rs), "claims": len(claims), "cited_claims": len(cited),
            "citation_precision": round(len(sup) / len(cited), 3) if cited else None,
            "citation_precision_lenient": round((len(sup) + len(part)) / len(cited), 3) if cited else None,
            "claim_coverage": round(len(cited) / len(claims), 3) if claims else None,
            "unverified_shown": round(len(unverified) / len(claims), 3) if claims else None,
            "parametric_legal_claims": len(legal_unsup),
            "fact_recall": round(statistics.mean(fr), 3) if fr else None,
            "expect_ok": f"{len(exp_ok)}/{len(exp)}" if exp else None,
            "latency_p50_s": round(statistics.median([r["latency_s"] for r in rs if "latency_s" in r]), 1) if rs else None,
            "errors": sum(1 for r in rs if r.get("error") or r.get("judge_error")),
        }

    out: dict = {}
    for surface in sorted({r["surface"] for r in results}):
        rs = [r for r in results if r["surface"] == surface]
        out[surface] = {"overall": block(rs)}
        cats = defaultdict(list)
        for r in rs:
            cats[r.get("category", "?")].append(r)
        out[surface]["by_category"] = {c: block(v) for c, v in sorted(cats.items())}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--surface", default="ask,chat")
    ap.add_argument("--only", default="")
    ap.add_argument("--mode", default="cite", help="Assistant work mode (UI default is cite)")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--tag", default="run")
    args = ap.parse_args()

    rows = [json.loads(l) for l in GOLD.read_text().splitlines() if l.strip()]
    if args.only:
        keep = set(args.only.split(","))
        rows = [r for r in rows if r["id"] in keep or r["category"] in keep]
    api = Api(args.base_url)
    jobs = [(s, r) for s in args.surface.split(",") for r in rows]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(lambda j: run_one(api, j[0], j[1], args.mode), jobs))

    summary = summarise([r for r in results if "units" in r])
    stamp = time.strftime("%Y%m%d-%H%M%S")
    payload = {"tag": args.tag, "at": stamp, "judge": JUDGE_MODEL, "mode": args.mode,
               "summary": summary, "results": results}
    (OUT_DIR / f"last_{args.tag}.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False))
    print(json.dumps(summary, indent=1))
    errs = [r for r in results if r.get("error")]
    if errs:
        print(f"\n{len(errs)} request errors:", [(e["id"], e["surface"], e["error"][:80]) for e in errs])


if __name__ == "__main__":
    main()
