from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from ai_policy_runtime.domain.rule import EffectiveRules, Rule
from ai_policy_runtime.domain.task import TaskContext


SCHEMA_VERSION = 1


class EffectiveRulesRenderer:
    """Render Effective Rules into the standardized machine and agent formats."""

    def __init__(
        self,
        *,
        mapper: "RuleEffectiveMapper | None" = None,
        prompt: "PromptRenderer | None" = None,
    ) -> None:
        self._mapper = mapper or RuleEffectiveMapper()
        self._prompt = prompt or PromptRenderer()

    def to_mapping(
        self,
        *,
        task: TaskContext,
        task_id: str,
        summary: str,
        rules: EffectiveRules,
        trace: dict[str, Any],
    ) -> dict[str, Any]:
        generated_at = trace.get("generated_at") or datetime.now(timezone.utc).isoformat()
        structured_trace = {
            "activated_skills": trace.get("active_skills", trace.get("activated_skills", [])),
            "packs": trace.get("packs", []),
            "conflict_count": trace.get("conflict_count", len(rules.conflicts)),
            "generated_at": generated_at,
        }
        return {
            "effective_rules": {
                "schema_version": SCHEMA_VERSION,
                "task": {
                    "id": task_id,
                    "summary": summary,
                    "context": _task_context(task),
                },
                "hard": [self._mapper.rule(rule) for rule in rules.hard],
                "soft": [self._mapper.rule(rule) for rule in rules.soft],
                "preference": [
                    self._mapper.preference(rule) for rule in rules.preferences
                ],
                "exceptions": [
                    self._mapper.exception(rule) for rule in rules.exceptions
                ],
                "verification": self._mapper.verification(rules),
                "trace": structured_trace,
            }
        }

    def to_prompt(self, mapping: dict[str, Any]) -> str:
        return self._prompt.render(mapping)

    def to_yaml(self, mapping: dict[str, Any]) -> str:
        try:
            import yaml  # type: ignore
        except ImportError:
            return _to_simple_yaml(mapping) + "\n"
        return yaml.safe_dump(mapping, sort_keys=False, allow_unicode=True)

    def to_json(self, mapping: dict[str, Any]) -> str:
        return json.dumps(mapping, indent=2, ensure_ascii=False)


class PromptRenderer:
    """Render standardized effective rules into an agent-readable prompt."""

    def render(self, mapping: dict[str, Any]) -> str:
        effective = mapping["effective_rules"]
        lines = ["# Effective Rules for Current Task", "", "## Task Context", ""]
        for key, value in effective["task"]["context"].items():
            lines.append(f"- {_label(key)}: {_format_context_value(key, value)}")
        self._append_rule_lines(lines, "HARD Rules", effective["hard"])
        self._append_rule_lines(lines, "SOFT Rules", effective["soft"])
        self._append_preference_lines(lines, effective["preference"])
        self._append_exception_lines(lines, effective["exceptions"])
        self._append_verification_lines(lines, effective["verification"])
        return "\n".join(lines).rstrip() + "\n"

    def _append_rule_lines(
        self, lines: list[str], title: str, rules: list[dict[str, Any]]
    ) -> None:
        if not rules:
            return
        lines.extend(["", f"## {title}", ""])
        lines.extend(f"- {rule['statement']}" for rule in rules)

    def _append_preference_lines(
        self, lines: list[str], rules: list[dict[str, Any]]
    ) -> None:
        if not rules:
            return
        lines.extend(["", "## Preferences", ""])
        lines.extend(f"- {rule['statement']}" for rule in rules)

    def _append_exception_lines(
        self, lines: list[str], exceptions: list[dict[str, Any]]
    ) -> None:
        if not exceptions:
            return
        lines.extend(["", "## Exceptions", ""])
        for exception in exceptions:
            allowed = ", ".join(str(item) for item in exception.get("allow", []))
            condition = exception.get("condition")
            statement = f"{allowed} allowed"
            if condition:
                statement = f"When {condition}, {statement}"
            if exception.get("require"):
                statement += f"; requires: {', '.join(exception['require'])}"
            lines.append(f"- {statement}.")

    def _append_verification_lines(
        self, lines: list[str], verification: dict[str, list[dict[str, Any]]]
    ) -> None:
        required = verification.get("required", [])
        recommended = verification.get("recommended", [])
        if not required and not recommended:
            return
        lines.extend(["", "## Verification Requirements", ""])
        lines.extend(f"- {item['statement']}" for item in required)
        lines.extend(f"- Recommended: {item['statement']}" for item in recommended)


