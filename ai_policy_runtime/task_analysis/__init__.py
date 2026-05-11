from __future__ import annotations

from .analyzer import TaskAnalyzer, build_extractor
from .deterministic_extractor import DeterministicTaskExtractor
from .embeddings import (
    EmbeddingProvider,
    HashingTextEmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
)
from .lexicon import LexiconRule, TaskLexicon, TriggerProfile
from .schema import ExtractionEvidence, TaskAnalysis, TaskSignals

__all__ = [
    "DeterministicTaskExtractor",
    "EmbeddingProvider",
    "ExtractionEvidence",
    "HashingTextEmbeddingProvider",
    "LexiconRule",
    "SentenceTransformerEmbeddingProvider",
    "TaskAnalysis",
    "TaskAnalyzer",
    "TaskLexicon",
    "TaskSignals",
    "TriggerProfile",
    "build_extractor",
]
