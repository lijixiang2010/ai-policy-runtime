from __future__ import annotations

from ai_policy_runtime.domain.rule import (
    ConflictDiagnostic,
    EffectiveRules,
    Rule,
    RuleAction,
    RuleStrength,
)
from ai_policy_runtime.domain.task import TaskContext
from ai_policy_runtime.infrastructure.conditions import ConditionError, evaluate_condition
from ai_policy_runtime.services.registry import SkillRegistry


class PolicyConflictError(RuntimeError):
    """Raised when active HARD rules cannot be reconciled."""

    pass


class PolicyEngine:
    """Build Effective Rules from activated skills and pack overrides."""

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry
        self._resolver = RuleConflictResolver()
        self._reducer = RuleReducer()

    def evaluate(self, task: TaskContext, pack_ids: tuple[str, ...] = ()) -> EffectiveRules:
        active_skills, pack_overrides = self.registry.activate(task, pack_ids)
        rules = [rule for skill in active_skills for rule in skill.rules]
        rules.extend(pack_overrides)
        rules = [rule for rule in rules if self._rule_applies(rule, task)]
        resolved, diagnostics = self._resolver.resolve(rules)
        return self._reducer.reduce(resolved, diagnostics)

    def _rule_applies(self, rule: Rule, task: TaskContext) -> bool:
        context = task.condition_context()
        try:
            if not evaluate_condition(rule.condition, context):
                return False
            if rule.unless and self._unless_applies(rule.unless, context):
                return False
            return True
        except ConditionError:
            return False

    def _unless_applies(self, expression: str, context: dict[str, object]) -> bool:
        """Treat unknown exception flags as absent rather than disabling a rule."""

        try:
            return evaluate_condition(expression, context)
        except ConditionError:
            return False


class RuleConflictResolver:
    """Resolve active Rule IR conflicts before reduction."""

    def resolve(self, rules: list[Rule]) -> tuple[list[Rule], list[ConflictDiagnostic]]:
        kept: list[Rule] = []
        diagnostics: list[ConflictDiagnostic] = []

        for rule in sorted(rules, key=lambda item: item.precedence(), reverse=True):
            conflicting = [item for item in kept if rule.conflicts_with(item)]
            if not conflicting:
                kept.append(rule)
                continue

            should_keep = True
            for other in conflicting:
                if not self._handle_conflict(rule, other, kept, diagnostics):
                    should_keep = False
                    break

            if should_keep:
                kept.append(rule)

        return kept, diagnostics

    def _handle_conflict(
        self,
        rule: Rule,
        other: Rule,
        kept: list[Rule],
        diagnostics: list[ConflictDiagnostic],
    ) -> bool:
        if rule.strength == other.strength == RuleStrength.HARD:
            raise PolicyConflictError(
                f"Unresolvable HARD conflict: {rule.id} conflicts with {other.id}"
            )

        if rule.condition != other.condition and (
            rule.is_conditional or other.is_conditional
        ):
            diagnostics.append(
                ConflictDiagnostic(
                    rule_id=rule.id,
                    other_rule_id=other.id,
                    resolution="kept default rule and conditional exception",
                    winner_id=None,
                )
            )
            return True

        if other.precedence() >= rule.precedence():
            diagnostics.append(
                ConflictDiagnostic(
                    rule_id=rule.id,
                    other_rule_id=other.id,
                    resolution="suppressed by higher precedence rule",
                    winner_id=other.id,
                )
            )
            return False

        kept.remove(other)
        diagnostics.append(
            ConflictDiagnostic(
                rule_id=rule.id,
                other_rule_id=other.id,
                resolution="replaced lower precedence rule",
                winner_id=rule.id,
            )
        )
        return True


class RuleReducer:
    """Reduce resolved rules into a stable minimal set."""

    def reduce(
        self, rules: list[Rule], diagnostics: list[ConflictDiagnostic]
    ) -> EffectiveRules:
        effective = EffectiveRules(conflicts=diagnostics)
        for rule in self.deduplicate(rules):
            self._add_rule(effective, rule)
        return effective

    def deduplicate(self, rules: list[Rule]) -> list[Rule]:
        by_key: dict[tuple[object, ...], Rule] = {}
        for rule in sorted(rules, key=lambda item: item.precedence(), reverse=True):
            key = (
                rule.strength,
                rule.target,
                rule.action,
                str(rule.value),
                rule.condition,
                rule.unless,
            )
            by_key.setdefault(key, rule)
        return sorted(by_key.values(), key=lambda item: item.precedence(), reverse=True)

    def _add_rule(self, effective: EffectiveRules, rule: Rule) -> None:
        if rule.condition and rule.action == RuleAction.ALLOW:
            effective.exceptions.append(rule)
        elif rule.strength == RuleStrength.HARD:
            effective.hard.append(rule)
        elif rule.strength == RuleStrength.SOFT:
            effective.soft.append(rule)
        else:
            effective.preferences.append(rule)
