"""Legal Research Bench-style benchmark for the Assistant (arXiv:2610.00609, Vals AI, COLM 2026).

    python evals/research/lrb_bench.py --arms none,before,now --tag r1_local
    python evals/research/lrb_bench.py --calibrate                    # validate the judge first
    python evals/research/lrb_bench.py --arms now --only D01,S01      # a few questions

What it takes from the paper:
  * **All-pass**: a response is correct only if every rubric item passes and the source check passes.
  * **Source check**: every authority the response cites from the firm's collections must resolve, and its
    pinpoint must exist (the paper marks the whole response wrong for an invalid URL).
  * Weighted pass and the failure split: all-pass / lower-tier-only / central-wrong (misses a +3 item).
  * Difficulty marks: reconciliation and temporal validity.
  * An ablation: tools versus single-shot, and here also before versus after this branch's work.
  * The judge is validated before it scores anything.

Arms (same generator model, same research-mode run):
  none    no tools: one model call            (paper Table 4, "1-shot")
  before  the assistant at commit bf4eb59: firm tools only, the old prompt
  now     the assistant as built: authority tools, research method, dated prompt

Honest limits: the paper's judge was validated against practising attorneys; here the judge is validated against
gold and deliberately reversed answers. The questions are written for this firm's corpus (PCIJ, UN Security
Council), by the engineers, not by a panel of lawyers. 24 questions give wide confidence intervals.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_questions import QUESTIONS  # noqa: E402

from app.db.connection import connect  # noqa: E402
from app.llm.bedrock_client import chat_complete  # noqa: E402
from app.research.citations import extract_citations  # noqa: E402
from app.research.legal_systems import Forum  # noqa: E402
from app.research.verify import verify_citations  # noqa: E402

MEMBER = "MEM-00001"
GENERATOR = os.environ.get("BENCH_MODEL", "zai.glm-5")
JUDGE = os.environ.get("BENCH_JUDGE_MODEL", "deepseek.v3.2")  # differs from the generator and the in-product verifier
ARMS = ("none", "before", "now")
OUT = Path(__file__).parent

NO_TOOLS_SYSTEM = (
    "You are a legal research assistant. Answer the question as a careful lawyer would, state the legal rule and "
    "its source, and cite the authorities you rely on with their full citations."
)


# --------------------------------------------------------------------------- running the arms

_PATCH_LOCK = threading.Lock()


def _old_prompt():
    spec = importlib.util.spec_from_file_location("baseline_prompt", OUT / "baseline_system_prompt_bf4eb59.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_system_prompt


class _ArmPatch:
    """Switch the agent's tools and prompt for the duration of an arm (arms run one after another)."""

    def __init__(self, arm: str):
        self.arm = arm

    def __enter__(self):
        import app.chat.agent as agent
        from app.chat.tools.schema import CORE_TOOLS, WORKFLOW_TOOLS

        self.agent, self.saved = agent, (agent.ALL_TOOLS, agent.build_system_prompt)
        if self.arm == "before":
            agent.ALL_TOOLS = CORE_TOOLS + WORKFLOW_TOOLS
            agent.build_system_prompt = _old_prompt()
        return self

    def __exit__(self, *exc):
        self.agent.ALL_TOOLS, self.agent.build_system_prompt = self.saved


