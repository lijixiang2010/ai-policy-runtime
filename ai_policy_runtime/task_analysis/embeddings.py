from __future__ import annotations

import hashlib
import math
import os
import re
import unicodedata
from collections import Counter
from typing import Protocol, Sequence


class EmbeddingProvider(Protocol):
    """Vector provider used by semantic task analysis."""

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


class HashingTextEmbeddingProvider:
    """Dependency-free semantic approximation using hashed lexical n-grams.

    This provider is intentionally small and local. It is not a replacement for
    transformer embeddings, but it works well enough for task-intent recall when
    Skill authors provide representative semantic phrases.
    """

    model_name = "hashing-text-ngram-v1"

    def __init__(self, dimensions: int = 512) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.dimensions = dimensions

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        features = _text_features(text)
        if not features:
            return vector
        counts = Counter(features)
        for feature, count in counts.items():
            index = _stable_hash(feature) % self.dimensions
            sign = 1.0 if _stable_hash(f"{feature}:sign") % 2 == 0 else -1.0
            vector[index] += sign * (1.0 + math.log(count))
        return _normalize(vector)


class SentenceTransformerEmbeddingProvider:
    """Embedding provider backed by an explicitly configured local sentence-transformers model."""

    def __init__(self, model_name: str | None = None) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Semantic task analysis requires sentence-transformers. "
                "Install ai-policy-runtime[semantic] to enable this optional feature."
            ) from exc
        self.model_name = model_name or os.environ.get("AI_POLICY_EMBEDDING_MODEL")
        if not self.model_name:
            raise RuntimeError(
                "Semantic task analysis requires an explicit local embedding model. "
                "Set AI_POLICY_EMBEDDING_MODEL or pass model_name."
            )
        try:
            self._model = SentenceTransformer(self.model_name)
        except Exception as exc:
            raise RuntimeError(
                "Semantic task analysis could not load the embedding model "
                f"{self.model_name!r}. Provide a local model directory or a model "
                "that is already available in the sentence-transformers cache."
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


def _text_features(text: str) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []
    compact = normalized.replace(" ", "")
    features: list[str] = []
    features.extend(f"char:{gram}" for gram in _char_ngrams(compact, 2, 4))
    tokens = normalized.split()
    features.extend(f"token:{token}" for token in tokens)
    features.extend(f"word:{gram}" for gram in _word_ngrams(tokens, 2, 3))
    return features


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    return " ".join(re.findall(r"[\w]+|[\u4e00-\u9fff]", normalized, flags=re.UNICODE))


def _char_ngrams(text: str, min_n: int, max_n: int) -> list[str]:
    if not text:
        return []
    grams: list[str] = []
    for size in range(min_n, max_n + 1):
        if len(text) < size:
            continue
        grams.extend(text[index : index + size] for index in range(len(text) - size + 1))
    return grams or [text]


def _word_ngrams(tokens: Sequence[str], min_n: int, max_n: int) -> list[str]:
    grams: list[str] = []
    for size in range(min_n, max_n + 1):
        if len(tokens) < size:
            continue
        grams.extend(" ".join(tokens[index : index + size]) for index in range(len(tokens) - size + 1))
    return grams


def _stable_hash(value: str) -> int:
    return int.from_bytes(hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big")


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [value / norm for value in vector]
