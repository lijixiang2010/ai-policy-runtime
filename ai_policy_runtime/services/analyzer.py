from __future__ import annotations

from ai_policy_runtime.domain.task import TaskContext
from ai_policy_runtime.task_analysis import TaskAnalysis, TaskAnalyzer, TaskSignals


_DEFAULT_ANALYZER = TaskAnalyzer()


def analyze(text: str, signals: TaskSignals | None = None) -> TaskAnalysis:
    """Return the full task analysis result."""

    return _DEFAULT_ANALYZER.analyze(text, signals)


def analyze_task(text: str, signals: TaskSignals | None = None) -> TaskContext:
    """Compatibility wrapper returning only the structured task context."""

    return analyze(text, signals).task
