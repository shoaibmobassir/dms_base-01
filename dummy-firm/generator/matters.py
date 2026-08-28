from __future__ import annotations

import random
from datetime import date
from typing import Any

from generator.themes import opposing_name_bank, theme_for_matter_type
from generator.util import pick, random_date, sample


PRACTICE_CODES = {
    "Corporate": "COR",
    "M&A": "MNA",
    "Banking & Finance": "BNK",
    "Disputes": "DIS",
    "Arbitration": "ARB",
    "Insolvency": "INS",
    "Employment": "EMP",
    "Real Estate": "REL",
    "Tax": "TAX",
    "Regulatory": "REG",
}

OFFICE_CODES = {"Delhi": "DEL", "Mumbai": "MUM", "Bengaluru": "BLR", "Singapore": "SGP"}


def generate_matters(
    rng: random.Random,
    members: list[dict[str, Any]],
    clients: list[dict[str, Any]],
    config: dict[str, Any],
    n_matters: int,
) -> list[dict[str, Any]]:
    matter_types = config["matter_types"]
    lawyers = [m for m in members if m["is_lawyer"]]
    support = [m for m in members if not m["is_lawyer"]]
    opposing = opposing_name_bank()

    # Power-law-ish: some clients get many matters (repeat work).
    weights = [max(1, int(1 + (len(clients) - i) / 4)) for i in range(len(clients))]

    matters: list[dict[str, Any]] = []
    for index in range(1, n_matters + 1):
        client = rng.choices(clients, weights=weights, k=1)[0]
        practice_area, matter_type = _choose_type(rng, matter_types, client)
        lead = _preferred_or_matching(rng, lawyers, client, practice_area)
        office = lead["office"]
        opened = random_date(rng, date(2017, 1, 1), date(2025, 6, 1))
        status = rng.choices(["Open", "Closed", "Stayed"], weights=[0.35, 0.55, 0.1], k=1)[0]
        closed = None
        if status == "Closed":
            closed = random_date(rng, opened, date(2026, 8, 1)).isoformat()

        associate = _matching(rng, lawyers, practice_area, exclude={lead["member_id"]})
        junior = _matching(rng, lawyers, practice_area, exclude={lead["member_id"], associate["member_id"]})
        clerk = pick(rng, support) if support else None

        matter_members = [
            {"member_id": lead["member_id"], "role_on_matter": "Partner" if lead["role"] == "Partner" else "Lead"},
            {"member_id": associate["member_id"], "role_on_matter": "Associate"},
            {"member_id": junior["member_id"], "role_on_matter": "Junior"},
        ]
        if clerk:
            matter_members.append({"member_id": clerk["member_id"], "role_on_matter": clerk["role"]})

        year = opened.year
        seq = index
        code = f"{PRACTICE_CODES[practice_area]}/{OFFICE_CODES.get(office, 'DEL')}/{seq:04d}/{year}"
        counterpart = pick(rng, opposing)
        title = _title(client["name"], counterpart, matter_type)
        theme_key = theme_for_matter_type(practice_area, matter_type)

        matters.append(
            {
                "matter_id": f"MTR-{year}-{seq:05d}",
                "matter_code": code,
                "title": title,
                "client_id": client["client_id"],
                "client_name": client["name"],
                "opposing_party": counterpart,
                "practice_area": practice_area,
                "matter_type": matter_type,
                "theme_key": theme_key,
                "jurisdiction": "Singapore" if office == "Singapore" else "India",
                "court": None,  # filled from DNA
                "opened_date": opened.isoformat(),
                "closed_date": closed,
                "status": status,
                "office": office,
                "matter_members": matter_members,
            }
        )
    return matters


def _choose_type(rng: random.Random, matter_types: dict[str, list[str]], client: dict[str, Any]) -> tuple[str, str]:
    industry_bias = {
        "Infrastructure": ["Arbitration", "Disputes", "Real Estate"],
        "Energy": ["Arbitration", "Regulatory", "Banking & Finance"],
        "Banking": ["Banking & Finance", "Insolvency", "Disputes"],
        "Technology": ["M&A", "Employment", "Corporate"],
        "Real Estate": ["Real Estate", "Disputes", "Corporate"],
        "Pharmaceuticals": ["Regulatory", "M&A", "Tax"],
    }
    preferred = industry_bias.get(client["industry"])
    if preferred and rng.random() < 0.65:
        practice = pick(rng, [p for p in preferred if p in matter_types])
    else:
        practice = pick(rng, list(matter_types.keys()))
    return practice, pick(rng, matter_types[practice])


def _preferred_or_matching(
    rng: random.Random,
    lawyers: list[dict[str, Any]],
    client: dict[str, Any],
    practice_area: str,
) -> dict[str, Any]:
    preferred = [m for m in lawyers if m["member_id"] in client["preferred_lawyer_ids"]]
    if preferred and rng.random() < 0.5:
        return pick(rng, preferred)
    return _matching(rng, lawyers, practice_area, exclude=set())


def _matching(
    rng: random.Random,
    lawyers: list[dict[str, Any]],
    practice_area: str,
    exclude: set[str],
) -> dict[str, Any]:
    pool = [m for m in lawyers if m["member_id"] not in exclude and practice_area in m["practice_areas"]]
    if not pool:
        pool = [m for m in lawyers if m["member_id"] not in exclude]
    if not pool:
        pool = lawyers
    return pick(rng, pool)


def _title(client: str, opposing: str, matter_type: str) -> str:
    if "Agreement" in matter_type or matter_type in {
        "Due Diligence",
        "Merger",
        "Joint Venture",
        "Corporate Restructuring",
        "Title Diligence",
        "Development Agreement",
        "CIRP",
        "Liquidation",
        "SEBI Investigation",
        "Competition Commission",
        "Sectoral Licensing",
        "POSH Investigation",
        "Transfer Pricing",
        "GST Dispute",
        "Assessment Appeal",
    }:
        return f"{client} — {matter_type}"
    return f"{client} v {opposing}"
