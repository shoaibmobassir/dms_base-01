from __future__ import annotations

import random
from typing import Any

from faker import Faker

from generator.util import sample


INDUSTRIES = [
    "Infrastructure",
    "Energy",
    "Manufacturing",
    "Technology",
    "Real Estate",
    "Banking",
    "Pharmaceuticals",
    "Logistics",
    "Retail",
    "Telecom",
    "Mining",
    "Hospitality",
]

CITIES = ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Pune", "Ahmedabad", "Kolkata", "Singapore"]

SUFFIXES = ["Ltd.", "Pvt. Ltd.", "Limited", "Corporation", "Holdings", "Infrastructure Ltd.", "Energy Ltd."]


def generate_clients(
    rng: random.Random,
    fake: Faker,
    members: list[dict[str, Any]],
    n_clients: int,
) -> list[dict[str, Any]]:
    lawyers = [m for m in members if m["is_lawyer"]]
    clients: list[dict[str, Any]] = []
    used_names: set[str] = set()

    for index in range(1, n_clients + 1):
        industry = rng.choice(INDUSTRIES)
        name = _unique_name(rng, fake, used_names)
        hq = rng.choice(CITIES)
        n_subs = rng.randint(0, 3)
        subsidiaries = [_unique_name(rng, fake, used_names) for _ in range(n_subs)]
        preferred = sample(rng, lawyers, k=rng.randint(1, 3))
        clients.append(
            {
                "client_id": f"CLI-{index:05d}",
                "name": name,
                "industry": industry,
                "size": rng.choice(["Mid-market", "Large", "Conglomerate", "Promoter-backed"]),
                "headquarters": hq,
                "locations": list(dict.fromkeys([hq] + sample(rng, CITIES, k=rng.randint(1, 3)))),
                "subsidiaries": subsidiaries,
                "preferred_lawyer_ids": [m["member_id"] for m in preferred],
                "aliases": _aliases(name),
            }
        )
    return clients


def _unique_name(rng: random.Random, fake: Faker, used: set[str]) -> str:
    for _ in range(50):
        stem = fake.company().split()[0].replace(",", "")
        name = f"{stem} {rng.choice(SUFFIXES)}"
        if name not in used:
            used.add(name)
            return name
    name = f"{fake.unique.company()} Ltd."
    used.add(name)
    return name


def _aliases(name: str) -> list[str]:
    short = name.replace("Pvt. Ltd.", "").replace("Ltd.", "").replace("Limited", "").replace("Corporation", "").strip()
    initials = "".join(part[0] for part in short.split() if part[0].isalpha())
    aliases = [name, short, f"{short} Ltd.", f"{short} Infra."]
    if len(initials) >= 2:
        aliases.append(initials.upper())
    return list(dict.fromkeys(aliases))
