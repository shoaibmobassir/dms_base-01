from __future__ import annotations

import random
from typing import Any

from generator.themes import THEMES
from generator.util import inr_crore, pick, sample


def generate_matter_dna(rng: random.Random, matter: dict[str, Any]) -> dict[str, Any]:
    theme = THEMES[matter["theme_key"]]
    amount = inr_crore(rng, *theme["amount_range"])
    court = pick(rng, theme["courts"])
    outcome = pick(rng, theme["outcome_pool"])

    extra: dict[str, Any] = {}
    if theme.get("versioned"):
        extra["version_clause"] = theme["version_clause"]
        extra["version_values"] = list(theme["version_values"])
        extra["version_reason"] = theme["version_reason"]
        extra["cap_final"] = theme["version_values"][-1]

    # Per-matter wording variant so similar matters don't clone each other.
    synonym_choice: dict[str, str] = {}
    for concept, variants in theme.get("synonyms", {}).items():
        synonym_choice[concept] = pick(rng, variants)

    return {
        "matter_id": matter["matter_id"],
        "theme_key": matter["theme_key"],
        "theme_label": theme["label"],
        "facts": list(theme["facts"]),
        "legal_issues": list(theme["legal_issues"]),
        "arguments": list(theme["arguments"]),
        "counterarguments": list(theme["counterarguments"]),
        "statutes": list(theme["statutes"]),
        "outcome": outcome,
        "claim_amount": amount,
        "court": court,
        "contract_type": _contract_type(matter["matter_type"]),
        "synonym_choice": synonym_choice,
        "synonyms": theme.get("synonyms", {}),
        "hidden_keys": list(theme.get("hidden_keys", [])),
        "versioned": bool(theme.get("versioned")),
        "restricted_bias": bool(theme.get("restricted_bias")),
        **extra,
    }


def phrase_for(dna: dict[str, Any], concept: str, fallback: str | None = None) -> str:
    return dna["synonym_choice"].get(concept, fallback or concept)


def scatter_facts(rng: random.Random, facts: list[str], n_docs: int) -> list[list[int]]:
    """Each fact is given to a subset of documents; no document gets every fact."""
    assignments: list[list[int]] = [[] for _ in range(n_docs)]
    for fact_i, _ in enumerate(facts):
        holders = sample(rng, list(range(n_docs)), k=max(1, min(3, n_docs - 1)))
        for doc_i in holders:
            assignments[doc_i].append(fact_i)
    # Guarantee no document contains all facts when there are 3+ facts and 3+ docs.
    if len(facts) >= 3 and n_docs >= 3:
        for doc_i, held in enumerate(assignments):
            if len(set(held)) >= len(facts):
                drop = pick(rng, held)
                assignments[doc_i] = [i for i in held if i != drop]
    return assignments


def _contract_type(matter_type: str) -> str:
    mapping = {
        "Construction Arbitration": "EPC Agreement",
        "Construction Dispute": "EPC Agreement",
        "Share Purchase Agreement": "Share Purchase Agreement",
        "Loan Agreement": "Facility Agreement",
        "Facility Agreement": "Facility Agreement",
        "Joint Venture": "Shareholders' Agreement",
        "Development Agreement": "Joint Development Agreement",
        "Commercial Arbitration": "Long-term Supply Agreement",
    }
    return mapping.get(matter_type, f"{matter_type} documents")
