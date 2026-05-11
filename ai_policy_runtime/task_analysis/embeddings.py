from __future__ import annotations

import math
import os
from typing import Protocol, Sequence


class EmbeddingProvider(Protocol):
    """Vector provider used by semantic task analysis."""

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


class SentenceTransformerEmbeddingProvider:
    """Embedding provider backed by sentence-transformers."""

    DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, model_name: str | None = None) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Semantic task analysis requires sentence-transformers. "
                "Install project dependencies from requirements.txt."
            ) from exc
        self.model_name = model_name or os.environ.get(
            "AI_POLICY_EMBEDDING_MODEL", self.DEFAULT_MODEL
        )
        try:
            self._model = SentenceTransformer(self.model_name)
        except Exception as exc:
            raise RuntimeError(
                "Semantic task analysis could not load the embedding model "
                f"{self.model_name!r}. Download it first or set "
                "AI_POLICY_EMBEDDING_MODEL to a local model directory."
            ) from exc

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [vector.astype(float).tolist() for vector in vectors]


class NullEmbeddingProvider:
    """Provider used when semantic matching is intentionally disabled."""

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return []


def provider_cache_key(provider: EmbeddingProvider) -> str:
    """Return a stable cache key for an embedding provider."""

    return str(getattr(provider, "model_name", provider.__class__.__name__))


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Return cosine similarity for two vectors."""

    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)
