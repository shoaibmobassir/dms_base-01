"""Extractor protocol — base class for all file extractors."""
from __future__ import annotations

from typing import Protocol


class Extractor(Protocol):
    """Extract text from a file path. Returns (full_text, page_count)."""
    def extract(self, path: str) -> tuple[str, int]:
        ...
