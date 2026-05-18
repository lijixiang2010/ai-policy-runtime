from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .embeddings import EmbeddingProvider, cosine_similarity, provider_cache_key
from .lexicon import LexiconRule, TaskLexicon
from .schema import ExtractionEvidence


@dataclass(frozen=True)
class SemanticMatch:
    """A semantic match between the user task and a lexicon rule."""

    rule: LexiconRule
    score: float
    text: str

    def evidence(self) -> ExtractionEvidence:
        return ExtractionEvidence(
            field=self.rule.field,
            value=self.rule.value,
            source=f"{self.rule.source}:semantic:{self.text}",
            confidence=min(self.rule.confidence, self.score),
        )


class SemanticTaskIndex:
    """Embedding index over task-analysis rules declared by Skills."""

    def __init__(
        self,
        lexicon: TaskLexicon,
        provider: EmbeddingProvider,
        *,
        threshold: float = 0.38,
        cache_dir: str | Path | None = None,
    ) -> None:
        self._provider = provider
        self._threshold = threshold
        self._entries = tuple(_iter_entries(lexicon))
        self._vectors = self._load_or_encode(cache_dir)

    def search(self, text: str, *, limit: int = 32) -> tuple[SemanticMatch, ...]:
        return self.search_scoped(text, scope=None, limit=limit)

    def search_scoped(
        self,
        text: str,
        *,
        scope: frozenset[str] | None,
        limit: int = 32,
    ) -> tuple[SemanticMatch, ...]:
        """Search semantic entries, optionally constrained to candidate skills."""

        if not self._entries or not self._vectors:
            return ()
        query_vectors = self._provider.encode([text])
        if not query_vectors:
            return ()
        query = query_vectors[0]
        matches = [
            SemanticMatch(
                rule=rule,
                score=cosine_similarity(query, vector),
                text=entry_text,
            )
            for (rule, entry_text), vector in zip(self._entries, self._vectors)
            if scope is None or rule.skill_id in scope
        ]
        selected = [item for item in matches if self._passes_threshold(item)]
        selected.sort(
            key=lambda item: (_field_priority(item.rule.field), item.score),
            reverse=True,
        )
        return tuple(_best_per_field(selected))[:limit]

    def _passes_threshold(self, match: SemanticMatch) -> bool:
        if match.score < self._threshold:
            return False
        if (
            match.rule.field.startswith("context.")
            and match.rule.skill_id.startswith("cmake.")
            and match.score < 0.5
        ):
            return False
        return True

    def _load_or_encode(self, cache_dir: str | Path | None) -> list[list[float]]:
        texts = [entry[1] for entry in self._entries]
        if not texts:
            return []
        if cache_dir is None:
            return self._provider.encode(texts)

        cache = SemanticIndexCache(cache_dir)
        key = cache.key(provider_cache_key(self._provider), texts)
        vectors = cache.read(key)
        if vectors is not None:
            return vectors
        vectors = self._provider.encode(texts)
        cache.write(key, vectors)
        return vectors


class SemanticIndexCache:
    """File-backed cache for semantic index vectors."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def key(self, model: str, texts: Sequence[str]) -> str:
        payload = json.dumps({"model": model, "texts": list(texts)}, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def read(self, key: str) -> list[list[float]] | None:
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        vectors = data.get("vectors")
        if not isinstance(vectors, list):
            return None
        return vectors

    def write(self, key: str, vectors: list[list[float]]) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{key}.json"
        path.write_text(json.dumps({"vectors": vectors}), encoding="utf-8")
        return path


def _iter_entries(lexicon: TaskLexicon) -> Iterable[tuple[LexiconRule, str]]:
    for rule in (
        *lexicon.skill_rules,
        *lexicon.domain_rules,
        *lexicon.trigger_rules,
        *lexicon.context_rules,
    ):
        texts = (
            rule.semantic_texts
            if rule.field.startswith("context.")
            else rule.semantic_texts or rule.phrases
        )
        for text in texts:
            yield rule, text


def _best_per_field(matches: Sequence[SemanticMatch]) -> Iterable[SemanticMatch]:
    seen: set[tuple[str, str]] = set()
    for match in matches:
        key = _dedupe_key(match.rule)
        if key in seen:
            continue
        seen.add(key)
        yield match


def _dedupe_key(rule: LexiconRule) -> tuple[str, str]:
    if rule.field.startswith("context."):
        return (rule.field, rule.skill_id)
    return (rule.field, str(rule.value))


def _field_priority(field: str) -> int:
    if field.startswith("context."):
        return 4
    if field in {"domain", "task_type"}:
        return 3
    if field == "skill":
        return 2
    return 1
