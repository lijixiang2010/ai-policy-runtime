from __future__ import annotations

import re
from typing import Iterable

from .lexicon import LexiconRule
from .schema import ExtractionEvidence


class ExactRuleMatcher:
    """Match normalized user text against exact phrases declared by Skills."""

    def best(self, rules: Iterable[LexiconRule], text: str) -> ExtractionEvidence | None:
        """Return the highest-confidence exact match for a rule group."""

        best_match = max(
            self.all(rules, text),
            key=lambda item: item[1].confidence,
            default=None,
        )
        return best_match[1] if best_match else None

    def all(
        self,
        rules: Iterable[LexiconRule],
        text: str,
    ) -> tuple[tuple[LexiconRule, ExtractionEvidence], ...]:
        """Return every exact rule match."""

        return tuple(
            (rule, evidence)
            for rule in rules
            if (evidence := self.match(rule, text)) is not None
        )

    def match(self, rule: LexiconRule, text: str) -> ExtractionEvidence | None:
        """Return evidence when any rule phrase appears in the normalized text."""

        matched = next((phrase for phrase in rule.phrases if _contains_phrase(text, phrase)), None)
        if matched is None:
            return None
        return ExtractionEvidence(
            field=rule.field,
            value=rule.value,
            source=f"{rule.source}:{matched}",
            confidence=rule.confidence,
        )


def normalize_text(text: str) -> str:
    """Normalize input text for deterministic matching."""

    return " ".join(text.lower().strip().split())


def _contains_phrase(text: str, phrase: str) -> bool:
    """Return whether a phrase appears without matching inside English words."""

    if not phrase:
        return False
    if not _requires_word_boundary(phrase):
        return phrase in text
    return re.search(rf"(?<![a-z0-9_]){re.escape(phrase)}(?![a-z0-9_])", text) is not None


def _requires_word_boundary(phrase: str) -> bool:
    return re.fullmatch(r"[a-z0-9_]+(?: [a-z0-9_]+)*", phrase) is not None
