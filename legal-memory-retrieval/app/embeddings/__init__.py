from __future__ import annotations

from typing import Protocol


class Embedder(Protocol):
    dim: int

    def encode(self, texts: list[str]) -> list[list[float]]:
        ...
