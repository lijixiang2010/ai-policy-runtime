from __future__ import annotations

import os
from pathlib import Path

from .deterministic_extractor import DeterministicTaskExtractor
from .embeddings import (
    EmbeddingProvider,
    HashingTextEmbeddingProvider,
    NullEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
)
from .lexicon import TaskLexicon
from .schema import TaskAnalysis, TaskSignals
from .semantic_index import SemanticTaskIndex


class TaskAnalyzer:
    """Task analyzer using exact facts plus embedding semantic recall."""

    def __init__(
        self,
        *,
        deterministic: DeterministicTaskExtractor | None = None,
    ) -> None:
        self._deterministic = deterministic or build_extractor("skills")

    @classmethod
    def from_skills_dir(
        cls,
        path: str | Path,
        *,
        embeddings: EmbeddingProvider | None = None,
        semantic: bool = True,
        cache_dir: str | Path | None = None,
    ) -> "TaskAnalyzer":
        """Build an analyzer whose deterministic rules come from Skill metadata."""

        return cls(
            deterministic=build_extractor(
                path,
                embeddings,
                semantic=semantic,
                cache_dir=cache_dir,
            )
        )

    def analyze(self, text: str, signals: TaskSignals | None = None) -> TaskAnalysis:
        """Analyze user input into a structured task context."""

        return self._deterministic.extract(text, signals)


def build_extractor(
    skills_dir: str | Path,
    embeddings: EmbeddingProvider | None = None,
    *,
    semantic: bool = True,
    cache_dir: str | Path | None = None,
) -> DeterministicTaskExtractor:
    """Create the default task extractor with sensible runtime defaults."""

    lexicon = TaskLexicon.from_skills_dir(skills_dir)
    if not semantic:
        return DeterministicTaskExtractor(lexicon)
    provider = embeddings or _default_embedding_provider()
    return DeterministicTaskExtractor(
        lexicon,
        SemanticTaskIndex(lexicon, provider, cache_dir=cache_dir),
    )


def _default_embedding_provider() -> EmbeddingProvider:
    """Return the best configured embedding provider.

    Selection order keeps the product lightweight by default while preserving
    offline options:

    1. OpenAI-compatible /v1/embeddings when configured.
    2. Explicit provider choices from AI_POLICY_EMBEDDING_PROVIDER.
    3. Local bundled sentence-transformers model when available.
    4. Dependency-free hashing fallback.
    """

    provider = _configured_provider_name()
    if provider in {"disabled", "none", "null"}:
        return NullEmbeddingProvider()
    if provider in {"hashing", "lightweight"}:
        return HashingTextEmbeddingProvider()
    if provider in {"openai", "openai-compatible"}:
        remote = OpenAICompatibleEmbeddingProvider.from_env()
        if remote is None:
            raise RuntimeError(
                "AI_POLICY_EMBEDDING_PROVIDER requests openai-compatible, "
                "but no endpoint configuration was found."
            )
        return remote
    if remote := OpenAICompatibleEmbeddingProvider.from_env():
        return remote

    local_model = Path("models") / "paraphrase-multilingual-MiniLM-L12-v2"
    if provider in {"local", "sentence-transformers"}:
        model_name = str(local_model) if local_model.exists() else None
        return SentenceTransformerEmbeddingProvider(model_name)
    if local_model.exists():
        try:
            return SentenceTransformerEmbeddingProvider(str(local_model))
        except RuntimeError:
            pass
    return HashingTextEmbeddingProvider()


def optional_sentence_transformer_provider() -> EmbeddingProvider | None:
    """Return a configured transformer provider, or None when unavailable."""

    try:
        return SentenceTransformerEmbeddingProvider()
    except RuntimeError:
        return None


def _configured_provider_name() -> str:
    return (
        os.environ.get("AI_POLICY_EMBEDDING_PROVIDER", "")
        .strip()
        .lower()
        .replace("_", "-")
    )
