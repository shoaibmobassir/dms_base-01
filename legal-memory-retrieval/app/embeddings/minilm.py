from __future__ import annotations

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class MiniLMEmbedder:
    dim = 384

    def __init__(self) -> None:
        self._model = SentenceTransformer(MODEL_NAME)

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        matrix = np.asarray(vectors, dtype=np.float32)
        return [row.tolist() for row in matrix]