def run_question(arm: str, q: dict) -> dict[str, Any]:
    t = time.perf_counter()
    last_err = None
    for attempt in range(2):
        try:
            if arm == "none":
                r = chat_complete([{"role": "system", "content": NO_TOOLS_SYSTEM}, {"role": "user", "content": q["question"]}],
                                  model=GENERATOR, max_tokens=3000, timeout=120)
                text, tools = r.get("content") or "", []
            else:
                from app.chat.agent import run_chat_agent_sync
                from app.chat.tools.document_tools import build_doc_index_from_hits
                from app.retrieval.engine import retrieve

                with connect() as conn:
                    hits, _ = retrieve(conn, q["question"], MEMBER)
                    doc_index = build_doc_index_from_hits(hits)
                    res = run_chat_agent_sync(conn, q["question"], [], doc_index, GENERATOR, member_id=MEMBER,
                                              mode="research", hit_count=len(doc_index), matter=None)
                text = res.get("full_text") or ""
                tools = [e.get("tool") for e in res.get("events", []) if e.get("type") == "tool_started"]
            if text.strip():
                print(f"  {arm} {q['id']} done in {time.perf_counter() - t:.0f}s, {len(tools)} tool calls", file=sys.stderr, flush=True)
                return {"text": text, "tools": tools, "seconds": round(time.perf_counter() - t, 1), "error": None}
            last_err = "empty response"
        except Exception as exc:  # a rate limit or timeout: try once more
            last_err = f"{type(exc).__name__}: {str(exc)[:160]}"
    return {"text": "", "tools": [], "seconds": round(time.perf_counter() - t, 1), "error": last_err}


# --------------------------------------------------------------------------- judging

JUDGE_PROMPT = """You grade a legal research answer against a rubric. Be strict and literal.

QUESTION:
{question}

REFERENCE ANSWER (written by the question's author; the response may use different words):
{gold}

RESPONSE TO GRADE:
\"\"\"
{response}
\"\"\"

For each criterion decide whether the RESPONSE clearly satisfies it. Rules:
- Judge only what the response says. Do not give credit for something implied, hedged into its opposite, or only in the question.
- A criterion that requires a conclusion fails if the response reaches the opposite conclusion or declines to commit.
- A criterion that says the response does NOT do something fails if the response does it.

CRITERIA:
{criteria}

Reply with JSON only: {{"items": [{{"id": "<id>", "pass": true or false, "reason": "<one short sentence>"}}]}}"""


def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


def judge_items(q: dict, response: str) -> dict[str, dict]:
    items = [(f"j{i}", it) for i, it in enumerate(q["rubric"]) if it["kind"] == "judge"]
    if not items:
        return {}
    prompt = JUDGE_PROMPT.format(
        question=q["question"], gold=q["gold"], response=response[:14000],
        criteria="\n".join(f"- id {iid}: {it['text']}" for iid, it in items))
    last = None
    for _ in range(3):
        try:
            out = chat_complete([{"role": "user", "content": prompt}], model=JUDGE, max_tokens=1500, timeout=120)
            data = _parse_json(out.get("content") or "")
            got = {row["id"]: {"pass": bool(row.get("pass")), "reason": str(row.get("reason", ""))[:200]} for row in data["items"]}
            if all(iid in got for iid, _ in items):
                return got
            last = "missing items"
        except Exception as exc:
            last = f"{type(exc).__name__}: {str(exc)[:120]}"
    return {iid: {"pass": False, "reason": f"judge failed: {last}"} for iid, _ in items}


# --------------------------------------------------------------------------- scoring

PINPOINT_ISSUE = re.compile(r"^(Page \d+ is beyond|Paragraph \d+ does not exist)")


def source_check(conn, text: str) -> dict[str, Any]:
    """Every held-collection citation must resolve and have a real pinpoint (the paper's source check)."""
    res = verify_citations(conn, text, MEMBER, forum=Forum("international"))
    bad = []
    for row in res["citations"]:
        if row["resolution"] == "not_found":
            bad.append({"citation": row["citation"], "why": row.get("reason", "does not exist")})
        else:
            for issue in row.get("issues", []):
                if PINPOINT_ISSUE.match(issue):
                    bad.append({"citation": row["citation"], "why": issue})
    return {"ok": not bad, "invalid": bad, "checked": res["count"]}


