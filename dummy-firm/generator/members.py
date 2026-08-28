from __future__ import annotations

import random
from typing import Any

from faker import Faker

from generator.util import sample


OFFICES = ["Delhi", "Mumbai", "Bengaluru", "Singapore"]

SPECIALISATIONS = {
    "Corporate": ["Shareholder Disputes", "Joint Ventures", "Corporate Governance", "Restructuring"],
    "M&A": ["Share Purchase Agreements", "Private Equity Exits", "Cross-border M&A", "Due Diligence"],
    "Banking & Finance": ["Acquisition Finance", "Security Enforcement", "Debt Restructuring", "NBFC Lending"],
    "Disputes": ["Commercial Litigation", "Infrastructure Disputes", "Contract Disputes", "Shareholder Disputes"],
    "Arbitration": ["Construction Arbitration", "Commercial Arbitration", "Investment Arbitration", "SIAC Seats"],
    "Insolvency": ["CIRP Strategy", "Resolution Plans", "Personal Guarantees", "NCLT Practice"],
    "Employment": ["Wrongful Termination", "Restrictive Covenants", "POSH", "Senior Exits"],
    "Real Estate": ["Title Diligence", "Joint Development", "Lease Disputes", "RERA"],
    "Tax": ["Transfer Pricing", "GST Litigation", "International Tax", "Assessment Appeals"],
    "Regulatory": ["SEBI Investigations", "Competition Law", "Sectoral Licensing", "FDI Policy"],
}


def generate_members(
    rng: random.Random,
    fake: Faker,
    practice_areas: list[str],
    n_lawyers: int,
    n_support: int,
) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    lawyer_roles = _role_mix(n_lawyers)
    support_roles = _support_mix(n_support)

    for index, role in enumerate(lawyer_roles + support_roles, start=1):
        # Round-robin first so every practice area exists among lawyers.
        if index <= len(practice_areas) and role not in {"Knowledge Manager", "Clerk", "Stenographer", "Paralegal"}:
            areas = [practice_areas[(index - 1) % len(practice_areas)]]
            extra = sample(rng, [a for a in practice_areas if a != areas[0]], k=1)
            areas = areas + extra
        else:
            areas = sample(rng, practice_areas, k=rng.randint(1, 2))
        specs: list[str] = []
        for area in areas:
            specs.extend(sample(rng, SPECIALISATIONS[area], k=rng.randint(1, 2)))
        specs = list(dict.fromkeys(specs))
        members.append(
            {
                "member_id": f"MEM-{index:05d}",
                "name": fake.name(),
                "role": role,
                "practice_areas": areas,
                "specializations": specs,
                "office": rng.choice(OFFICES),
                "joined_year": rng.randint(2004, 2023),
                "email": None,
                "is_lawyer": role in {
                    "Partner",
                    "Counsel",
                    "Senior Associate",
                    "Associate",
                    "Junior",
                    "KM Lawyer",
                },
            }
        )

    for member in members:
        slug = member["name"].lower().replace(" ", ".")
        member["email"] = f"{slug}@apexchambers.com"
    return members


def _role_mix(n: int) -> list[str]:
    sequence = (
        ["Partner"] * max(2, n // 5)
        + ["Counsel"] * max(1, n // 10)
        + ["Senior Associate"] * max(2, n // 5)
        + ["Associate"] * max(3, n // 3)
        + ["Junior"] * max(2, n // 6)
        + ["KM Lawyer"] * max(1, n // 12)
    )
    if len(sequence) < n:
        sequence += ["Associate"] * (n - len(sequence))
    return sequence[:n]


def _support_mix(n: int) -> list[str]:
    sequence = ["Knowledge Manager", "Clerk", "Stenographer", "Paralegal"] * ((n // 4) + 1)
    return sequence[:n]
