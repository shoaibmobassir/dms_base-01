"""Bedrock embedding providers (experimental — not the production retrieval default).

Production corpus vectors are MiniLM 384-d. Switching to Bedrock embeddings
requires a new vector column / dimension + full re-embed before enabling
`EMBEDDING_PROVIDER=bedrock` for retrieval.
"""

from __future__ import annotations

from app.config import settings
from app.llm.bedrock_client import embed_texts


class BedrockEmbedder:
    """Embedder Protocol implementation backed by Amazon Bedrock."""

    def __init__(
        self,
        model: str | None = None,
        *,
        dimensions: int | None = None,
        input_type: str = "search_document",
    ) -> None:
        self.model = (model or settings.bedrock_embedding_model).strip()
        self.input_type = input_type
        if self.model.startswith("amazon.titan-embed"):
            self.dim = int(dimensions or settings.bedrock_embedding_dimensions or 1024)
        elif self.model.startswith("cohere.embed-v4"):
            # Cohere Embed v4 default output size on Bedrock is typically 1536
            # unless truncated via request params; report configured override.
            self.dim = int(dimensions or settings.bedrock_embedding_dimensions or 1536)
        else:
            self.dim = int(dimensions or settings.bedrock_embedding_dimensions or 1024)

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return embed_texts(
            texts,
            model=self.model,
            input_type=self.input_type,
            dimensions=self.dim if self.model.startswith("amazon.titan-embed") else None,
        )
