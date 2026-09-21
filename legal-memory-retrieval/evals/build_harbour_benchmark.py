#!/usr/bin/env python3
"""Build retrieval gold for the Harbour Chambers corpus (PCIJ + UNSC + India filings).

Gold comes from corpus files, not from the retriever. This set replaces the
frozen Apex Chambers 445-question file for measuring the live index.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = (ROOT / ".." / "dummy-firm" / "data").resolve()
OUT = ROOT / "evals" / "harbour_benchmark.jsonl"


def _load_json(name: str):
    return json.loads((CORPUS / name).read_text(encoding="utf-8"))


def _iter_jsonl(name: str):
    with (CORPUS / name).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def _row(**fields) -> dict:
    fields.setdefault("level", 1)
    fields.setdefault("as_member", "MEM-00001")
    fields.setdefault("should_abstain", False)
    return fields


def exact_rows() -> list[dict]:
    rows = []
    for raw in _iter_jsonl("evaluation.jsonl"):
        rows.append(
            _row(
                question_id=f"H-{raw['question_id']}",
                type="exact",
                question=raw["question"],
                expected_documents=raw.get("expected_documents") or [],
                expected_matters=raw.get("expected_matters") or [],
                gold_target="document",
            )
        )
    return rows


def argument_rows() -> list[dict]:
    matters = {m["matter_id"]: m for m in _load_json("matters.json")}
    rows = []
    for arg in _iter_jsonl("arguments.jsonl"):
        matter = matters.get(arg["matter_id"], {})
        title = matter.get("title") or arg["matter_id"]
        docs = arg.get("supporting_documents") or []
        if not docs:
            continue
        rows.append(
            _row(
                question_id=f"H-{arg['argument_id']}",
                type="argument",
                level=2,
                question=f"Which documents support our argument on {title}?",
                expected_documents=docs,
                expected_matters=[arg["matter_id"]],
                gold_target="document",
            )
        )
    return rows


def paraphrase_holdout(limit: int = 20) -> list[dict]:
    """Non-templated argument questions. Same gold as argument_rows, different wording.

    These must not use the Harbour prefix, or the holdout only retests E1 strip.
    """
    templates = (
        "Docs that back our position on {title}",
        "What supports the argument in {title}?",
    )
    matters = {m["matter_id"]: m for m in _load_json("matters.json")}
    picked = []
    args = [arg for arg in _iter_jsonl("arguments.jsonl") if arg.get("supporting_documents")]
    if not args:
        return []
    step = max(1, len(args) // limit)
    for arg in args[::step]:
        if len(picked) >= limit:
            break
        matter = matters.get(arg["matter_id"], {})
        title = matter.get("title") or arg["matter_id"]
        template = templates[len(picked) % len(templates)]
        picked.append(
            _row(
                question_id=f"H-PARA-{len(picked)+1:03d}",
                type="argument",
                level=2,
                question=template.format(title=title),
                expected_documents=arg.get("supporting_documents") or [],
                expected_matters=[arg["matter_id"]],
                gold_target="document",
            )
        )
    return picked


def client_rows() -> list[dict]:
    grouped: dict[str, list[str]] = defaultdict(list)
    names: dict[str, str] = {}
    for matter in _load_json("matters.json"):
        name = (matter.get("client_name") or "").strip()
        if not name:
            continue
        grouped[name].append(matter["matter_id"])
        names[name] = name
    rows = []
    for i, name in enumerate(sorted(grouped), start=1):
        rows.append(
            _row(
                question_id=f"H-CLI-{i:03d}",
                type="client_matter",
                question=f"What matters involve {name}?",
                expected_documents=[],
                expected_matters=grouped[name],
                gold_target="matter",
            )
        )
    return rows


def title_rows(limit: int = 48) -> list[dict]:
    rows = []
    seen: set[str] = set()
    for i, doc in enumerate(_iter_jsonl("documents.jsonl")):
        title = (doc.get("title") or "").strip()
        if len(title) < 18 or title in seen:
            continue
        if i % 64 != 0:
            continue
        seen.add(title)
        rows.append(
            _row(
                question_id=f"H-TTL-{len(rows)+1:03d}",
                type="document_title",
                question=f"Find the document titled {title}",
                expected_documents=[doc["document_id"]],
                expected_matters=[doc["matter_id"]],
                gold_target="document",
            )
        )
        if len(rows) >= limit:
            break
    return rows


def related_rows(limit: int = 24) -> list[dict]:
    """One question per (source, relation), with every direct neighbour as gold.

    Edge-level rows shared a question string and made cache hits look like
    separate retrievals. Recall is over the neighbour set.
    """
    allowed = ("same_client", "similar_facts", "precedent_for", "follow_up_to")
    opened: dict[tuple[str, str], list[str]] = {}
    per_type: dict[str, int] = defaultdict(int)
    for edge in _iter_jsonl("relationships.jsonl"):
        rel = edge.get("type") or ""
        if rel not in allowed:
            continue
        source = edge["source"]
        target = edge["target"]
        key = (source, rel)
        if key in opened:
            if target not in opened[key]:
                opened[key].append(target)
            continue
        if per_type[rel] >= 6 or len(opened) >= limit:
            continue
        per_type[rel] += 1
        opened[key] = [target]

    rows = []
    for (source, rel), targets in opened.items():
        if rel == "same_client":
            question = f"Find matters related to {source} for the same client."
        elif rel == "similar_facts":
            question = f"Find matters related to {source} with similar facts."
        elif rel == "precedent_for":
            question = f"Which matter is precedent for {source}?"
        else:
            question = f"What matter is a follow-up to {source}?"
        rows.append(
            _row(
                question_id=f"H-REL-{len(rows)+1:03d}",
                type="related_matter",
                level=3,
                question=question,
                expected_documents=[],
                expected_matters=targets,
                gold_target="matter",
                relationship=rel,
            )
        )
    return rows


def negative_rows() -> list[dict]:
    probes = [
        ("nuclear submarine licensing", ["nuclear submarine", "submarine licensing"]),
        ("bitcoin custody wallet opinion", ["bitcoin", "cryptocurrency", "wallet custody"]),
        ("space mining royalty agreement", ["space mining", "asteroid"]),
        ("employment non-compete for a software startup", ["non-compete", "startup"]),
    ]
    rows = []
    for i, (topic, terms) in enumerate(probes, start=1):
        rows.append(
            _row(
                question_id=f"H-NEG-{i:03d}",
                type="negative",
                question=f"Have we previously advised on {topic}?",
                expected_documents=[],
                expected_matters=[],
                absent_terms=terms,
                should_abstain=True,
                gold_target="absent",
            )
        )
    return rows


def main() -> None:
    semantic = [
        _row(
            question_id="H-SEM-001",
            type="semantic",
            level=2,
            question="Has MSEDCL filed submissions in Appeal 163 of 2018?",
            expected_documents=["DOC-03076", "DOC-03077"],
            expected_matters=["MTR-2018-00166"],
            gold_target="document",
        ),
        _row(
            question_id="H-SEM-002",
            type="semantic",
            level=2,
            question="What documents concern the Lotus collision case before the PCIJ?",
            expected_documents=[
                "DOC-00031", "DOC-00032", "DOC-00033", "DOC-00034",
                "DOC-00035", "DOC-00036", "DOC-00037", "DOC-00038",
            ],
            expected_matters=["MTR-1927-00010"],
            gold_target="document",
        ),
        _row(
            question_id="H-SEM-003",
            type="semantic",
            level=2,
            question="Which filings record UN Security Council resolutions from 1950?",
            expected_documents=[
                "DOC-00338", "DOC-00339", "DOC-00340", "DOC-00341",
                "DOC-00342", "DOC-00343", "DOC-00344", "DOC-00345",
            ],
            expected_matters=["MTR-1950-00088"],
            gold_target="document",
        ),
        _row(
            question_id="H-SEM-004",
            type="semantic",
            level=2,
            question="What is our filing in GMR Warora Energy v CERC Appeal 163 of 2018?",
            expected_documents=["DOC-03076", "DOC-03077"],
            expected_matters=["MTR-2018-00166"],
            gold_target="document",
        ),
    ]
    rows = (
        exact_rows()
        + argument_rows()
        + client_rows()
        + title_rows()
        + related_rows()
        + semantic
        + negative_rows()
    )
    OUT.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["type"]] += 1
    print(json.dumps({"path": str(OUT), "n": len(rows), "by_type": dict(counts)}, indent=2))


if __name__ == "__main__":
    main()
