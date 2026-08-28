from __future__ import annotations

from collections import defaultdict
from typing import Any

def generate_evaluation(
    matters: list[dict[str, Any]],
    dnas: dict[str, dict[str, Any]],
    documents: list[dict[str, Any]],
    members: list[dict[str, Any]],
    clients: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    permissions: list[dict[str, Any]],
    negative_topics: list[str],
) -> list[dict[str, Any]]:
    docs_by_matter: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in documents:
        docs_by_matter[doc["matter_id"]].append(doc)

    members_by_id = {m["member_id"]: m for m in members}
    clients_by_id = {c["client_id"]: c for c in clients}
    perm_by_matter = {p["matter_id"]: p for p in permissions}

    questions: list[dict[str, Any]] = []
    qid = 0

    def add(qtype: str, level: int, question: str, **expected: Any) -> None:
        nonlocal qid
        qid += 1
        questions.append(
            {
                "question_id": f"Q-{qid:04d}",
                "type": qtype,
                "level": level,
                "question": question,
                **expected,
            }
        )

    # Level 1 — exact
    for matter in matters[:25]:
        add(
            "exact",
            1,
            f"What is the matter code for {matter['title']}?",
            expected_answer=matter["matter_code"],
            expected_matters=[matter["matter_id"]],
            expected_documents=[d["document_id"] for d in docs_by_matter[matter["matter_id"]][:3]],
        )

    # Repeat-client history
    by_client: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for matter in matters:
        by_client[matter["client_id"]].append(matter)
    for client_id, ms in by_client.items():
        if len(ms) >= 3:
            client = clients_by_id[client_id]
            add(
                "matter_retrieval",
                1,
                f"What have we previously done for {client['name']}?",
                expected_matters=[m["matter_id"] for m in ms],
                expected_documents=[d["document_id"] for m in ms for d in docs_by_matter[m["matter_id"]][:1]],
            )
            break

    # Level 2 — semantic (synonyms, especially flood / FM cluster)
    flood_matters = [m for m in matters if m["theme_key"] == "flood_force_majeure"]
    if flood_matters:
        flood_docs = []
        for m in flood_matters:
            flood_docs.extend(d["document_id"] for d in docs_by_matter[m["matter_id"]] if d["document_type"] in {"Research Memo", "Statement of Claim", "Hearing Notes"})
        add(
            "similar_matter",
            2,
            "Have we previously handled a construction arbitration involving flooding and force majeure?",
            expected_matters=[m["matter_id"] for m in flood_matters],
            expected_documents=flood_docs[:12],
        )
        add(
            "semantic",
            2,
            "Have we dealt with natural disasters affecting contractual performance?",
            expected_matters=[m["matter_id"] for m in flood_matters],
            expected_documents=flood_docs[:12],
        )
        add(
            "semantic",
            2,
            "Have we advised on exceptional circumstances or contractual impossibility in EPC delay claims?",
            expected_matters=[m["matter_id"] for m in flood_matters],
            expected_issue="Force majeure",
        )

    # Expertise retrieval
    arb_experts = [
        m
        for m in members
        if "Arbitration" in m["practice_areas"]
        or any("Arbitration" in s or "Construction" in s for s in m.get("specializations", []))
    ]
    arb_partners = arb_experts
    if arb_partners and flood_matters:
        add(
            "person_expertise",
            2,
            "Who has experience with construction arbitration?",
            expected_members=[m["member_id"] for m in arb_partners],
            expected_matters=[m["matter_id"] for m in flood_matters][:8],
        )

    # Level 3 — multi-hop
    if flood_matters:
        infra_clients = {c["client_id"] for c in clients if c["industry"] == "Infrastructure"}
        infra_flood = [m for m in flood_matters if m["client_id"] in infra_clients]
        lawyer_ids = sorted({mm["member_id"] for m in infra_flood for mm in m["matter_members"]})
        add(
            "multi_hop",
            3,
            "Which lawyers worked on matters involving force majeure for infrastructure clients?",
            expected_members=lawyer_ids,
            expected_matters=[m["matter_id"] for m in infra_flood],
        )

    # Level 4 — cross-document / hidden knowledge
    for matter in flood_matters[:6]:
        dna = dnas[matter["matter_id"]]
        docs = docs_by_matter[matter["matter_id"]]
        amount_docs = [d["document_id"] for d in docs if d.get("contains_amount")]
        court_docs = [d["document_id"] for d in docs if d.get("contains_court")]
        weather_docs = [d["document_id"] for d in docs if d.get("contains_weather_fact")]
        add(
            "cross_document",
            4,
            f"What was our position regarding the {dna['claim_amount']} flooding-related force majeure dispute in {matter['matter_code']}?",
            expected_matters=[matter["matter_id"]],
            expected_documents=list(dict.fromkeys(amount_docs + court_docs + weather_docs))[:8],
            expected_answer_contains=[dna["claim_amount"], dna["court"], dna["outcome"]],
            requires_cross_document=True,
        )

    spa_matters = [m for m in matters if dnas[m["matter_id"]].get("versioned")]
    for matter in spa_matters[:5]:
        dna = dnas[matter["matter_id"]]
        version_docs = [d["document_id"] for d in docs_by_matter[matter["matter_id"]] if d.get("version") or d["document_type"] == "Partner Note"]
        add(
            "versioning",
            4,
            f"Why did we change the indemnity clause on {matter['matter_code']}?",
            expected_matters=[matter["matter_id"]],
            expected_documents=version_docs,
            expected_answer=dna.get("version_reason"),
            expected_answer_contains=dna.get("version_values", []),
        )

    # Level 5 — graph
    partner_matters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for matter in matters:
        lead = matter["matter_members"][0]["member_id"]
        partner_matters[lead].append(matter)
    for lead, ms in partner_matters.items():
        if len({m["client_id"] for m in ms}) >= 2 and any(m["theme_key"] == "flood_force_majeure" for m in ms):
            seed = next(m for m in ms if m["theme_key"] == "flood_force_majeure")
            related = [
                m["matter_id"]
                for m in ms
                if m["client_id"] != seed["client_id"]
            ]
            add(
                "graph_reasoning",
                5,
                f"Find matters related to {seed['matter_id']} handled by the same lead lawyer but for different clients.",
                expected_matters=related,
                expected_members=[lead],
                seed_matter=seed["matter_id"],
            )
            break

    # argument retrieval
    if flood_matters:
        add(
            "argument_retrieval",
            3,
            "What arguments have we previously used for force majeure in construction arbitrations?",
            expected_matters=[m["matter_id"] for m in flood_matters],
            expected_issue="Force majeure",
        )

    # Level 6 — negatives
    for topic in negative_topics:
        add(
            "negative",
            6,
            f"Have we advised on {topic}?",
            expected_matters=[],
            expected_documents=[],
            expected_answer="I couldn't find sufficient evidence in the firm's knowledge base.",
        )

    # Level 7 — permissions
    restricted = [p for p in permissions if p["restricted"]]
    for perm in restricted[:8]:
        matter = next(m for m in matters if m["matter_id"] == perm["matter_id"])
        outsider = next(
            m["member_id"]
            for m in members
            if m["member_id"] not in perm["allowed_members"]
        )
        insider = perm["allowed_members"][0]
        add(
            "permission",
            7,
            f"What happened in {matter['matter_id']}?",
            as_member=insider,
            expected_access="AUTHORIZED",
            expected_matters=[matter["matter_id"]],
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

    # insufficient evidence variant inside corpus (ask for a fact combination that was scattered)
    if flood_matters:
        add(
            "insufficient_evidence",
            6,
            "Quote a single document that states the flooding amount, the Delhi/Bombay forum, and the full force majeure position together.",
            expected_single_document=False,
            note="No single document is guaranteed to contain all three; cross-document synthesis required. Refuse if the system cannot cite multiple docs.",
            expected_matters=[m["matter_id"] for m in flood_matters[:3]],
        )

    return questions
