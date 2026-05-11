from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RuleStrength(str, Enum):
    """Rule enforcement strength."""

    HARD = "HARD"
    SOFT = "SOFT"
    PREFERENCE = "PREFERENCE"


class RuleAction(str, Enum):
    """Normalized rule action used by the policy engine."""

    REQUIRE = "REQUIRE"
    FORBID = "FORBID"
    ALLOW = "ALLOW"
    RECOMMEND = "RECOMMEND"
    DISCOURAGE = "DISCOURAGE"
    PREFER = "PREFER"
    PREFER_ORDER = "PREFER_ORDER"


LEVEL_RANK = {
    "PLATFORM": 4,
    "DOMAIN": 3,
    "PROJECT": 2,
    "TASK": 1,
    "USER": 1,
}

STRENGTH_RANK = {
    RuleStrength.HARD: 3,
    RuleStrength.SOFT: 2,
    RuleStrength.PREFERENCE: 1,
}


@dataclass(frozen=True)
class Rule:
    """Normalized Rule IR consumed by conflict resolution and rendering."""

    id: str
    strength: RuleStrength
    target: str
    action: RuleAction
    value: Any
    description: str = ""
    condition: str | None = None
    unless: str | None = None
    source: str = ""
    level: str = "DOMAIN"
    priority: int = 0
    requires: tuple[str, ...] = ()
    over: tuple[Any, ...] = ()
    examples: tuple[Any, ...] = ()
    rationale: str = ""
    title: str = ""
    verification: tuple[Any, ...] = ()

    @classmethod
    def from_mapping(
        cls,
        data: dict[str, Any],
        *,
        strength: RuleStrength,
        source: str,
        level: str,
        priority: int,
    ) -> "Rule":
        action = str(data["action"]).upper()
        if action == "SHOULD":
            action = "RECOMMEND"
        elif action == "SHOULD_NOT":
            action = "DISCOURAGE"
        return cls(
            id=str(data["id"]),
            strength=strength,
            target=str(data["target"]),
            action=RuleAction(action),
            value=data.get("value"),
            description=str(data.get("description", data.get("reason", ""))),
            condition=data.get("condition", data.get("when")),
            unless=data.get("unless"),
            source=source,
            level=str(level).upper(),
            priority=int(priority),
            requires=tuple(data.get("requires", data.get("require", ()))),
            over=tuple(_as_list(data.get("over", ()))),
            examples=tuple(_as_list(data.get("examples", ()))),
            rationale=str(data.get("rationale", "")),
            title=str(data.get("title", "")),
            verification=tuple(_as_list(data.get("verification", ()))),
        )

    @property
    def is_conditional(self) -> bool:
        return bool(self.condition)

    def specificity(self) -> int:
        return 1 if self.condition else 0

    def precedence(self) -> tuple[int, int, int, int]:
        return (
            STRENGTH_RANK[self.strength],
            LEVEL_RANK.get(self.level, 0),
            self.priority,
            self.specificity(),
        )

    def conflicts_with(self, other: "Rule") -> bool:
        if self.target != other.target or self.value != other.value:
            return False
        conflict_pairs = {
            (RuleAction.FORBID, RuleAction.ALLOW),
            (RuleAction.ALLOW, RuleAction.FORBID),
            (RuleAction.DISCOURAGE, RuleAction.ALLOW),
            (RuleAction.ALLOW, RuleAction.DISCOURAGE),
            (RuleAction.REQUIRE, RuleAction.FORBID),
            (RuleAction.FORBID, RuleAction.REQUIRE),
            (RuleAction.RECOMMEND, RuleAction.DISCOURAGE),
            (RuleAction.DISCOURAGE, RuleAction.RECOMMEND),
        }
        return (self.action, other.action) in conflict_pairs

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "description": self.description,
            "target": self.target,
            "action": self.action.value,
            "value": self.value,
            "source": self.source,
        }
        if self.condition:
            data["condition"] = self.condition
        if self.unless:
            data["unless"] = self.unless
        if self.requires:
            data["requires"] = list(self.requires)
        if self.over:
            data["over"] = list(self.over)
        if self.examples:
            data["examples"] = list(self.examples)
        if self.rationale:
            data["rationale"] = self.rationale
        if self.title:
            data["title"] = self.title
        if self.verification:
            data["verification"] = list(self.verification)
        return data


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


@dataclass(frozen=True)
class ConflictDiagnostic:
    """Explains how a pair of conflicting rules was handled."""

    rule_id: str
    other_rule_id: str
    resolution: str
    winner_id: str | None = None


@dataclass
class EffectiveRules:
    """Task-specific rules after activation, conflict resolution, and reduction."""

    hard: list[Rule] = field(default_factory=list)
    soft: list[Rule] = field(default_factory=list)
    preferences: list[Rule] = field(default_factory=list)
    exceptions: list[Rule] = field(default_factory=list)
    conflicts: list[ConflictDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_rules": {
                "hard": [rule.to_dict() for rule in self.hard],
                "soft": [rule.to_dict() for rule in self.soft],
                "preferences": [rule.to_dict() for rule in self.preferences],
                "exceptions": [rule.to_dict() for rule in self.exceptions],
            },
            "diagnostics": {
                "conflicts": [
                    {
                        "rule_id": item.rule_id,
                        "other_rule_id": item.other_rule_id,
                        "resolution": item.resolution,
                        "winner_id": item.winner_id,
                    }
                    for item in self.conflicts
                ]
            },
        }
