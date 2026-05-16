from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ai_policy_runtime.domain.task import TaskContext


@dataclass(frozen=True)
class ExtractionEvidence:
    """A single reason why an extractor inferred a task fact."""

    field: str
    value: Any
    source: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "source": self.source,
            "confidence": round(self.confidence, 3),
        }


@dataclass(frozen=True)
class TaskSignals:
    """Optional non-text signals that help interpret a user task."""

    file_path: Path | None = None
    project_language: str | None = None
    execution_phase: str | None = None


@dataclass(frozen=True)
class TaskAnalysis:
    """Structured analyzer result with confidence and evidence."""

    task: TaskContext
    confidence: float
    evidence: tuple[ExtractionEvidence, ...] = ()
    needs_review: bool = False
    activation_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": {
                "domain": self.task.domain,
                "task_type": self.task.task_type,
                "capabilities": list(self.task.capabilities),
                "tags": list(self.task.tags),
                "context": dict(self.task.context),
            },
            "confidence": round(self.confidence, 3),
            "needs_review": self.needs_review,
            "activation_ready": self.activation_ready,
            "evidence": [item.to_dict() for item in self.evidence],
        }


class TaskExtractor(Protocol):
    """Protocol for task extractors."""

    def extract(self, text: str, signals: TaskSignals | None = None) -> TaskAnalysis:
        """Extract a TaskAnalysis from natural language and optional signals."""


def is_activation_ready(task: TaskContext) -> bool:
    """Return whether a TaskContext is specific enough for Skill activation."""

    if task.task_type == "unknown":
        return False
    if task.domain != "general":
        return True
    return task.context.get("artifact_type") == "code" or bool(task.context.get("language"))