def score(conn, q: dict, text: str, *, check_sources: bool = True) -> dict[str, Any]:
    judged = judge_items(q, text) if text.strip() else {}
    keys = {c.key for c in extract_citations(text)}
    results = []
    for i, it in enumerate(q["rubric"]):
        if it["kind"] == "judge":
            r = judged.get(f"j{i}", {"pass": False, "reason": "no response"})
            results.append({"w": it["w"], "text": it["text"], "pass": r["pass"], "reason": r["reason"]})
        else:
            ok = all(k in keys for k in it["keys"]) if it.get("all") else any(k in keys for k in it["keys"])
            results.append({"w": it["w"], "text": it["text"], "pass": ok, "reason": "cited" if ok else "not cited"})
    src = source_check(conn, text) if (check_sources and q.get("source_check", True) and text.strip()) else {"ok": True, "invalid": [], "checked": 0}
    total = sum(r["w"] for r in results)
    got = sum(r["w"] for r in results if r["pass"])
    central_wrong = any(r["w"] == 3 and not r["pass"] for r in results)
    rubric_ok = all(r["pass"] for r in results)
    return {"items": results, "weighted": round(got / total, 3) if total else 0.0, "rubric_ok": rubric_ok,
            "source_ok": src["ok"], "source": src, "all_pass": rubric_ok and src["ok"] and bool(text.strip()),
            "central_wrong": central_wrong}


