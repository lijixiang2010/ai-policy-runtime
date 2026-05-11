from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_policy_runtime.services.verification import Violation


@dataclass(frozen=True)
class RepairInstruction:
    """Actionable instruction generated from a policy violation."""

    rule_id: str
    path: str
    line: int
    instruction: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "path": self.path,
            "line": self.line,
            "instruction": self.instruction,
        }


class RepairPlanner:
    """Generate deterministic repair instructions from violations."""

    def plan(self, violations: list[Violation]) -> list[RepairInstruction]:
        return [self._instruction(violation) for violation in violations]

    def _instruction(self, violation: Violation) -> RepairInstruction:
        location = f"{violation.path}:{violation.line}" if violation.line else violation.path
        return RepairInstruction(
            rule_id=violation.rule_id,
            path=violation.path,
            line=violation.line,
            instruction=(
                f"Fix violation {violation.rule_id} at {location}. "
                f"{violation.message} Revise the output so the rule is satisfied, "
                "then rerun policy verification."
            ),
        )


class RepairPlanWriter:
    """Persist repair instructions under .policy/current."""

    def __init__(self, root: str | Path) -> None:
        self.current = Path(root) / ".policy" / "current"

    def write(self, instructions: list[RepairInstruction]) -> Path:
        self.current.mkdir(parents=True, exist_ok=True)
        path = self.current / "repair-plan.json"
        path.write_text(
            json.dumps(
                {"repair_plan": [item.to_dict() for item in instructions]},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path
