from __future__ import annotations

from collections import defaultdict
from typing import Any


def generate_relationships(
    matters: list[dict[str, Any]],
    dnas: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rels: list[dict[str, Any]] = []
    by_client: dict[str, list[str]] = defaultdict(list)
    by_theme: dict[str, list[str]] = defaultdict(list)
    by_practice: dict[str, list[str]] = defaultdict(list)
    by_partner: dict[str, list[str]] = defaultdict(list)
    by_opposing: dict[str, list[str]] = defaultdict(list)

    for matter in matters:
        mid = matter["matter_id"]
        by_client[matter["client_id"]].append(mid)
        by_theme[matter["theme_key"]].append(mid)
        by_practice[matter["practice_area"]].append(mid)
        by_opposing[matter["opposing_party"]].append(mid)
        lead = matter["matter_members"][0]["member_id"]
        by_partner[lead].append(mid)

    def emit(src: str, rel: str, dst: str) -> None:
        if src != dst:
            rels.append({"source": src, "type": rel, "target": dst})

    for ids in by_client.values():
        for i, src in enumerate(ids):
            for dst in ids[i + 1 :]:
                emit(src, "same_client", dst)
                emit(src, "follow_up_to" if src < dst else "related_to", dst)

    for ids in by_theme.values():
        for i, src in enumerate(ids):
            for dst in ids[i + 1 : i + 4]:
                emit(src, "similar_facts", dst)
                emit(src, "same_legal_issue", dst)

    for ids in by_practice.values():
        for i, src in enumerate(ids):
            for dst in ids[i + 1 : i + 2]:
                emit(src, "same_practice_area", dst)

    for ids in by_opposing.values():
        if len(ids) > 1:
            emit(ids[0], "same_opposing_party", ids[1])

    # precedent: closed earlier matter of same theme
    closed = [m for m in matters if m["status"] == "Closed"]
    open_or_later = [m for m in matters if m["status"] != "Closed"]
    used = 0
    for later in open_or_later:
        for earlier in closed:
            if earlier["theme_key"] == later["theme_key"] and earlier["opened_date"] < later["opened_date"]:
                emit(earlier["matter_id"], "precedent_for", later["matter_id"])
                used += 1
                break
        if used > 40:
            break

    # related_transaction / related_dispute
    for matter in matters:
        if matter["practice_area"] in {"M&A", "Corporate", "Banking & Finance"}:
            for other in matters:
                if (
                    other["client_id"] == matter["client_id"]
                    and other["practice_area"] in {"Disputes", "Arbitration"}
                ):
                    emit(matter["matter_id"], "related_dispute", other["matter_id"])
                    emit(other["matter_id"], "related_transaction", matter["matter_id"])
                    break

    # de-duplicate
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for rel in rels:
        key = (rel["source"], rel["type"], rel["target"])
        if key not in seen:
            seen.add(key)
            unique.append(rel)
    return unique
