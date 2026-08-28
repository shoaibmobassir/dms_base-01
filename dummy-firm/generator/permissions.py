from __future__ import annotations

import random
from typing import Any


def generate_permissions(
    rng: random.Random,
    matters: list[dict[str, Any]],
    dnas: dict[str, dict[str, Any]],
    fraction: float,
) -> list[dict[str, Any]]:
    n = max(1, int(len(matters) * fraction))
    scored = sorted(
        matters,
        key=lambda m: (0 if dnas[m["matter_id"]].get("restricted_bias") else 1, rng.random()),
    )
    restricted = scored[:n]
    rows: list[dict[str, Any]] = []
    for matter in matters:
        team = [mm["member_id"] for mm in matter["matter_members"]]
        is_restricted = matter in restricted or matter["matter_id"] in {m["matter_id"] for m in restricted}
        if is_restricted:
            allowed = team[:2]
            classification = "Restricted Partner Matter"
        else:
            allowed = team
            classification = f"{matter['practice_area']} team"
        rows.append(
            {
                "matter_id": matter["matter_id"],
                "classification": classification,
                "restricted": is_restricted,
                "allowed_members": allowed,
                "practice_area": matter["practice_area"],
            }
        )
    return rows