# --------------------------------------------------------------------------- statistics

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def mcnemar(b: int, c: int) -> float:
    """Exact two-sided McNemar p for b, c discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def summarize(rows: list[dict]) -> dict[str, Any]:
    n = len(rows)
    ap = sum(r["score"]["all_pass"] for r in rows)
    lo, hi = wilson(ap, n)
    cw = sum(r["score"]["central_wrong"] for r in rows)
    src_fail = sum(not r["score"]["source_ok"] for r in rows)
    lower_only = sum((not r["score"]["all_pass"]) and (not r["score"]["central_wrong"]) for r in rows)
    return {"n": n, "all_pass": round(ap / n, 3) if n else 0, "ci95": [round(lo, 3), round(hi, 3)],
            "weighted_pass": round(statistics.mean(r["score"]["weighted"] for r in rows), 3) if n else 0,
            "central_wrong": round(cw / n, 3) if n else 0, "lower_tier_only": round(lower_only / n, 3) if n else 0,
            "source_check_failures": src_fail, "fabricated_citations": sum(len(r["score"]["source"]["invalid"]) for r in rows),
            "mean_seconds": round(statistics.mean(r["seconds"] for r in rows), 1) if n else 0,
            "mean_tool_calls": round(statistics.mean(len(r["tools"]) for r in rows), 1) if n else 0,
            "errors": sum(bool(r["error"]) for r in rows)}


# --------------------------------------------------------------------------- calibration

REVERSE_PROMPT = ("Write a confident, plausible answer of at most 120 words to this legal question that reaches the "
                  "OPPOSITE of the correct central conclusion. Do not mention that it is wrong.\n\nQuestion: {q}\n\n"
                  "Correct answer (for reference only): {gold}")


def calibrate(questions: list[dict], workers: int) -> dict[str, Any]:
    def one(q):
        with connect() as conn:
            gold = score(conn, q, q["gold"], check_sources=False)
            rev = chat_complete([{"role": "user", "content": REVERSE_PROMPT.format(q=q["question"], gold=q["gold"])}],
                                model=GENERATOR, max_tokens=500, timeout=90).get("content") or ""
            wrong = score(conn, q, rev, check_sources=False)
        judge_central = [r for r, it in zip(wrong["items"], q["rubric"]) if it["kind"] == "judge" and it["w"] == 3]
        return {"id": q["id"], "gold_judge_items_pass": all(r["pass"] for r, it in zip(gold["items"], q["rubric"]) if it["kind"] == "judge"),
                "gold_failed": [r["text"][:70] + " | " + r["reason"] for r, it in zip(gold["items"], q["rubric"]) if it["kind"] == "judge" and not r["pass"]],
                "reversed_text": rev[:300], "reversed_caught": any(not r["pass"] for r in judge_central) if judge_central else None,
                "reversed_failed": [r["text"][:70] for r in judge_central if not r["pass"]]}
    with ThreadPoolExecutor(workers) as pool:
        rows = list(pool.map(one, questions))
    caught = [r["reversed_caught"] for r in rows if r["reversed_caught"] is not None]
    return {"judge": JUDGE, "generator": GENERATOR, "n": len(rows),
            "gold_accepted": round(sum(r["gold_judge_items_pass"] for r in rows) / len(rows), 3),
            "reversed_rejected": round(sum(caught) / len(caught), 3) if caught else None, "rows": rows}


# --------------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="none,before,now")
    ap.add_argument("--only", help="comma-separated question ids")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--calibrate", action="store_true")
    args = ap.parse_args()
    questions = [q for q in QUESTIONS if not args.only or q["id"] in args.only.split(",")]
    with connect() as conn:  # open the pool and load the models once; workers racing to do it hang or time out
        from app.km.passages import _cross_encode
        from app.retrieval.engine import retrieve as _warm_retrieve

        _warm_retrieve(conn, "warm up the retrieval models", MEMBER)
        _cross_encode("warm up", [{"title": "t", "text": "warm up the reranker"}])

    if args.calibrate:
        rep = calibrate(questions, args.workers)
        (OUT / "results_bench_calibration.json").write_text(json.dumps(rep, indent=2, default=str))
        print(f"judge {rep['judge']} vs generator {rep['generator']}: gold answers accepted {rep['gold_accepted']:.2f}; "
              f"reversed answers rejected {rep['reversed_rejected']}")
        for r in rep["rows"]:
            if not r["gold_judge_items_pass"] or r["reversed_caught"] is False:
                print("  ", r["id"], "gold_failed:", r["gold_failed"], "| reversed_caught:", r["reversed_caught"], "|", r["reversed_text"][:120].replace("\n", " "))
        return

    report: dict[str, Any] = {"tag": args.tag, "generator": GENERATOR, "judge": JUDGE, "n": len(questions), "arms": {}}
    per_arm: dict[str, dict[str, dict]] = {}
    for arm in [a for a in args.arms.split(",") if a in ARMS]:
        t0 = time.perf_counter()
        with _ArmPatch(arm):
            with ThreadPoolExecutor(args.workers) as pool:
                runs = list(pool.map(lambda q: run_question(arm, q), questions))
        rows = []
        with connect() as conn:
            for q, r in zip(questions, runs):
                rows.append({"id": q["id"], "scenario": q["scenario"], "attrs": q["attrs"], **r,
                             "score": score(conn, q, r["text"])})
        per_arm[arm] = {r["id"]: r for r in rows}
        s = summarize(rows)
        s["by_scenario"] = {sc: summarize([r for r in rows if r["scenario"] == sc]) for sc in sorted({r["scenario"] for r in rows})}
        s["by_attribute"] = {a: summarize([r for r in rows if a in r["attrs"]]) for a in ("reconciliation", "temporal")
                             if any(a in r["attrs"] for r in rows)}
        report["arms"][arm] = {"summary": s, "rows": rows, "wall_seconds": round(time.perf_counter() - t0)}
        print(f"[{arm}] all-pass {s['all_pass']:.2f} {s['ci95']} weighted {s['weighted_pass']:.2f} central-wrong {s['central_wrong']:.2f} "
              f"source-fail {s['source_check_failures']} fabricated {s['fabricated_citations']} {s['mean_seconds']}s tools {s['mean_tool_calls']}")
        (OUT / f"results_bench_{args.tag}.json").write_text(json.dumps(report, indent=2, default=str))

    pairs = {}
    for a, b in (("now", "before"), ("now", "none"), ("before", "none")):
        if a in per_arm and b in per_arm:
            ids = list(per_arm[a])
            x = sum(per_arm[a][i]["score"]["all_pass"] and not per_arm[b][i]["score"]["all_pass"] for i in ids)
            y = sum(per_arm[b][i]["score"]["all_pass"] and not per_arm[a][i]["score"]["all_pass"] for i in ids)
            pairs[f"{a} vs {b}"] = {"only_first_passes": x, "only_second_passes": y, "mcnemar_p": round(mcnemar(x, y), 4)}
    report["paired"] = pairs
    (OUT / f"results_bench_{args.tag}.json").write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(pairs, indent=2))


if __name__ == "__main__":
    main()
