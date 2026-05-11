from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskContext:
    """Structured task facts used for activation and rule conditions."""

    domain: str
    task_type: str
    capabilities: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "TaskContext":
        return cls(
            domain=str(data["domain"]),
            task_type=str(data["task_type"]),
            capabilities=tuple(data.get("capabilities", ())),
            tags=tuple(data.get("tags", ())),
            context=dict(data.get("context", {})),
        )

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    def condition_context(self) -> dict[str, Any]:
        """Return the flat variable map consumed by condition expressions."""

        return {
            **self.context,
            "domain": self.domain,
            "trigger": self.task_type,
            "task_type": self.task_type,
            "capabilities": list(self.capabilities),
            "tags": list(self.tags),
        }
