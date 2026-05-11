from __future__ import annotations

from ai_policy_runtime.domain.rule import EffectiveRules, Rule


def build_prompt_section(effective_rules: EffectiveRules) -> str:
    lines = ["Follow these effective rules:"]
    _append_rules(lines, "HARD", effective_rules.hard)
    _append_rules(lines, "SOFT", effective_rules.soft)
    _append_rules(lines, "PREFERENCES", effective_rules.preferences)
    _append_rules(lines, "EXCEPTIONS", effective_rules.exceptions)
    return "\n".join(lines)


def _append_rules(lines: list[str], title: str, rules: list[Rule]) -> None:
    if not rules:
        return
    lines.append("")
    lines.append(f"{title}:")
    for rule in rules:
        text = rule.description or f"{rule.action.value} {rule.value}"
        if rule.condition:
            text = f"When {rule.condition}: {text}"
        if rule.requires:
            text = f"{text} Requires: {', '.join(rule.requires)}."
        lines.append(f"- {text}")
