from __future__ import annotations

from .lexicon import TaskLexicon
from .matching import ExactRuleMatcher, normalize_text
from .resolution import (
    ExtractionState,
    default_task_type_evidence,
    signal_domain_evidence,
)
from .schema import TaskAnalysis, TaskSignals
from .semantic_index import SemanticTaskIndex


class DeterministicTaskExtractor:
    """Extract task context using only data loaded from Skills and signals."""

    def __init__(
        self,
        lexicon: TaskLexicon | None = None,
        semantic_index: SemanticTaskIndex | None = None,
    ) -> None:
        self._lexicon = lexicon or TaskLexicon.from_skills_dir("skills")
        self._semantic_index = semantic_index
        self._matcher = ExactRuleMatcher()

    def extract(self, text: str, signals: TaskSignals | None = None) -> TaskAnalysis:
        normalized = normalize_text(text)
        state = ExtractionState()
        self._apply_domain(normalized, signals, state)
        self._apply_task_type(normalized, state)
        self._apply_exact_context(normalized, state)
        self._apply_semantic_context(normalized, state)
        return state.to_analysis(self._lexicon)

    def _apply_domain(
        self,
        text: str,
        signals: TaskSignals | None,
        state: ExtractionState,
    ) -> None:
        match = self._matcher.best(self._lexicon.domain_rules, text)
        if match is not None:
            state.add(match)
            return
        if signals and signals.project_language:
            state.add(signal_domain_evidence(signals.project_language))

    def _apply_task_type(
        self,
        text: str,
        state: ExtractionState,
    ) -> None:
        state.add(
            self._matcher.best(self._lexicon.trigger_rules, text)
            or default_task_type_evidence()
        )

    def _apply_exact_context(
        self,
        text: str,
        state: ExtractionState,
    ) -> None:
        for rule, evidence in self._matcher.all(self._lexicon.context_rules, text):
            state.apply_rule(rule, evidence)

    def _apply_semantic_context(
        self,
        text: str,
        state: ExtractionState,
    ) -> None:
        if self._semantic_index is None:
            return
        for match in self._semantic_index.search(text):
            state.apply_rule(match.rule, match.evidence())
