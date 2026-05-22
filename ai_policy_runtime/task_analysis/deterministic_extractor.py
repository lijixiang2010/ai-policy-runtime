from __future__ import annotations

from .lexicon import LexiconRule, TaskGate, TaskLexicon
from .matching import ExactRuleMatcher, normalize_text
from .resolution import (
    ExtractionState,
    default_task_type_evidence,
    signal_domain_evidence,
)
from .schema import ExtractionEvidence, TaskAnalysis, TaskSignals
from .semantic_index import SemanticMatch, SemanticTaskIndex


PROJECT_SIGNAL_SEMANTIC_TASK_MIN_CONFIDENCE = 0.6
PROJECT_SIGNAL_CROSS_DOMAIN_SEMANTIC_TASK_MIN_CONFIDENCE = 0.65
PROJECT_SIGNAL_BORDERLINE_CROSS_DOMAIN_CONFIDENCE = 0.64
PROJECT_SIGNAL_BORDERLINE_MIN_TEXT_LENGTH = 12
SHORT_GIT_COMMIT_INTENT_CONFIDENCE = 0.47
SHORT_GIT_COMMIT_MAX_TEXT_LENGTH = 6
GIT_WORKING_TREE_COMMIT_INTENT_CONFIDENCE = 0.6


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
        if self._is_semantic_non_code_change_request(normalized):
            state.add(default_task_type_evidence())
            return state.to_analysis(self._lexicon)
        self._apply_domain(normalized, signals, state)
        self._apply_task_type(normalized, state)
        self._apply_git_working_tree_commit_intent(normalized, signals, state)
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

    def _apply_git_working_tree_commit_intent(
        self,
        text: str,
        signals: TaskSignals | None,
        state: ExtractionState,
    ) -> None:
        if not signals or not signals.git_has_changes or self._semantic_index is None:
            return
        if state.best_value("task_type", "") != "unknown":
            return
        text_length = len(text.strip())
        score = self._semantic_index.best_text_score(
            text,
            (
                "commit current changes",
                "commit the current changes",
                "commit code changes",
                "commit these changes",
                "commit workspace changes",
                "create one git commit",
                "create a commit for the current changes",
                "make one commit",
                "make one commit for current changes",
                "commit once",
                "commit now",
                "make the commit",
                "commit it",
                "ready for commit",
                "prepare to commit",
                "prepare a git commit for current changes",
                "can commit now",
                "you can commit now",
                "you can commit release preparation changes now",
                "create a single commit",
                "commit the current work",
                "commit the release preparation changes",
                "stage and commit current changes",
                "turn current changes into one git commit",
                "save current code changes into git history",
            ),
        )
        threshold = (
            SHORT_GIT_COMMIT_INTENT_CONFIDENCE
            if text_length <= SHORT_GIT_COMMIT_MAX_TEXT_LENGTH
            else GIT_WORKING_TREE_COMMIT_INTENT_CONFIDENCE
        )
        if score < threshold:
            return
        state.apply_rule(
            _semantic_signal_rule(
                "git.workflow.commit_hygiene",
                "task_type",
                "prepare_commit",
                set_context={"git_working_tree_sensitive": True},
                tags=("git",),
            ),
            ExtractionEvidence(
                field="task_type",
                value="prepare_commit",
                source="signal:git_working_tree:semantic_short_commit_intent",
                confidence=max(score, 0.66),
            ),
        )
        state.add(
            ExtractionEvidence(
                field="domain",
                value="git",
                source="signal:git_working_tree:semantic_short_commit_intent",
                confidence=0.72,
            )
        )

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
            self._apply_semantic_task_bootstrap(text, state)
            gate = self._semantic_gate(state)
            if gate is None:
                bootstrapped_scope = self._lexicon.generic_semantic_scope()
                for match in self._semantic_index.search_scoped(text, scope=bootstrapped_scope):
                    if match.rule.field == "task_type":
                        self._apply_semantic_task_match(match, state)
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
                    self._apply_semantic_task_match(match, state)
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
        domain_from_project_signal = _domain_from_project_signal(state, current_domain)
        for match in self._semantic_index.search_scoped(text, scope=None):
            if match.rule.field != "task_type":
                continue
            evidence = match.evidence()
            domain = self._lexicon.domain_for_skill(match.rule.skill_id)
            if not self._semantic_task_allowed(
                match,
                evidence,
                current_domain,
                domain_from_project_signal,
                text,
            ):
                continue
            if not current_domain and (not domain or domain == "generic_code"):
                continue
            if domain and not current_domain:
                if (
                    domain != "git"
                    or evidence.confidence < 0.64
                    or str(match.rule.value)
                    not in _GIT_NO_SIGNAL_SEMANTIC_BOOTSTRAP_TASKS
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

    def _apply_semantic_task_match(
        self,
        match: SemanticMatch,
        state: ExtractionState,
    ) -> None:
        evidence = match.evidence()
        current_domain = state.best_value("domain", "")
        if not self._semantic_task_allowed(
            match,
            evidence,
            current_domain,
            _domain_from_project_signal(state, current_domain),
            "",
        ):
            return
        state.apply_rule(match.rule, evidence)

    def _semantic_task_allowed(
        self,
        match: SemanticMatch,
        evidence: ExtractionEvidence,
        current_domain: str,
        domain_from_project_signal: bool,
        text: str,
    ) -> bool:
        domain = self._lexicon.domain_for_skill(match.rule.skill_id)
        if (
            domain
            and current_domain
            and domain == current_domain
            and domain == "python"
            and domain_from_project_signal
            and evidence.confidence < PROJECT_SIGNAL_SEMANTIC_TASK_MIN_CONFIDENCE
        ):
            return False
        if domain and current_domain and domain != current_domain:
            min_confidence = (
                _project_signal_cross_domain_min_confidence(text)
                if domain_from_project_signal
                else 0.5
            )
            if (
                domain not in {"git", "cmake"}
                or evidence.confidence < min_confidence
                or not _can_cross_project_domain_from_semantic_task(
                    domain,
                    str(match.rule.value),
                )
            ):
                return False
        return True

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

    def _is_semantic_non_code_change_request(self, text: str) -> bool:
        if self._semantic_index is None:
            return False
        return (
            self._semantic_index.best_text_score(
                text,
                (
                    "no code changes",
                    "do not change source code",
                    "explain code only without modifying it",
                    "summarize text or logs without changing code",
                    "rewrite documentation copy without code changes",
                    "write release notes or issue text without source changes",
                ),
            )
            >= 0.7
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


def _domain_from_project_signal(state: ExtractionState, current_domain: str) -> bool:
    return any(
        item.field == "domain"
        and item.value == current_domain
        and item.source == "signal:project_language"
        for item in state.evidence
    )


def _project_signal_cross_domain_min_confidence(text: str) -> float:
    if len(text.strip()) >= PROJECT_SIGNAL_BORDERLINE_MIN_TEXT_LENGTH:
        return PROJECT_SIGNAL_BORDERLINE_CROSS_DOMAIN_CONFIDENCE
    return PROJECT_SIGNAL_CROSS_DOMAIN_SEMANTIC_TASK_MIN_CONFIDENCE


def _semantic_signal_rule(
    skill_id: str,
    field: str,
    value: object,
    *,
    set_context: dict[str, object] | None = None,
    tags: tuple[str, ...] = (),
) -> LexiconRule:
    return LexiconRule(
        skill_id=skill_id,
        field=field,
        value=value,
        phrases=(),
        confidence=1.0,
        source="signal:semantic",
        set_context=set_context or {},
        tags=tags,
    )


_GIT_NO_SIGNAL_SEMANTIC_BOOTSTRAP_TASKS = {
    "prepare_commit",
    "write_commit_message",
    "review_git_history",
    "rewrite_history",
    "undo_change",
}


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
        )
    )
