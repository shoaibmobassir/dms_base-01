from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def scale_for(config: dict[str, Any]) -> dict[str, Any]:
    profile = config["scale"]["profile"]
    return config["scale"][profile]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def random_date(rng: random.Random, start: date, end: date) -> date:
    span = (end - start).days
    return start + timedelta(days=rng.randint(0, max(span, 1)))


def inr_crore(rng: random.Random, low: float, high: float) -> str:
    value = round(rng.uniform(low, high), 1)
    return f"₹{value} crore"


def pick(rng: random.Random, items: list[Any]) -> Any:
    return items[rng.randint(0, len(items) - 1)]


def sample(rng: random.Random, items: list[Any], k: int) -> list[Any]:
    k = min(k, len(items))
    chosen = list(items)
    rng.shuffle(chosen)
    return chosen[:k]
