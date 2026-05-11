from __future__ import annotations

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

        matched = next((phrase for phrase in rule.phrases if phrase in text), None)
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
