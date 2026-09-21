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
        from app.cache.multi_tier import embedding_cache_get, embedding_cache_set

        out: list[list[float] | None] = [None] * len(texts)
        missing_idx: list[int] = []
        missing_texts: list[str] = []
        for i, text in enumerate(texts):
            cached = embedding_cache_get(text)
            if cached is not None:
                out[i] = cached
            else:
                missing_idx.append(i)
                missing_texts.append(text)
        if missing_texts:
            vectors = self._model.encode(
                missing_texts,
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
            matrix = np.asarray(vectors, dtype=np.float32)
            for idx, row in zip(missing_idx, matrix):
                vec = row.tolist()
                embedding_cache_set(texts[idx], vec)
                out[idx] = vec
        return [row or [] for row in out]
