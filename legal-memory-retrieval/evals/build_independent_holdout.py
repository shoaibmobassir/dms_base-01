#!/usr/bin/env python3
"""Independent search set and gold set for Harbour retrieval.

Gold is read from corpus files, never from the retriever. Questions are
written so they do not copy the official Harbour templates. Those templates
are what unlock argument_scope and title_match. This set checks the engine
on unseen wording and unseen seeds.

Outputs (under evals/):
  independent_search.jsonl     questions only
  independent_gold.jsonl       expected documents / matters only
  independent_retrieval.jsonl  joined file the scoring harness reads
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.build_harbour_benchmark import (
    related_rows,
    title_rows,
    _iter_jsonl,
    _load_json,
    _row,
)

SEARCH_OUT = ROOT / "evals" / "independent_search.jsonl"
GOLD_OUT = ROOT / "evals" / "independent_gold.jsonl"
JOINED_OUT = ROOT / "evals" / "independent_retrieval.jsonl"

FORBIDDEN_PREFIXES = (
    "which documents support our argument on",
    "find the document titled",
    "what matters involve",
    "what is the matter code for",
)


def _official_questions() -> set[str]:
    path = ROOT / "evals" / "harbour_benchmark.jsonl"
    if not path.exists():
        return set()
    return {
        json.loads(line)["question"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def _docs_by_matter() -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for doc in _iter_jsonl("documents.jsonl"):
        grouped[doc["matter_id"]].append(doc["document_id"])
    return grouped


def matter_name_rows() -> list[dict]:
    """Bare matter title. The official set never asks the title alone."""
    rows = []
    seen: set[str] = set()
    for matter in _load_json("matters.json"):
        title = (matter.get("title") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        rows.append(
            _row(
                question_id=f"I-MAT-{len(rows)+1:03d}",
                type="matter_name",
                question=title,
                expected_documents=[],
                expected_matters=[matter["matter_id"]],
                gold_target="matter",
            )
        )
    return rows


def document_name_rows(limit: int = 40) -> list[dict]:
    """Bare document title. Skips titles already in the official title slice."""
    used = {row["expected_documents"][0] for row in title_rows() if row["expected_documents"]}
    rows = []
    for i, doc in enumerate(_iter_jsonl("documents.jsonl")):
        title = (doc.get("title") or "").strip()
        if "\n" in title or len(title) < 18:
            continue
        if doc["document_id"] in used:
            continue
        if i % 47 != 0:
            continue
        rows.append(
            _row(
                question_id=f"I-DOC-{len(rows)+1:03d}",
                type="document_name",
                question=title,
                expected_documents=[doc["document_id"]],
                expected_matters=[doc["matter_id"]],
                gold_target="document",
            )
        )
        if len(rows) >= limit:
            break
    return rows


def matter_code_rows(limit: int = 36) -> list[dict]:
    rows = []
    seen: set[str] = set()
    for matter in _load_json("matters.json"):
        code = (matter.get("matter_code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        if len(seen) % 5 != 0:
            continue
        rows.append(
            _row(
                question_id=f"I-CODE-{len(rows)+1:03d}",
                type="matter_code",
                question=code,
                expected_documents=[],
                expected_matters=[matter["matter_id"]],
                gold_target="matter",
            )
        )
        if len(rows) >= limit:
            break
    return rows


def client_name_rows() -> list[dict]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for matter in _load_json("matters.json"):
        name = (matter.get("client_name") or "").strip()
        if name:
            grouped[name].append(matter["matter_id"])
    rows = []
    for i, name in enumerate(sorted(grouped), start=1):
        rows.append(
            _row(
                question_id=f"I-CLI-{i:03d}",
                type="client_name",
                question=name,
                expected_documents=[],
                expected_matters=grouped[name],
                gold_target="matter",
            )
        )
    return rows


def related_holdout_rows(limit: int = 24) -> list[dict]:
    """Unused seeds. Wording names the stored relation without copying the official sentence."""
    used_keys: set[tuple[str, str]] = set()
    for row in related_rows():
        seed = next((token for token in row["question"].replace("?", "").split() if token.startswith("MTR-")), "")
        if seed and row.get("relationship"):
            used_keys.add((seed, row["relationship"]))

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
        if key in used_keys:
            continue
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
            question = f"Matters related to {source} with the same client."
        elif rel == "similar_facts":
            question = f"Which matters are related to {source} on similar facts?"
        elif rel == "precedent_for":
            question = f"What is the precedent for {source}?"
        else:
            question = f"Which matter is the follow-up to {source}?"
        rows.append(
            _row(
                question_id=f"I-REL-{len(rows)+1:03d}",
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


def paraphrase_rows(limit: int = 40) -> list[dict]:
    """Same supporting-document gold, wording that does not match the official prefix."""
    matters = {m["matter_id"]: m for m in _load_json("matters.json")}
    docs = _docs_by_matter()
    known_docs = {doc_id for ids in docs.values() for doc_id in ids}
    templates = (
        "Papers we filed in {title}",
        "Where is the record of {title}?",
    )
    rows = []
    args = [arg for arg in _iter_jsonl("arguments.jsonl") if arg.get("supporting_documents")]
    step = max(1, len(args) // limit)
    for arg in args[::step]:
        if len(rows) >= limit:
            break
        gold = [doc_id for doc_id in arg["supporting_documents"] if doc_id in known_docs]
        if not gold:
            continue
        title = (matters.get(arg["matter_id"]) or {}).get("title") or arg["matter_id"]
        question = templates[len(rows) % len(templates)].format(title=title)
        rows.append(
            _row(
                question_id=f"I-PARA-{len(rows)+1:03d}",
                type="paraphrase",
                level=2,
                question=question,
                expected_documents=gold,
                expected_matters=[arg["matter_id"]],
                gold_target="document",
            )
        )
    return rows


def negative_rows() -> list[dict]:
    probes = [
        ("quantum computing patent pool", ["quantum computing", "patent pool"]),
        ("deep-sea nodule mining concession", ["nodule mining", "deep-sea"]),
        ("NFT art royalty scheme", ["nft", "non-fungible"]),
        ("urban drone corridor insurance", ["drone corridor", "urban air mobility"]),
    ]
    titles = " ".join(
        (doc.get("title") or "").lower() for doc in _iter_jsonl("documents.jsonl")
    )
    rows = []
    for i, (topic, terms) in enumerate(probes, start=1):
        leaked = [term for term in terms if term in titles]
        if leaked:
            raise SystemExit(f"negative term already in corpus titles: {leaked}")
        rows.append(
            _row(
                question_id=f"I-NEG-{i:03d}",
                type="negative",
                question=f"Has the firm worked on {topic}?",
                expected_documents=[],
                expected_matters=[],
                absent_terms=terms,
                should_abstain=True,
                gold_target="absent",
            )
        )
    return rows


def build_rows() -> list[dict]:
    rows = (
        matter_name_rows()
        + document_name_rows()
        + matter_code_rows()
        + client_name_rows()
        + related_holdout_rows()
        + paraphrase_rows()
        + negative_rows()
    )
    official = _official_questions()
    seen: set[str] = set()
    for row in rows:
        question = row["question"].strip()
        lowered = question.lower()
        if question in seen:
            raise SystemExit(f"duplicate holdout question: {question}")
        if question in official:
            raise SystemExit(f"holdout copies official question: {question}")
        if any(lowered.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
            raise SystemExit(f"holdout uses a tuned prefix: {question}")
        seen.add(question)
    return rows


def write_sets(rows: list[dict]) -> None:
    search_fields = ("question_id", "type", "question", "level", "as_member")
    gold_fields = (
        "question_id",
        "expected_documents",
        "expected_matters",
        "gold_target",
        "absent_terms",
        "should_abstain",
        "relationship",
    )
    search_lines = []
    gold_lines = []
    joined_lines = []
    for row in rows:
        search_lines.append(json.dumps({key: row[key] for key in search_fields if key in row}, ensure_ascii=False))
        gold = {key: row[key] for key in gold_fields if key in row}
        gold_lines.append(json.dumps(gold, ensure_ascii=False))
        joined_lines.append(json.dumps(row, ensure_ascii=False))
    SEARCH_OUT.write_text("\n".join(search_lines) + "\n", encoding="utf-8")
    GOLD_OUT.write_text("\n".join(gold_lines) + "\n", encoding="utf-8")
    JOINED_OUT.write_text("\n".join(joined_lines) + "\n", encoding="utf-8")


def main() -> None:
    rows = build_rows()
    write_sets(rows)
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["type"]] += 1
    print(json.dumps({
        "search": str(SEARCH_OUT),
        "gold": str(GOLD_OUT),
        "joined": str(JOINED_OUT),
        "n": len(rows),
        "by_type": dict(counts),
    }, indent=2))


if __name__ == "__main__":
    main()
