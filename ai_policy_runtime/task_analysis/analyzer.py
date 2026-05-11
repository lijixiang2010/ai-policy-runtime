from __future__ import annotations

from pathlib import Path

from .deterministic_extractor import DeterministicTaskExtractor
from .embeddings import EmbeddingProvider, SentenceTransformerEmbeddingProvider
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
        self._deterministic = deterministic or DeterministicTaskExtractor()

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
    provider = embeddings or SentenceTransformerEmbeddingProvider()
    return DeterministicTaskExtractor(
        lexicon,
        SemanticTaskIndex(lexicon, provider, cache_dir=cache_dir),
    )
