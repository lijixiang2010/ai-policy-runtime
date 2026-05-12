from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ai_policy_runtime.domain.task import TaskContext

from .lexicon import LexiconRule, TaskLexicon
from .schema import ExtractionEvidence, TaskAnalysis


GENERAL_DOMAIN = "general"
UNKNOWN_TASK_TYPE = "unknown"
REVIEW_CONFIDENCE_THRESHOLD = 0.72


@dataclass
class ExtractionState:
    """Mutable task-analysis state before final TaskContext construction."""

    context: dict[str, Any] = field(default_factory=dict)
    tags: set[str] = field(default_factory=set)
    skill_matches: set[str] = field(default_factory=set)
    evidence: list[ExtractionEvidence] = field(default_factory=list)

    def add(self, evidence: ExtractionEvidence) -> None:
        """Append evidence without changing context or tags."""

        self.evidence.append(evidence)

    def apply_rule(self, rule: LexiconRule, evidence: ExtractionEvidence) -> None:
        """Apply a rule if stronger evidence for the same field is not present."""

        if self.has_stronger_or_equal(evidence):
            return
        if rule.field == "skill":
            self.skill_matches.add(str(rule.value))
            self.evidence.append(evidence)
            return
        self.context.update(rule.set_context)
        self.tags.update(rule.tags)
        self.evidence.append(evidence)

    def has_stronger_or_equal(self, candidate: ExtractionEvidence) -> bool:
        """Return whether current evidence should suppress a candidate."""

        if candidate.field == "skill":
            return any(
                item.field == candidate.field
                and item.value == candidate.value
                and item.confidence >= candidate.confidence
                for item in self.evidence
            )
        return any(
            item.field == candidate.field and item.confidence >= candidate.confidence
            for item in self.evidence
        )

    def best_value(self, field: str, default: str) -> str:
        """Return the highest-confidence value for a field."""

        matches = [item for item in self.evidence if item.field == field]
        if not matches:
            return default
        return str(max(matches, key=lambda item: item.confidence).value)

    def to_analysis(self, lexicon: TaskLexicon) -> TaskAnalysis:
        """Finalize state into a TaskAnalysis."""

        domain = self.best_value("domain", GENERAL_DOMAIN)
        task_type = self.best_value("task_type", UNKNOWN_TASK_TYPE)
        if domain != GENERAL_DOMAIN:
            self.context.setdefault("language", domain)
            self.tags.add(domain)
        if self.skill_matches:
            self.context["semantic_skill_matches"] = tuple(sorted(self.skill_matches))

        confidence = _confidence(self.evidence, domain, task_type)
        task = TaskContext(
            domain=domain,
            task_type=task_type,
            capabilities=lexicon.capabilities_for(task_type),
            tags=tuple(sorted(self.tags)),
            context=dict(self.context),
        )
        return TaskAnalysis(
            task=task,
            confidence=confidence,
            evidence=tuple(self.evidence),
            needs_review=confidence < REVIEW_CONFIDENCE_THRESHOLD,
        )


def default_task_type_evidence() -> ExtractionEvidence:
    """Evidence used when no task trigger can be inferred."""

    return ExtractionEvidence(
        field="task_type",
        value=UNKNOWN_TASK_TYPE,
        source="default:unknown",
        confidence=0.2,
    )


def signal_domain_evidence(project_language: str) -> ExtractionEvidence:
    """Evidence produced from an explicit project-language signal."""

    return ExtractionEvidence(
        field="domain",
        value=project_language,
        source="signal:project_language",
        confidence=0.7,
    )


def _confidence(
    evidence: Iterable[ExtractionEvidence],
    domain: str,
    task_type: str,
) -> float:
    by_field: dict[str, float] = {}
    for item in evidence:
        by_field[item.field] = max(item.confidence, by_field.get(item.field, 0.0))
    score = 0.2
    score += 0.35 if domain != GENERAL_DOMAIN else 0.0
    score += 0.2 if task_type != UNKNOWN_TASK_TYPE else 0.0
    score += min(sum(by_field.values()) * 0.08, 0.25)
    return min(score, 1.0)
