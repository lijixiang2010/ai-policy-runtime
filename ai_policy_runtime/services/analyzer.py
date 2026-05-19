from __future__ import annotations

from ai_policy_runtime.task_analysis import TaskAnalysis, TaskAnalyzer, TaskSignals


_DEFAULT_ANALYZER: TaskAnalyzer | None = None


def analyze(text: str, signals: TaskSignals | None = None) -> TaskAnalysis:
    """Return the full task analysis result."""

    return _default_analyzer().analyze(text, signals)


def _default_analyzer() -> TaskAnalyzer:
    global _DEFAULT_ANALYZER
    if _DEFAULT_ANALYZER is None:
        _DEFAULT_ANALYZER = TaskAnalyzer()
    return _DEFAULT_ANALYZER
