from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .rule import Rule, RuleStrength


@dataclass(frozen=True)
class Skill:
    """A parsed Skill DSL document with normalized Rule IR entries."""

    skill_id: str
    name: str
    version: str = "1.0.0"
    level: str = "DOMAIN"
    priority: int = 0
    status: str = "stable"
    domains: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)
    activation_when: str | None = None
    dependencies: tuple[str, ...] = ()
    incompatibilities: tuple[str, ...] = ()
    verification: tuple[dict[str, Any], ...] = ()
    rules: tuple[Rule, ...] = ()

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "Skill":
        data = SkillDocument(data).normalized()

        skill_id = str(data["skill_id"])
        level = str(data.get("level", "DOMAIN")).upper()
        priority = int(data.get("priority", 0))

        scope = data.get("scope", {})
        domains = tuple(data.get("domains", scope.get("domains", ())))
        triggers = tuple(data.get("triggers", scope.get("triggers", ())))
        capabilities = tuple(data.get("capabilities", scope.get("capabilities", ())))
        tags = tuple(data.get("tags", scope.get("tags", ())))

        rules = RuleFactory(skill_id, level, priority).from_skill_mapping(data)

        return cls(
            skill_id=skill_id,
            name=str(data.get("name", skill_id)),
            version=str(data.get("version", "1.0.0")),
            level=level,
            priority=priority,
            status=str(data.get("status", "stable")),
            domains=domains,
            triggers=triggers,
            capabilities=capabilities,
            tags=tags,
            context=dict(data.get("context", {})),
            activation_when=data.get("activation", {}).get("when"),
            dependencies=tuple(data.get("dependencies", ())),
            incompatibilities=tuple(data.get("incompatibilities", ())),
            verification=tuple(data.get("verification", ())),
            rules=tuple(rules),
        )


