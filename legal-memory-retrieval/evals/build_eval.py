#!/usr/bin/env python3
"""Build ~500 gold questions from the frozen corpus. Does not regenerate documents."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from app.config import settings

NEGATIVE_TOPICS = [
    "nuclear submarine licensing",
    "Antarctic mining concessions",
    "space debris liability treaties",
    "veterinary malpractice in equine surgery",
    "cryptocurrency mixer registration in Liechtenstein",
    "deep-sea nodule harvesting in the Clarion-Clipperton Zone",
    "satellite mega-constellation spectrum auctions in Bhutan",
    "war-crimes defence for foreign heads of state",
]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def main() -> None:
    corpus = Path(settings.corpus_dir)
    if not corpus.is_absolute():
        corpus = (ROOT / corpus).resolve()

    members = load_json(corpus / "members.json")
    clients = load_json(corpus / "clients.json")
    matters = load_json(corpus / "matters.json")
    permissions = load_json(corpus / "permissions.json")
    docs_by_matter: dict[str, list[dict]] = defaultdict(list)
    for doc in iter_jsonl(corpus / "documents.jsonl"):
        docs_by_matter[doc["matter_id"]].append(doc)

    questions: list[dict] = []
    qid = 0

    def add(qtype: str, level: int, question: str, **extra) -> None:
        nonlocal qid
        qid += 1
        questions.append({"question_id": f"Q-{qid:04d}", "type": qtype, "level": level, "question": question, **extra})

    # Exact matter-code lookups
    for matter in matters[:220]:
        docs = docs_by_matter[matter["matter_id"]]
        add(
            "exact",
            1,
            f"What is the matter code for {matter['title']}?",
            expected_answer=matter["matter_code"],
            expected_matters=[matter["matter_id"]],
            expected_documents=[d["document_id"] for d in docs[:3]],
        )

    by_client: dict[str, list[dict]] = defaultdict(list)
    for matter in matters:
        by_client[matter["client_id"]].append(matter)
    clients_by_id = {c["client_id"]: c for c in clients}
    n_hist = 0
    for client_id, ms in by_client.items():
        if len(ms) >= 3 and n_hist < 40:
            client = clients_by_id[client_id]
            add(
                "matter_retrieval",
                1,
                f"What have we previously done for {client['name']}?",
                expected_matters=[m["matter_id"] for m in ms],
                expected_documents=[docs_by_matter[m["matter_id"]][0]["document_id"] for m in ms if docs_by_matter[m["matter_id"]]],
            )
            n_hist += 1

    by_theme: dict[str, list[dict]] = defaultdict(list)
    for matter in matters:
        by_theme[matter["theme_key"]].append(matter)

    theme_questions = {
        "flood_force_majeure": (
            2,
            "similar_matter",
            "Have we previously handled a construction arbitration involving flooding and force majeure?",
        ),
        "spa_indemnity_cap": (
            2,
            "similar_matter",
            "Have we negotiated SPA indemnity caps on manufacturing acquisitions?",
        ),
        "cirp": (2, "similar_matter", "Have we acted on IBC CIRP or liquidation petitions?"),
        "sebi_insider": (2, "semantic", "Have we advised on unpublished price sensitive information or insider trading SCNs?"),
        "employment_exit": (2, "semantic", "Have we advised on post-employment non-competes and restraint of trade?"),
        "title_diligence": (2, "semantic", "Have we done title diligence involving unregistered family settlements?"),
        "transfer_pricing": (2, "semantic", "Have we handled transfer pricing adjustments on intra-group management fees?"),
        "loan_security": (2, "similar_matter", "Have we enforced share pledges after payment defaults?"),
        "shareholder_oppression": (2, "similar_matter", "Have we acted on oppression and mismanagement petitions?"),
        "commercial_arb": (2, "semantic", "Have we handled supply-contract terminations for quality failures?"),
        "jv": (2, "semantic", "Have we advised on 50:50 joint venture deadlocks and shotgun clauses?"),
        "investment_arb": (2, "similar_matter", "Have we acted on treaty claims alleging expropriation after licence cancellation?"),
    }
    for theme, (level, qtype, text) in theme_questions.items():
        ms = by_theme.get(theme) or []
        if not ms:
            continue
        docs = []
        for m in ms[:12]:
            docs.extend(d["document_id"] for d in docs_by_matter[m["matter_id"]][:2])
        add(qtype, level, text, expected_matters=[m["matter_id"] for m in ms], expected_documents=docs[:20])

    add(
        "semantic",
        2,
        "Have we dealt with natural disasters affecting contractual performance?",
        expected_matters=[m["matter_id"] for m in by_theme.get("flood_force_majeure", [])],
        expected_documents=[
            d["document_id"]
            for m in by_theme.get("flood_force_majeure", [])[:8]
            for d in docs_by_matter[m["matter_id"]]
            if d["document_type"] in {"Research Memo", "Statement of Claim", "Hearing Notes"}
        ][:20],
    )

    for area in ["Arbitration", "M&A", "Insolvency", "Tax", "Employment", "Real Estate", "Regulatory"]:
        experts = [
            m["member_id"]
            for m in members
            if area in m.get("practice_areas", []) or any(area.split()[0] in s for s in m.get("specializations", []))
        ]
        related = [mt["matter_id"] for mt in matters if mt["practice_area"] == area][:15]
        if experts:
            add(
                "person_expertise",
                2,
                f"Which lawyers have experience in {area}?",
                expected_members=experts,
                expected_matters=related,
            )

    infra_ids = {c["client_id"] for c in clients if c.get("industry") == "Infrastructure"}
    flood = by_theme.get("flood_force_majeure", [])
    infra_flood = [m for m in flood if m["client_id"] in infra_ids]
    add(
        "multi_hop",
        3,
        "Which lawyers worked on matters involving force majeure for infrastructure clients?",
        expected_members=sorted({mm["member_id"] for m in infra_flood for mm in m["matter_members"]}),
        expected_matters=[m["matter_id"] for m in infra_flood],
    )

    for matter in flood[:40]:
        docs = docs_by_matter[matter["matter_id"]]
        add(
            "cross_document",
            4,
            f"What was our position regarding the {matter.get('claim_amount')} flooding-related force majeure dispute in {matter['matter_code']}?",
            expected_matters=[matter["matter_id"]],
            expected_documents=[d["document_id"] for d in docs if d["document_type"] in {"Research Memo", "Statement of Claim", "Hearing Notes", "Award Summary", "Client Email"}][:8],
            requires_cross_document=True,
        )

    spa = [m for m in matters if m.get("theme_key") == "spa_indemnity_cap"]
    for matter in spa[:40]:
        docs = docs_by_matter[matter["matter_id"]]
        version_docs = [d["document_id"] for d in docs if d.get("version") or d["document_type"] == "Partner Note"]
        add(
            "versioning",
            4,
            f"Why did we change the indemnity clause on {matter['matter_code']}?",
            expected_matters=[matter["matter_id"]],
            expected_documents=version_docs or [d["document_id"] for d in docs[:4]],
        )

    partner_matters: dict[str, list[dict]] = defaultdict(list)
    for matter in matters:
        partner_matters[matter["matter_members"][0]["member_id"]].append(matter)
    n_graph = 0
    for lead, ms in partner_matters.items():
        if n_graph >= 15:
            break
        if len({m["client_id"] for m in ms}) < 2:
            continue
        seed = ms[0]
        related = [m["matter_id"] for m in ms if m["client_id"] != seed["client_id"]]
        add(
            "graph_reasoning",
            5,
            f"Find matters related to {seed['matter_id']} handled by the same lead lawyer but for different clients.",
            expected_matters=related,
            expected_members=[lead],
            seed_matter=seed["matter_id"],
        )
        n_graph += 1

    add(
        "argument_retrieval",
        3,
        "What arguments have we previously used for force majeure in construction arbitrations?",
        expected_matters=[m["matter_id"] for m in flood],
        expected_issue="Force majeure",
        expected_documents=[
            d["document_id"]
            for m in flood[:10]
            for d in docs_by_matter[m["matter_id"]]
            if d["document_type"] in {"Draft Arguments", "Final Arguments", "Research Memo"}
        ][:20],
    )

    for topic in NEGATIVE_TOPICS:
        add(
            "negative",
            6,
            f"Have we advised on {topic}?",
            expected_matters=[],
            expected_documents=[],
            expected_answer="I couldn't find sufficient evidence in the firm's knowledge base.",
        )

    perm_by = {p["matter_id"]: p for p in permissions}
    restricted = [p for p in permissions if p.get("restricted")]
    outsider = next(m["member_id"] for m in members if True)
    for perm in restricted[:30]:
        matter = next(m for m in matters if m["matter_id"] == perm["matter_id"])
        outsider = next(m["member_id"] for m in members if m["member_id"] not in perm["allowed_members"])
        insider = perm["allowed_members"][0]
        add(
            "permission",
            7,
            f"What happened in {matter['matter_id']}?",
            as_member=insider,
            expected_access="AUTHORIZED",
            expected_matters=[matter["matter_id"]],
            expected_documents=[d["document_id"] for d in docs_by_matter[matter["matter_id"]][:3]],
        )
        add(
            "permission",
            7,
            f"What happened in {matter['matter_id']}?",
            as_member=outsider,
            expected_access="DENIED",
            expected_matters=[],
            expected_documents=[],
            expected_answer="ACCESS DENIED / NO KNOWLEDGE AVAILABLE",
        )

    out = ROOT / "evals" / "dataset.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in questions:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    types: dict[str, int] = defaultdict(int)
    for q in questions:
        types[q["type"]] += 1
    print(json.dumps({"questions": len(questions), "types": dict(types), "path": str(out)}, indent=2))


if __name__ == "__main__":
    main()
