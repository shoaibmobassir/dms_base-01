from __future__ import annotations

from typing import Any


def generate_arguments(matters: list[dict[str, Any]], dnas: dict[str, dict[str, Any]], documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    docs_by_matter: dict[str, list[str]] = {}
    for doc in documents:
        docs_by_matter.setdefault(doc["matter_id"], []).append(doc["document_id"])

    rows: list[dict[str, Any]] = []
    arg_i = 0
    for matter in matters:
        dna = dnas[matter["matter_id"]]
        support = docs_by_matter.get(matter["matter_id"], [])[:3]
        for issue in dna["legal_issues"]:
            for side, texts, outcome in (
                ("Client", dna["arguments"], "Partially accepted" if "Partial" in dna["outcome"] else dna["outcome"]),
                ("Opposing party", dna["counterarguments"], "Partially rejected"),
            ):
                for text in texts:
                    arg_i += 1
                    rows.append(
                        {
                            "argument_id": f"ARG-{arg_i:05d}",
                            "matter_id": matter["matter_id"],
                            "issue": issue,
                            "position": side,
                            "argument": text,
                            "outcome": outcome,
                            "supporting_documents": support,
                        }
                    )
    return rows