class SkillDocument:
    """Compatibility adapter for supported Skill DSL shapes."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def normalized(self) -> dict[str, Any]:
        """Return a canonical mapping consumed by Skill.from_mapping."""

        if "skill" not in self._data or "skill_id" in self._data:
            return self._data

        meta = self._data.get("skill", {})
        activation = self._data.get("activation", meta.get("activation", {}))
        context, activation = self._normalized_context(activation)
        return {
            **self._data,
            "skill_id": meta.get("id"),
            "name": meta.get("name"),
            "version": meta.get("version"),
            "description": meta.get("description"),
            "level": meta.get("level"),
            "priority": meta.get("priority"),
            "status": meta.get("status") or self._data.get("status", "stable"),
            "scope": self._scope(meta, activation),
            "activation": activation,
            "context": context,
            "dependencies": self._data.get("dependencies", meta.get("dependencies", ())),
            "incompatibilities": self._data.get(
                "incompatibilities", meta.get("incompatibilities", ())
            ),
        }

    def _scope(self, meta: dict[str, Any], activation: dict[str, Any]) -> dict[str, Any]:
        scope = self._data.get("scope", {})
        if scope:
            return scope
        return {
            "domains": [meta["domain"]] if meta.get("domain") else (),
            "triggers": activation.get("triggers", ()),
            "capabilities": meta.get("capabilities", ()),
            "tags": (),
        }

    def _normalized_context(
        self, activation: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        activation_when = activation.get("when")
        context = dict(self._data.get("context", {}))
        if isinstance(activation_when, dict):
            return {**context, **activation_when}, {**activation, "when": None}
        return context, activation


class RuleFactory:
    """Build normalized Rule IR objects from Skill DSL sections."""

    _RULE_GROUPS = (
        ("hard", RuleStrength.HARD),
        ("soft", RuleStrength.SOFT),
        ("preference", RuleStrength.PREFERENCE),
        ("preferences", RuleStrength.PREFERENCE),
    )

    def __init__(self, skill_id: str, level: str, priority: int) -> None:
        self.skill_id = skill_id
        self.level = level
        self.priority = priority

    def from_skill_mapping(self, data: dict[str, Any]) -> tuple[Rule, ...]:
        rules = [
            self._build(rule_data, strength)
            for key, strength in self._RULE_GROUPS
            for rule_data in data.get("rules", {}).get(key, ())
        ]
        rules.extend(
            self._build_exception_rule(exception, allowed)
            for exception in data.get("exceptions", ())
            for allowed in exception.get("allow", ())
        )
        return tuple(rules)

    def _build(self, rule_data: dict[str, Any] | str, strength: RuleStrength) -> Rule:
        return Rule.from_mapping(
            _normalize_rule_data(rule_data, strength, self.skill_id),
            strength=strength,
            source=self.skill_id,
            level=self.level,
            priority=self.priority,
        )

    def _build_exception_rule(self, exception: dict[str, Any], allowed: Any) -> Rule:
        condition = exception.get("when")
        rule_data = dict(allowed) if isinstance(allowed, dict) else {
            "id": f"{self.skill_id}.exception.{allowed}",
            "target": str(allowed),
            "action": "ALLOW",
            "value": str(allowed),
            "description": f"Allow {allowed} when {condition}.",
        }
        rule_data.setdefault("condition", condition)
        rule_data.setdefault("requires", exception.get("require", ()))
        return Rule.from_mapping(
            rule_data,
            strength=RuleStrength.SOFT,
            source=self.skill_id,
            level=self.level,
            priority=self.priority,
        )


def _normalize_rule_data(
    rule_data: dict[str, Any] | str, strength: RuleStrength, skill_id: str
) -> dict[str, Any]:
    if isinstance(rule_data, str):
        return _parse_clause(rule_data, strength, skill_id)

    data = dict(rule_data)
    keyword_action = {
        "must": "REQUIRE",
        "must_not": "FORBID",
        "should": "RECOMMEND",
        "should_not": "DISCOURAGE",
        "allow": "ALLOW",
        "prefer": "PREFER",
    }
    for keyword, action in keyword_action.items():
        if keyword in data:
            value = data[keyword]
            if keyword == "prefer" and isinstance(value, dict):
                value = f"{value.get('higher')} > {value.get('lower')}"
            if keyword == "prefer" and "over" in data and not isinstance(value, str):
                value = f"{value} > {data['over']}"
            elif keyword == "prefer" and "over" in data:
                over = data["over"]
                if isinstance(over, list):
                    over = " > ".join(str(item) for item in over)
                value = f"{value} > {over}"
            data["action"] = action
            data.setdefault("value", value)
            break

    if "when" in data:
        data["condition"] = data["when"]
    data.setdefault("id", f"{skill_id}.{data.get('target', data.get('value', 'rule'))}")
    data.setdefault("target", str(data.get("value", data["id"])))
    data.setdefault(
        "description",
        data.get("reason", data.get("should", data.get("must", str(data.get("value", ""))))),
    )
    if "require" in data:
        data.setdefault("requires", data["require"])
    return data


def _parse_clause(text: str, strength: RuleStrength, skill_id: str) -> dict[str, Any]:
    upper = text.upper()
    condition = None
    requires: list[str] = []

    body = text
    if upper.startswith("WHEN "):
        directive_positions = [
            pos for token in (" MUST_NOT ", " MUST ", " SHOULD_NOT ", " SHOULD ", " ALLOW ", " PREFER ")
            if (pos := upper.find(token)) >= 0
        ]
        if directive_positions:
            split_at = min(directive_positions)
            condition = text[5:split_at].strip()
            body = text[split_at + 1 :].strip()

    upper_body = body.upper()
    if " REQUIRE " in upper_body:
        req_at = upper_body.find(" REQUIRE ")
        requires = [item.strip() for item in body[req_at + 9 :].split(",") if item.strip()]
        body = body[:req_at].strip()
        upper_body = body.upper()

    keyword_action = [
        ("MUST_NOT ", "FORBID"),
        ("MUST ", "REQUIRE"),
        ("SHOULD_NOT ", "DISCOURAGE"),
        ("SHOULD ", "RECOMMEND"),
        ("ALLOW ", "ALLOW"),
        ("PREFER ", "PREFER"),
    ]
    for prefix, action in keyword_action:
        if upper_body.startswith(prefix):
            value = body[len(prefix) :].strip()
            return {
                "id": f"{skill_id}.{value.replace(' ', '_').replace('>', 'gt')}",
                "condition": condition,
                "action": action,
                "value": value,
                "target": value.split()[0],
                "description": value,
                "requires": requires,
            }
    raise ValueError(f"Unsupported rule clause: {text}")
