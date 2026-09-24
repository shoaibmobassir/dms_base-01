"""Embedder factory — keeps MiniLM as the production default.

Set EMBEDDING_PROVIDER=bedrock only after schema + re-embed for the new dim.
"""

from __future__ import annotations

from typing import Union

from app.config import settings
from app.embeddings.bedrock import BedrockEmbedder
from app.embeddings.minilm import MiniLMEmbedder

EmbedderImpl = Union[MiniLMEmbedder, BedrockEmbedder]

_embedder: EmbedderImpl | None = None


def get_embedder() -> EmbedderImpl:
    """Return the configured embedder (singleton)."""
    global _embedder
    if _embedder is not None:
        return _embedder
    name = (settings.embedding_provider or "minilm").strip().lower()
    if name == "bedrock":
        _embedder = BedrockEmbedder()
    else:
        _embedder = MiniLMEmbedder()
    return _embedder


def reset_embedder() -> None:
    """Clear singleton (tests / provider switch)."""
    global _embedder
    _embedder = None
