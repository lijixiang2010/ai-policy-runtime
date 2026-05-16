from __future__ import annotations

from .lexicon import TaskGate, TaskLexicon
from .matching import ExactRuleMatcher, normalize_text
from .resolution import (
    ExtractionState,
    GENERAL_DOMAIN,
    UNKNOWN_TASK_TYPE,
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
        if _is_obviously_not_engineering_work(normalized):
            return state.to_analysis(self._lexicon)
        self._apply_domain(normalized, signals, state)
        self._apply_task_type(normalized, state)
        if not _has_engineering_entrypoint(normalized, state):
            return state.to_analysis(self._lexicon)
        self._apply_exact_context(normalized, state)
        self._apply_semantic_context(normalized, state, self._semantic_gate(state))
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
        gate: TaskGate,
    ) -> None:
        if self._semantic_index is None:
            return
        scope = self._lexicon.semantic_scope(gate)
        if not scope:
            return
        for match in self._semantic_index.search_scoped(text, scope=scope):
            state.apply_rule(match.rule, match.evidence())

    def _semantic_gate(self, state: ExtractionState) -> TaskGate:
        """Build the first-stage gate from exact evidence and nonsemantic signals."""

        domain = state.best_value("domain", "")
        task_type = state.best_value("task_type", "")
        return TaskGate(
            domain=domain or None,
            task_type=task_type if task_type != "unknown" else None,
            standard=_int_or_none(state.context.get("standard")),
        )


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _looks_like_status_query(text: str) -> bool:
    status_terms = (
        "是否启用",
        "有没有启用",
        "是否开启",
        "有没有开启",
        "启用了",
        "enabled",
        "active",
        "loaded",
    )
    integration_terms = (
        "ai policy runtime",
        "plugin",
        "hook",
        "claude code",
        "codex",
        "插件",
        "钩子",
    )
    return any(term in text for term in status_terms) and any(
        term in text for term in integration_terms
    )


def _is_obviously_not_engineering_work(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    return _looks_like_status_query(stripped)


def _has_engineering_entrypoint(text: str, state: ExtractionState) -> bool:
    domain = state.best_value("domain", GENERAL_DOMAIN)
    task_type = state.best_value("task_type", UNKNOWN_TASK_TYPE)
    if domain != GENERAL_DOMAIN or task_type != UNKNOWN_TASK_TYPE:
        return True
    return _contains_engineering_surface(text)


def _contains_engineering_surface(text: str) -> bool:
    terms = (
        "api",
        "bug",
        "build",
        "class",
        "code",
        "compile",
        "function",
        "implementation",
        "refactor",
        "test",
        "代码",
        "函数",
        "接口",
        "实现",
        "测试",
        "编译",
        "重构",
        "修复",
        "设计",
    )
    file_or_code_markers = (".cpp", ".hpp", ".h", ".cc", ".cxx", ".py", ".ts", "::", "()", "->")
    return any(term in text for term in terms) or any(
        marker in text for marker in file_or_code_markers
    )
