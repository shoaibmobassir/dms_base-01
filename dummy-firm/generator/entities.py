from __future__ import annotations

from typing import Any


def generate_entities(
    matters: list[dict[str, Any]],
    dnas: dict[str, dict[str, Any]],
    documents: list[dict[str, Any]],
    members: list[dict[str, Any]],
    clients: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(eid: str, etype: str, name: str, **extra: Any) -> None:
        rows.append({"entity_id": eid, "type": etype, "name": name, **extra})

    for m in members:
        add(m["member_id"], "PERSON", m["name"], role=m["role"])
    for c in clients:
        add(c["client_id"], "CLIENT", c["name"], industry=c["industry"])
        add(c["client_id"] + "-ORG", "ORGANIZATION", c["name"])
    for matter in matters:
        dna = dnas[matter["matter_id"]]
        add(matter["matter_id"], "MATTER", matter["title"], matter_code=matter["matter_code"])
        add(f"COURT-{matter['matter_id']}", "COURT", dna["court"])
        add(f"CONTRACT-{matter['matter_id']}", "CONTRACT", dna["contract_type"])
        for i, issue in enumerate(dna["legal_issues"]):
            add(f"ISSUE-{matter['matter_id']}-{i}", "LEGAL_ISSUE", issue)
        for i, statute in enumerate(dna["statutes"]):
            add(f"STATUTE-{matter['matter_id']}-{i}", "STATUTE", statute)
        add(f"LOC-{matter['matter_id']}", "LOCATION", matter["office"])
        add(f"OPP-{matter['matter_id']}", "ORGANIZATION", matter["opposing_party"])

    mentions: list[dict[str, Any]] = []
    for doc in documents:
        matter = next(m for m in matters if m["matter_id"] == doc["matter_id"])
        dna = dnas[matter["matter_id"]]
        mentions.append({"document_id": doc["document_id"], "relation": "belongs_to", "target": matter["matter_id"]})
        mentions.append({"document_id": doc["document_id"], "relation": "concerns", "target": matter["client_id"]})
        if dna["court"] and (dna["court"] in doc["text"] or doc.get("contains_court")):
            mentions.append({"document_id": doc["document_id"], "relation": "mentions", "target": f"COURT-{matter['matter_id']}"})
        for i, issue in enumerate(dna["legal_issues"]):
            if issue.lower() in doc["text"].lower() or any(
                syn.lower() in doc["text"].lower() for syns in dna.get("synonyms", {}).values() for syn in syns
            ):
                mentions.append({"document_id": doc["document_id"], "relation": "discusses", "target": f"ISSUE-{matter['matter_id']}-{i}"})
                break
        for i, statute in enumerate(dna["statutes"]):
            if statute in doc["text"]:
                mentions.append({"document_id": doc["document_id"], "relation": "cites", "target": f"STATUTE-{matter['matter_id']}-{i}"})

    return rows + [{"entity_id": f"MENT-{i:06d}", "type": "MENTION", **m} for i, m in enumerate(mentions, start=1)]
