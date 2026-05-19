from __future__ import annotations

import json
import math
import os
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
        remote_provider_requested = provider == "openai-compatible"
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

    @classmethod
    def from_values(
        cls,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
    ) -> "OpenAICompatibleEmbeddingConfig | None":
        """Return config for explicit Python Runtime embedding settings."""

        clean_base_url = (base_url or "").strip()
        clean_api_key = (api_key or "").strip()
        if not (clean_base_url or clean_api_key):
            return None
        return cls(
            base_url=clean_base_url or cls.base_url,
            model=(model or cls.model).strip() or cls.model,
            api_key=clean_api_key,
            timeout_seconds=timeout_seconds or cls.timeout_seconds,
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
