from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from generator.matter_dna import phrase_for, scatter_facts
from generator.util import pick


DISPUTE_DOC_SEQUENCE = [
    "Engagement Letter",
    "Initial Case Assessment",
    "Client Email",
    "Research Memo",
    "Statement of Claim",
    "Statement of Defence",
    "Evidence Note",
    "Matter Strategy Note",
    "Hearing Notes",
    "Draft Arguments",
    "Final Arguments",
    "Award Summary",
    "Matter Closure Memo",
]

TRANSACTION_DOC_SEQUENCE = [
    "Engagement Letter",
    "Term Sheet",
    "Due Diligence Report",
    "Share Purchase Agreement",
    "Internal Email",
    "Partner Note",
    "Board Resolution",
    "Closing Checklist",
    "Matter Closure Memo",
]

FINANCE_DOC_SEQUENCE = [
    "Engagement Letter",
    "Loan Agreement",
    "Research Memo",
    "Matter Strategy Note",
    "Internal Email",
    "Application",
    "Partner Note",
    "Matter Closure Memo",
]

GENERIC_DOC_SEQUENCE = [
    "Engagement Letter",
    "Initial Case Assessment",
    "Research Memo",
    "Legal Opinion",
    "Client Email",
    "Matter Strategy Note",
    "Meeting Notes",
    "KM Note",
    "Matter Closure Memo",
]


def generate_documents_for_matter(
    rng: random.Random,
    matter: dict[str, Any],
    dna: dict[str, Any],
    members_by_id: dict[str, dict[str, Any]],
    client: dict[str, Any],
    doc_counter: list[int],
    min_docs: int,
    max_docs: int,
) -> list[dict[str, Any]]:
    sequence = _sequence_for(matter)
    hi = max(min_docs, max_docs)
    lo = min(min_docs, max_docs)
    n = rng.randint(lo, hi)
    plan_types = _plan_types(rng, sequence, n, dna)
    if matter["theme_key"] == "flood_force_majeure":
        required = [
            "Client Email",
            "Research Memo",
            "Statement of Claim",
            "Hearing Notes",
            "Award Summary",
        ]
        for doc_type in required:
            if doc_type not in plan_types:
                plan_types.append(doc_type)
    fact_map = scatter_facts(rng, dna["facts"], len(plan_types))
    opened = date.fromisoformat(matter["opened_date"])

    docs: list[dict[str, Any]] = []
    version_group = None
    for i, doc_type in enumerate(plan_types):
        doc_counter[0] += 1
        doc_id = f"DOC-{doc_counter[0]:05d}"
        author = _author(rng, matter, members_by_id)
        doc_date = opened + timedelta(days=min(i * rng.randint(8, 28), 700))
        include_amount = doc_type in {"Statement of Claim", "Legal Opinion", "Award Summary", "Term Sheet"}
        include_court = doc_type in {"Hearing Notes", "Award Summary", "Statement of Claim", "Application"}
        include_flood_fact = any("flood" in dna["facts"][fi].lower() or "rainfall" in dna["facts"][fi].lower() for fi in fact_map[i])

        body = render_document(
            rng=rng,
            doc_type=doc_type,
            matter=matter,
            dna=dna,
            client=client,
            author=author,
            doc_date=doc_date,
            fact_indices=fact_map[i],
            include_amount=include_amount,
            include_court=include_court,
        )

        version = None
        parent_id = None
        is_spa_v1 = doc_type == "Share Purchase Agreement" and dna.get("versioned")
        if is_spa_v1:
            if version_group is None:
                version_group = doc_id
            version = "v1"
            body = _spa_version(matter, dna, client, author, doc_date, 0)
            include_amount = True

        noise = rng.random() < 0.22
        if noise:
            body = _inject_noise(rng, body, matter)

        docs.append(
            {
                "document_id": doc_id,
                "matter_id": matter["matter_id"],
                "matter_code": matter["matter_code"],
                "client_id": matter["client_id"],
                "title": f"{doc_type} — {matter['title']}",
                "document_type": doc_type,
                "author_id": author["member_id"],
                "author_name": author["name"],
                "date": doc_date.isoformat(),
                "status": "Final" if doc_type not in {"Draft Arguments"} else "Draft",
                "version": version,
                "parent_document_id": parent_id,
                "version_group": version_group,
                "text": body,
                "contains_amount": include_amount,
                "contains_court": include_court,
                "contains_weather_fact": include_flood_fact,
            }
        )

        if is_spa_v1:
            docs.extend(
                _spa_versions(
                    rng,
                    matter,
                    dna,
                    client,
                    author,
                    doc_date,
                    version_group,
                    doc_counter,
                    members_by_id,
                )
            )
    return docs