class RuleEffectiveMapper:
    """Map internal Rule IR objects into effective-rules schema entries."""

    def rule(self, rule: Rule) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": rule.id,
            "target": rule.target,
            "action": rule.action.value.lower(),
            "statement": _statement(rule),
            "source": {"skill": rule.source, "rule": rule.id},
        }
        if rule.condition:
            data["condition"] = rule.condition
        if rule.requires:
            data["requirements"] = list(rule.requires)
        if rule.unless:
            data["exceptions"] = [rule.unless]
        return data

    def preference(self, rule: Rule) -> dict[str, Any]:
        data = self.rule(rule)
        data["action"] = "prefer"
        prefer, over = _split_preference(rule)
        if prefer:
            data["prefer"] = prefer
        if over:
            data["over"] = over
        return data

    def exception(self, rule: Rule) -> dict[str, Any]:
        return {
            "id": rule.id,
            "condition": rule.condition,
            "allow": [rule.value],
            "require": list(rule.requires),
            "source": {"skill": rule.source, "rule": rule.id},
        }

    def verification(
        self, rules: EffectiveRules
    ) -> dict[str, list[dict[str, Any]]]:
        required = [
            {
                "id": f"verify.{rule.id}",
                "type": "policy_check",
                "statement": f"Verify: {_statement(rule)}",
                "rule": rule.id,
            }
            for rule in rules.hard
        ]
        recommended = [
            {
                "id": f"verify.{rule.id}",
                "type": "review_check",
                "statement": f"Review: {_statement(rule)}",
                "rule": rule.id,
            }
            for rule in rules.soft
            if rule.verification
        ]
        return {"required": required, "recommended": recommended}


def _task_context(task: TaskContext) -> dict[str, Any]:
    return {
        **task.context,
        "domain": task.domain,
        "task_type": task.task_type,
        "capabilities": list(task.capabilities),
        "tags": list(task.tags),
    }


def _statement(rule: Rule) -> str:
    return rule.description or str(rule.value)


def _split_preference(rule: Rule) -> tuple[str | None, str | None]:
    if rule.over:
        return str(rule.value).split(" > ", 1)[0], str(rule.over[0])
    if isinstance(rule.value, str) and " > " in rule.value:
        prefer, over = rule.value.split(" > ", 1)
        return prefer, over
    return str(rule.value) if rule.value is not None else None, None


def _label(key: str) -> str:
    return key.replace("_", " ").title()


def _format_context_value(key: str, value: Any) -> str:
    if key == "language" and value == "cpp":
        return "C++"
    if key == "standard" and value:
        return f"C++{value}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _to_simple_yaml(data: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(data, dict):
        return "\n".join(
            f"{prefix}{key}:\n{_to_simple_yaml(value, indent + 2)}"
            if isinstance(value, (dict, list))
            else f"{prefix}{key}: {_scalar(value)}"
            for key, value in data.items()
        )
    if isinstance(data, list):
        if not data:
            return f"{prefix}[]"
        return "\n".join(
            f"{prefix}-\n{_to_simple_yaml(item, indent + 2)}"
            if isinstance(item, (dict, list))
            else f"{prefix}- {_scalar(item)}"
            for item in data
        )
    return f"{prefix}{_scalar(data)}"


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)
