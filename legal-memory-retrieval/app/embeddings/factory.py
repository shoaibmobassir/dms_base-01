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
_minilm: MiniLMEmbedder | None = None


def get_minilm() -> MiniLMEmbedder:
    """The one MiniLM instance in the process.

    ``chunks.embedding`` is MiniLM 384-d, so every query against it (retrieval, Ask the
    Firm passages, batch-review screening) must use this model. Sharing one instance also
    means the startup warm-up covers all of them; two copies cost a second ~7 s load on
    the first batch review.
    """
    global _minilm
    if _minilm is None:
        _minilm = MiniLMEmbedder()
    return _minilm


def get_embedder() -> EmbedderImpl:
    """Return the configured embedder (singleton)."""
    global _embedder
    if _embedder is not None:
        return _embedder
    name = (settings.embedding_provider or "minilm").strip().lower()
    if name == "bedrock":
        _embedder = BedrockEmbedder()
    else:
        _embedder = get_minilm()
    return _embedder


def reset_embedder() -> None:
    """Clear singleton (tests / provider switch)."""
    global _embedder
    _embedder = None
