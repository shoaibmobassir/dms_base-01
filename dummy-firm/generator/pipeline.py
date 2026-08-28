from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from faker import Faker

from generator.arguments import generate_arguments
from generator.clients import generate_clients
from generator.documents import generate_documents_for_matter
from generator.entities import generate_entities
from generator.evaluation import generate_evaluation
from generator.matter_dna import generate_matter_dna
from generator.matters import generate_matters
from generator.members import generate_members
from generator.permissions import generate_permissions
from generator.relationships import generate_relationships
from generator.util import load_config, scale_for, write_json, write_jsonl


def generate_firm(config_path: Path, data_dir: Path, profile: str | None = None) -> dict[str, Any]:
    config = load_config(config_path)
    if profile:
        config["scale"]["profile"] = profile
    scale = scale_for(config)
    rng = random.Random(config.get("seed", 42))
    fake = Faker("en_IN")
    fake.seed_instance(config.get("seed", 42))

    members = generate_members(
        rng,
        fake,
        config["practice_areas"],
        scale["lawyers"],
        scale["support_staff"],
    )
    clients = generate_clients(rng, fake, members, scale["clients"])
    matters = generate_matters(rng, members, clients, config, scale["matters"])

    dnas: dict[str, dict[str, Any]] = {}
    for matter in matters:
        dna = generate_matter_dna(rng, matter)
        dnas[matter["matter_id"]] = dna
        matter["court"] = dna["court"]
        matter["claim_amount"] = dna["claim_amount"]
        matter["outcome"] = dna["outcome"]
        matter["legal_issues"] = dna["legal_issues"]
        matter["facts"] = dna["facts"]

    members_by_id = {m["member_id"]: m for m in members}
    clients_by_id = {c["client_id"]: c for c in clients}

    documents: list[dict[str, Any]] = []
    doc_counter = [0]
    for matter in matters:
        documents.extend(
            generate_documents_for_matter(
                rng=rng,
                matter=matter,
                dna=dnas[matter["matter_id"]],
                members_by_id=members_by_id,
                client=clients_by_id[matter["client_id"]],
                doc_counter=doc_counter,
                min_docs=scale["min_docs_per_matter"],
                max_docs=scale["max_docs_per_matter"],
            )
        )

    relationships = generate_relationships(matters, dnas)
    permissions = generate_permissions(
        rng, matters, dnas, config.get("restricted_matter_fraction", 0.08)
    )
    arguments = generate_arguments(matters, dnas, documents)
    entities = generate_entities(matters, dnas, documents, members, clients)
    evaluation = generate_evaluation(
        matters,
        dnas,
        documents,
        members,
        clients,
        relationships,
        permissions,
        config.get("negative_topics", []),
    )

    data_dir.mkdir(parents=True, exist_ok=True)
    write_json(data_dir / "members.json", members)
    write_json(data_dir / "clients.json", clients)
    write_json(data_dir / "matters.json", matters)
    write_json(data_dir / "matter_dna.json", list(dnas.values()))
    write_json(data_dir / "permissions.json", permissions)
    write_jsonl(data_dir / "documents.jsonl", documents)
    write_jsonl(data_dir / "relationships.jsonl", relationships)
    write_jsonl(data_dir / "arguments.jsonl", arguments)
    write_jsonl(data_dir / "entities.jsonl", entities)
    write_jsonl(data_dir / "evaluation.jsonl", evaluation)

    summary = {
        "firm": config["firm"]["name"],
        "profile": config["scale"]["profile"],
        "members": len(members),
        "clients": len(clients),
        "matters": len(matters),
        "documents": len(documents),
        "relationships": len(relationships),
        "arguments": len(arguments),
        "entities": len(entities),
        "evaluation_questions": len(evaluation),
        "restricted_matters": sum(1 for p in permissions if p["restricted"]),
        "approx_chunks_if_800_tokens": len(documents) * 3,
    }
    write_json(data_dir / "summary.json", summary)
    return summary