def _spa_versions(
    rng: random.Random,
    matter: dict[str, Any],
    dna: dict[str, Any],
    client: dict[str, Any],
    author: dict[str, Any],
    v1_date: date,
    version_group: str,
    doc_counter: list[int],
    members_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    extras: list[dict[str, Any]] = []
    labels = ["v2", "v3", "Final"]
    for idx, label in enumerate(labels, start=1):
        doc_counter[0] += 1
        version_date = v1_date + timedelta(days=20 * idx)
        extras.append(
            {
                "document_id": f"DOC-{doc_counter[0]:05d}",
                "matter_id": matter["matter_id"],
                "matter_code": matter["matter_code"],
                "client_id": matter["client_id"],
                "title": f"Share Purchase Agreement ({label}) — {matter['title']}",
                "document_type": "Share Purchase Agreement",
                "author_id": author["member_id"],
                "author_name": author["name"],
                "date": version_date.isoformat(),
                "status": "Final" if label == "Final" else "Draft",
                "version": label,
                "parent_document_id": version_group,
                "version_group": version_group,
                "text": _spa_version(matter, dna, client, author, version_date, idx),
                "contains_amount": True,
                "contains_court": False,
                "contains_weather_fact": False,
            }
        )
    # Internal note explaining the indemnity cap negotiation history
    partner = next(m for m in matter["matter_members"] if m["role_on_matter"] in {"Partner", "Lead"})
    p = members_by_id[partner["member_id"]]
    doc_counter[0] += 1
    extras.append(
        {
            "document_id": f"DOC-{doc_counter[0]:05d}",
            "matter_id": matter["matter_id"],
            "matter_code": matter["matter_code"],
            "client_id": matter["client_id"],
            "title": f"Partner Note — indemnity cap — {matter['title']}",
            "document_type": "Partner Note",
            "author_id": p["member_id"],
            "author_name": p["name"],
            "date": (v1_date + timedelta(days=70)).isoformat(),
            "status": "Final",
            "version": None,
            "parent_document_id": version_group,
            "version_group": version_group,
            "text": (
                f"PRIVILEGED AND CONFIDENTIAL\n\n"
                f"Matter: {matter['title']} ({matter['matter_code']})\n"
                f"From: {p['name']}\n\n"
                f"Clause 14 (Indemnity) moved from {dna['version_values'][0]} "
                f"to {dna['version_values'][1]} and then {dna['version_values'][2]}. "
                f"Final executed cap is {dna['version_values'][-1]}.\n\n"
                f"{dna['version_reason']}\n"
                f"Please retain the negotiation history on the matter file."
            ),
            "contains_amount": True,
            "contains_court": False,
            "contains_weather_fact": False,
        }
    )
    return extras


def _spa_version(
    matter: dict[str, Any],
    dna: dict[str, Any],
    client: dict[str, Any],
    author: dict[str, Any],
    doc_date: date,
    version_index: int,
) -> str:
    cap = dna["version_values"][version_index]
    return f"""SHARE PURCHASE AGREEMENT

Matter: {matter['title']}
Matter Code: {matter['matter_code']}
Client: {client['name']}
Author: {author['name']}
Date: {doc_date.isoformat()}
Version: {['v1', 'v2', 'v3', 'Final'][version_index]}

1. Parties
The Seller and the Buyer identified in Schedule 1 agree to the sale of the Sale Shares in the Target.

2. Consideration
The locked-box equity value is {dna['claim_amount']}, subject to leakage.

3. Conditions
Completion is subject to customary conditions including no material adverse change, excluding industry-wide shocks.

14. Indemnity
The Seller's aggregate liability under the tax and general indemnities is capped at {cap}, except for fraud and fundamental warranties.

15. Escrow
A portion of consideration shall be held in escrow against leakage and pending tax assessments identified in diligence.

This draft is generated for internal working purposes on {matter['matter_code']}.
"""


def render_document(
    rng: random.Random,
    doc_type: str,
    matter: dict[str, Any],
    dna: dict[str, Any],
    client: dict[str, Any],
    author: dict[str, Any],
    doc_date: date,
    fact_indices: list[int],
    include_amount: bool,
    include_court: bool,
) -> str:
    alias = pick(rng, client["aliases"])
    facts = [dna["facts"][i] for i in fact_indices] or [dna["facts"][0]]
    issues = sample_issues(rng, dna)
    fm = phrase_for(dna, "Force majeure", "force majeure")
    flood = phrase_for(dna, "flooding", "the triggering event")
    header = _header(doc_type, matter, client, author, doc_date, alias)

    if doc_type == "Research Memo":
        return header + _research(matter, dna, facts, issues, fm, flood, include_amount, include_court)
    if doc_type in {"Statement of Claim", "Pleading"}:
        return header + _claim(matter, dna, facts, fm, flood, include_amount, include_court, claimant=True)
    if doc_type == "Statement of Defence":
        return header + _claim(matter, dna, facts, fm, flood, include_amount, include_court, claimant=False)
    if doc_type in {"Draft Arguments", "Final Arguments", "Written Submission"}:
        return header + _arguments(matter, dna, facts, fm, include_amount, include_court)
    if doc_type == "Client Email":
        return header + _client_email(alias, facts, flood, include_amount)
    if doc_type == "Hearing Notes":
        return header + _hearing(matter, dna, facts, include_court, include_amount)
    if doc_type == "Award Summary" or doc_type == "Judgment Summary":
        return header + _award(matter, dna, include_amount, include_court)
    if doc_type == "Engagement Letter":
        return header + _engagement(matter, client, dna)
    if doc_type == "Matter Closure Memo":
        return header + _closure(matter, dna, include_amount)
    if doc_type == "Legal Opinion":
        return header + _opinion(matter, dna, facts, issues, include_amount)
    if doc_type == "Matter Strategy Note":
        return header + _strategy(matter, dna, facts)
    return header + _generic(doc_type, matter, dna, facts, issues, include_amount, include_court)


def sample_issues(rng: random.Random, dna: dict[str, Any]) -> list[str]:
    issues = list(dna["legal_issues"])
    rng.shuffle(issues)
    return issues[: max(1, len(issues) - 1)]


def _header(doc_type: str, matter: dict[str, Any], client: dict[str, Any], author: dict[str, Any], doc_date: date, alias: str) -> str:
    return (
        f"{doc_type.upper()}\n\n"
        f"Matter: {matter['title']}\n"
        f"Matter Code: {matter['matter_code']}\n"
        f"Client: {alias}\n"
        f"Author: {author['name']} ({author['role']})\n"
        f"Date: {doc_date.isoformat()}\n"
        f"Office: {matter['office']}\n\n"
    )


def _research(matter, dna, facts, issues, fm, flood, include_amount, include_court) -> str:
    authorities = "; ".join(dna["statutes"])
    amount = dna["claim_amount"] if include_amount else "the quantified claim (see claim documents)"
    court = dna["court"] if include_court else "the contractual forum"
    return f"""QUESTION PRESENTED
Whether {fm} is available on the {dna['contract_type']} in {matter['matter_type']}, and how {flood} interacts with delay and damages.

BACKGROUND
The following facts are presently on file:
{chr(10).join(f'- {f}' for f in facts)}
The engagement concerns {matter['client_name']} in {matter['jurisdiction']}.

LEGAL ISSUE
Primary issues for research: {', '.join(issues)}.

ANALYSIS
Indian contract law (and, where seated abroad, the chosen lex causae) requires a close reading of the {fm} clause against the factual matrix. 
{flood.capitalize()} must be mapped to the clause language, notice requirements, and mitigation. Causation as against concurrent delay remains the usual battleground.
The claim quantum in play is {amount}. Forum: {court}.

ARGUMENTS
For the client: {'; '.join(dna['arguments'][:2])}.
Anticipated pushback: {'; '.join(dna['counterarguments'][:2])}.

AUTHORITIES
{authorities}

CONCLUSION
On the present record, the {fm} case is arguable but fact-sensitive. Recommend preserving contemporaneous notices and independent engineer records.
"""


def _claim(matter, dna, facts, fm, flood, include_amount, include_court, claimant: bool) -> str:
    amount = dna["claim_amount"] if include_amount else "[amount to be inserted from quantum expert]"
    court = dna["court"] if include_court else "the Tribunal"
    role = "CLAIMANT" if claimant else "RESPONDENT"
    position = dna["arguments"] if claimant else dna["counterarguments"]
    return f"""IN THE MATTER OF {matter['title'].upper()}
{court}

{role}'S PLEADING

1. The {dna['contract_type']} governed the works / transaction.
2. Material facts relied upon:
{chr(10).join(f'   {i}. {f}' for i, f in enumerate(facts, 1))}
3. The dispute turns on {fm} and related contractual machinery, including the treatment of {flood}.
4. Relief sought includes determination of liability and {amount}.
5. The {role.lower()} will say: {'; '.join(position)}.

This pleading is filed in {matter['matter_code']} without prejudice to amendment.
"""


def _arguments(matter, dna, facts, fm, include_amount, include_court) -> str:
    amount = f" Quantum: {dna['claim_amount']}." if include_amount else ""
    forum = f" Forum: {dna['court']}." if include_court else ""
    return f"""OUTLINE OF SUBMISSIONS — {matter['matter_code']}

A. Facts relied upon in this draft
{chr(10).join(f'- {f}' for f in facts)}

B. Legal submissions
1. {dna['arguments'][0]}
2. {dna['arguments'][1] if len(dna['arguments']) > 1 else dna['arguments'][0]}
3. The {fm} analysis must remain tethered to the clause, not to abstract hardship.{amount}{forum}

C. Alternative case
{dna['counterarguments'][0]}

D. Outcome sought
{dna['outcome']}
"""


def _client_email(alias, facts, flood, include_amount) -> str:
    extra = " Please also confirm the live quantum figure with finance." if include_amount else ""
    return f"""From: client-contact@{alias.split()[0].lower()}.example
Subject: Re: update

Team — flagging that {flood} is still the factual centre of gravity from our side.
{facts[0]}.
We do not want this email to be a full recitation of the case; the assessment memo has the rest.{extra}

Please call if you need anything from site.
"""


def _hearing(matter, dna, facts, include_court, include_amount) -> str:
    court = dna["court"] if include_court else "Tribunal (seat not restated in these notes)"
    amt = dna["claim_amount"] if include_amount else "quantum parked for expert day"
    return f"""HEARING NOTES — {matter['matter_code']}
Forum: {court}

Panel / Court asked for a one-page chronology. Facts mentioned today:
{chr(10).join(f'- {f}' for f in facts)}

Quantum as stated today: {amt}.
Tribunal appeared interested in contemporaneous notices more than in textbook {dna['legal_issues'][0]}.
Action: pull engineer certificates before the next sitting.
"""


def _award(matter, dna, include_amount, include_court) -> str:
    return (
        f"SUMMARY OF DISPOSITIVE OUTCOME\n"
        f"Forum: {dna['court'] if include_court else 'as per award'}\n"
        f"Outcome: {dna['outcome']}\n"
        f"Amount context: {dna['claim_amount'] if include_amount else 'see confidential quantum schedule'}\n"
        f"Issues determined included {', '.join(dna['legal_issues'][:3])}.\n"
        f"This is an internal working summary, not a substitute for the award/judgment."
    )


def _engagement(matter, client, dna) -> str:
    return f"""We are pleased to confirm our engagement by {client['name']} in connection with {matter['matter_type']} ({matter['matter_code']}).

Scope: advice and representation concerning {dna['theme_label']}.
Retainer: standard Apex Chambers terms. Privilege applies.
Conflicts: checked against {matter['opposing_party']}.
"""


def _closure(matter, dna, include_amount) -> str:
    amt = f" Live quantum at close: {dna['claim_amount']}." if include_amount else ""
    return f"""MATTER CLOSURE
Status: {matter['status']}
Outcome: {dna['outcome']}.{amt}
Lessons: preserve notice trails; {dna['legal_issues'][0]} remains a recurring {matter['practice_area']} theme.
KM: tag this file under {dna['theme_key']}.
"""


def _opinion(matter, dna, facts, issues, include_amount) -> str:
    amt = f" Exposure is in the region of {dna['claim_amount']}." if include_amount else ""
    return f"""LEGAL OPINION (PRIVILEGED)

We are asked to advise {matter['client_name']} on {', '.join(issues)}.
Facts instructed:
{chr(10).join(f'- {f}' for f in facts)}
{amt}

Our opinion: the better view is aligned with: {dna['arguments'][0]}.
Caveat: {dna['counterarguments'][0]}.
This opinion may not be disclosed to third parties without written consent.
"""


def _strategy(matter, dna, facts) -> str:
    return f"""INTERNAL STRATEGY NOTE — {matter['matter_code']}
Do not send to client in this form.

Working theory: {dna['arguments'][0]}.
Facts we are currently willing to lead: {'; '.join(facts)}.
Settlement range to be discussed with the partner after the next evidence dump.
Related KM issue tags: {', '.join(dna['legal_issues'])}.
"""


def _generic(doc_type, matter, dna, facts, issues, include_amount, include_court) -> str:
    bits = [
        f"This {doc_type.lower()} records work on {matter['matter_code']}.",
        f"Issues in view: {', '.join(issues)}.",
        f"Facts touched: {'; '.join(facts)}.",
    ]
    if include_amount:
        bits.append(f"Quantum reference: {dna['claim_amount']}.")
    if include_court:
        bits.append(f"Forum: {dna['court']}.")
    bits.append(f"Working outcome: {dna['outcome']}.")
    return "\n".join(bits) + "\n"


def _inject_noise(rng: random.Random, body: str, matter: dict[str, Any]) -> str:
    extras = [
        f"\n[side note: also pinged on an unrelated {matter['practice_area']} query — ignore for this file]\n",
        "\npls rvw asap — incomplete sentance in the chronology, will fix tmrw.\n",
        "\nFYI wrt the earlier call: TBC / TBD / as discussed.\n",
        f"\nCross-ref (possibly wrong): see also {matter['matter_id'][:-1]}0 internal KM dump.\n",
    ]
    return body + pick(rng, extras)


def _sequence_for(matter: dict[str, Any]) -> list[str]:
    pa = matter["practice_area"]
    mt = matter["matter_type"]
    if pa in {"Arbitration", "Disputes"}:
        return list(DISPUTE_DOC_SEQUENCE)
    if pa in {"M&A", "Corporate"} and mt in {"Share Purchase Agreement", "Due Diligence", "Merger"}:
        return list(TRANSACTION_DOC_SEQUENCE)
    if pa == "Banking & Finance":
        return list(FINANCE_DOC_SEQUENCE)
    return list(GENERIC_DOC_SEQUENCE)


def _plan_types(rng: random.Random, sequence: list[str], n: int, dna: dict[str, Any]) -> list[str]:
    types = sequence[: min(n, len(sequence))]
    while len(types) < n:
        types.append(pick(rng, sequence))
    if dna.get("versioned") and "Share Purchase Agreement" not in types:
        types[min(3, len(types) - 1)] = "Share Purchase Agreement"
    return types


def _author(rng: random.Random, matter: dict[str, Any], members_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    mid = pick(rng, matter["matter_members"])["member_id"]
    return members_by_id[mid]
