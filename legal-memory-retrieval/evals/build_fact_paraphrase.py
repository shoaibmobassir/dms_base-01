#!/usr/bin/env python3
"""Title-free matter questions. Gold comes from corpus files, not the retriever.

These questions name parties and, when the pair is shared, one distinctive
word. They must not contain the matter title, or containment would solve them.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = (ROOT / ".." / "dummy-firm" / "data").resolve()
OUT = ROOT / "evals" / "fact_paraphrase.jsonl"

_APP = re.compile(r"Applicant\(s\):\s*([^.\n]+)", re.I)
_RESP = re.compile(r"Respondent\(s\):\s*([^.\n]+)", re.I)
_WORD = re.compile(r"[A-ZÀ-Ý][\w'’.-]{3,}")


def _load():
    matters = json.loads((CORPUS / "matters.json").read_text(encoding="utf-8"))
    gold: dict[str, list[str]] = defaultdict(list)
    for line in (CORPUS / "arguments.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        arg = json.loads(line)
        gold[arg["matter_id"]].extend(arg.get("supporting_documents") or [])
    return matters, gold


def _parties(matter: dict) -> tuple[str, str] | None:
    facts = " ".join(matter.get("facts") or [])
    app = _APP.search(facts)
    resp = _RESP.search(facts)
    if not app or not resp:
        return None
    applicant = app.group(1).split(",")[0].strip()
    respondent = resp.group(1).split(",")[0].strip()
    if len(applicant) < 4 or len(respondent) < 4:
        return None
    if "advisory" in respondent.lower():
        return None
    return applicant, respondent


def _distinctive(matter: dict, siblings: list[dict]) -> str | None:
    title = matter.get("title") or ""
    others = " ".join((sib.get("title") or "") for sib in siblings if sib["matter_id"] != matter["matter_id"])
    for word in _WORD.findall(title):
        if word.lower() in {"pcij", "series"}:
            continue
        if word.lower() in others.lower():
            continue
        if word.lower() in title.lower() and title.lower() not in word.lower():
            return word
    return None


def build_rows() -> list[dict]:
    matters, gold = _load()
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for matter in matters:
        parties = _parties(matter)
        if not parties or not gold.get(matter["matter_id"]):
            continue
        grouped[parties].append(matter)

    rows = []
    for (applicant, respondent), group in grouped.items():
        if len(group) != 1:
            continue
        matter = group[0]
        title = matter["title"]
        question = f"Papers we filed in the case {applicant} brought against {respondent}"
        if title.lower() in question.lower():
            continue
        rows.append({
            "question_id": f"F-UNQ-{len(rows)+1:03d}",
            "type": "fact_unique",
            "level": 2,
            "question": question,
            "expected_documents": gold[matter["matter_id"]],
            "expected_matters": [matter["matter_id"]],
            "gold_target": "document",
            "as_member": "MEM-00001",
            "should_abstain": False,
        })
        if len(rows) >= 8:
            break

    amb = 0
    for (applicant, respondent), group in grouped.items():
        if len(group) < 2:
            continue
        for matter in group:
            token = _distinctive(matter, group)
            if not token:
                continue
            title = matter["title"]
            question = (
                f"Papers we filed in the case {applicant} brought against "
                f"{respondent} concerning {token}"
            )
            if title.lower() in question.lower():
                continue
            amb += 1
            rows.append({
                "question_id": f"F-AMB-{amb:03d}",
                "type": "fact_ambiguous",
                "level": 2,
                "question": question,
                "expected_documents": gold[matter["matter_id"]],
                "expected_matters": [matter["matter_id"]],
                "gold_target": "document",
                "as_member": "MEM-00001",
                "should_abstain": False,
            })
            if amb >= 8:
                break
        if amb >= 8:
            break

    for index, topic in enumerate(
        ("quantum computing patent pool", "deep-sea nodule mining concession"),
        start=1,
    ):
        rows.append({
            "question_id": f"F-NEG-{index:03d}",
            "type": "negative",
            "level": 1,
            "question": f"Papers we filed in the case about {topic}",
            "expected_documents": [],
            "expected_matters": [],
            "absent_terms": [topic.split()[0]],
            "gold_target": "absent",
            "as_member": "MEM-00001",
            "should_abstain": True,
        })
    return rows


def main() -> None:
    rows = build_rows()
    OUT.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"n": len(rows), "out": str(OUT)}, indent=2))


if __name__ == "__main__":
    main()
