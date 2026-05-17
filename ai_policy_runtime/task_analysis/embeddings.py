from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EmbeddingProvider(Protocol):
    """Vector provider used by semantic task analysis."""

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""


@dataclass(frozen=True)
class OpenAICompatibleEmbeddingConfig:
    """Configuration for an OpenAI-compatible embeddings endpoint."""

    base_url: str = "https://api.openai.com/v1"
    model: str = "text-embedding-3-small"
    api_key: str = ""
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "OpenAICompatibleEmbeddingConfig | None":
        """Return config when the environment requests remote embeddings."""

        provider = (
            os.environ.get("AI_POLICY_EMBEDDING_PROVIDER", "")
            .strip()
            .lower()
            .replace("_", "-")
        )
        base_url = os.environ.get("AI_POLICY_EMBEDDING_BASE_URL", "").strip()
        api_key = (
            os.environ.get("AI_POLICY_EMBEDDING_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        ).strip()
        remote_provider_requested = provider in {
            "openai",
            "openai-compatible",
            "opaicompat",
        }
        if not remote_provider_requested and not (base_url or api_key):
            return None
        if remote_provider_requested and not (base_url or api_key):
            return None
        return cls(
            base_url=base_url or cls.base_url,
            model=os.environ.get("AI_POLICY_EMBEDDING_MODEL", cls.model).strip() or cls.model,
            api_key=api_key,
            timeout_seconds=_float_env("AI_POLICY_EMBEDDING_TIMEOUT", cls.timeout_seconds),
        )


class OpenAICompatibleEmbeddingProvider:
    """Embedding provider backed by an OpenAI-compatible /v1/embeddings API."""

    def __init__(self, config: OpenAICompatibleEmbeddingConfig) -> None:
        self.config = config
        self.model_name = f"openai-compatible:{config.base_url}:{config.model}"

    @classmethod
    def from_env(cls) -> "OpenAICompatibleEmbeddingProvider | None":
        """Create a provider from environment variables when configured."""

        config = OpenAICompatibleEmbeddingConfig.from_env()
        return cls(config) if config else None

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        payload = {
            "model": self.config.model,
            "input": list(texts),
        }
        request = Request(
            _embeddings_url(self.config.base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise RuntimeError(
                f"Embedding endpoint returned HTTP {exc.code}: {body}"
            ) from exc
        except (OSError, URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Embedding endpoint request failed: {exc}") from exc

        return _extract_openai_embeddings(data, expected_count=len(texts))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers


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


def _embeddings_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/embeddings") else f"{base}/embeddings"


def _extract_openai_embeddings(data: object, *, expected_count: int) -> list[list[float]]:
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise RuntimeError("Embedding endpoint response must contain a data list.")

    items = sorted(
        data["data"],
        key=lambda item: item.get("index", 0) if isinstance(item, dict) else 0,
    )
    vectors = [_embedding_from_item(item) for item in items]
    if len(vectors) != expected_count:
        raise RuntimeError(
            "Embedding endpoint returned "
            f"{len(vectors)} vectors for {expected_count} inputs."
        )
    return vectors


def _embedding_from_item(item: object) -> list[float]:
    if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
        raise RuntimeError("Embedding endpoint response item is missing embedding.")
    try:
        return [float(value) for value in item["embedding"]]
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Embedding vector contains a non-numeric value.") from exc


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default
