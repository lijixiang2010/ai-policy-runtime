from __future__ import annotations

from .lexicon import TaskGate, TaskLexicon
from .matching import ExactRuleMatcher, normalize_text
from .resolution import (
    ExtractionState,
    default_task_type_evidence,
    signal_domain_evidence,
)
from .schema import ExtractionEvidence, TaskAnalysis, TaskSignals
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
        if _is_explicit_non_code_change_request(normalized):
            state.add(default_task_type_evidence())
            return state.to_analysis(self._lexicon)
        self._apply_domain(normalized, signals, state)
        self._apply_task_type(normalized, state)
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
        match = max(
            self._matcher.all(self._lexicon.trigger_rules, text),
            key=lambda item: item[1].confidence,
            default=None,
        )
        if match is None:
            state.add(default_task_type_evidence())
            return

        rule, evidence = match
        state.add(evidence)
        if domain := self._lexicon.domain_for_skill(rule.skill_id):
            if _can_infer_domain_from_trigger(domain, evidence.source):
                state.add(
                    ExtractionEvidence(
                        field="domain",
                        value=domain,
                        source=f"{rule.source}:inferred_domain",
                        confidence=evidence.confidence,
                    )
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
        gate: TaskGate | None,
    ) -> None:
        if self._semantic_index is None:
            return
        bootstrapped_scope: frozenset[str] | None = None
        if gate is not None and gate.task_type is None:
            self._apply_semantic_task_bootstrap(text, state)
            gate = self._semantic_gate(state)
        if gate is None:
            bootstrapped_scope = self._lexicon.generic_semantic_scope()
            for match in self._semantic_index.search_scoped(text, scope=bootstrapped_scope):
                if match.rule.field == "task_type":
                    state.apply_rule(match.rule, match.evidence())
            gate = self._semantic_gate(state)
            if gate is None:
                return
        scope = bootstrapped_scope or self._lexicon.semantic_scope(gate)
        if gate.domain is None:
            scope = scope | self._lexicon.generic_semantic_scope()
        if not scope:
            return
        if gate.task_type is None:
            for match in self._semantic_index.search_scoped(text, scope=scope):
                if match.rule.field == "task_type":
                    state.apply_rule(match.rule, match.evidence())
            gated = self._semantic_gate(state)
            if gated is None or gated.task_type is None:
                return
            scope = self._lexicon.semantic_scope(gated)
            if gated.domain is None:
                scope = scope | self._lexicon.generic_semantic_scope()
        for match in self._semantic_index.search_scoped(text, scope=scope):
            state.apply_rule(match.rule, match.evidence())

    def _apply_semantic_task_bootstrap(
        self,
        text: str,
        state: ExtractionState,
    ) -> None:
        if self._semantic_index is None:
            return
        current_domain = state.best_value("domain", "")
        for match in self._semantic_index.search_scoped(text, scope=None):
            if match.rule.field != "task_type":
                continue
            evidence = match.evidence()
            domain = self._lexicon.domain_for_skill(match.rule.skill_id)
            if domain and current_domain and domain != current_domain:
                if (
                    domain not in {"git", "cmake"}
                    or evidence.confidence < 0.5
                    or not _can_cross_project_domain_from_semantic_task(
                        domain,
                        str(match.rule.value),
                    )
                ):
                    continue
            state.apply_rule(match.rule, evidence)
            if domain and domain != "generic_code":
                state.add(
                    ExtractionEvidence(
                        field="domain",
                        value=domain,
                        source=f"{match.rule.source}:semantic_task_domain",
                        confidence=max(evidence.confidence, 0.72),
                    )
                )
            return

    def _semantic_gate(self, state: ExtractionState) -> TaskGate | None:
        """Build the first-stage gate from exact evidence and nonsemantic signals."""

        domain = state.best_value("domain", "")
        task_type = state.best_value("task_type", "")
        if not domain and (not task_type or task_type == "unknown"):
            return None
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


def _can_infer_domain_from_trigger(domain: str, source: str) -> bool:
    """Return whether an exact trigger phrase is specific enough to imply a domain."""

    phrase = source.rsplit(":", 1)[-1].lower()
    hints = {
        "cmake": (
            "cmake",
            "cmakelists",
            "ctest",
            "fetchcontent",
            "externalproject",
            "file glob",
            "file(glob)",
            "find_package",
            "generator expressions",
            "target_",
            "vcpkg",
            "conan",
        ),
        "git": (
            "git",
            "amend commit",
            "commit these changes",
            "commit this code",
            "commit code changes",
            "create commit",
            "conflict marker",
            "clean generated files",
            "clean ignored files",
            "clean untracked generated files",
            "force push",
            "force-with-lease",
            "interactive rebase",
            "merge conflict",
            "merge request",
            "prepare commit",
            "pull request",
            "rebase",
            "rebase conflict",
            "remove untracked files",
            "stage commit",
            "squash commits",
            "squash these commits",
            "stash",
        ),
    }
    return any(hint in phrase for hint in hints.get(domain, ()))


def _can_cross_project_domain_from_semantic_task(domain: str, task_type: str) -> bool:
    if domain == "git":
        return task_type in {
            "prepare_commit",
            "write_commit_message",
            "prepare_pull_request",
            "review_git_history",
            "rewrite_history",
            "undo_change",
            "resolve_conflict",
            "save_unfinished_work",
            "clean_working_tree",
            "manage_branch",
            "sync_branch",
        }
    return domain == "cmake"


def _is_explicit_non_code_change_request(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "no code changes",
            "do not change source code",
            "do not change code",
            "without changing source code",
            "explain only",
            "only explain",
            "summarize only",
            "不需要改代码",
            "不用改代码",
            "不要改代码",
            "不改代码",
            "不需要修改",
            "不要修改",
            "只分析",
            "只分析，不改",
            "只分析不改",
            "只分析，不修改",
            "只解释",
            "只总结",
        )
    )
