from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_policy_runtime.domain.rule import EffectiveRules
from ai_policy_runtime.domain.task import TaskContext
from ai_policy_runtime.services.effective_rules import EffectiveRulesRenderer


def write_current_state(
    *,
    root: str | Path,
    task: TaskContext,
    effective_rules: EffectiveRules,
    trace: dict[str, Any],
    project_context: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any]]:
    return PolicyStateWriter(root).write(task, effective_rules, trace, project_context)


class PolicyStateWriter:
    """Write the current resolved policy state to .policy/current."""

    def __init__(
        self,
        root: str | Path,
        renderer: EffectiveRulesRenderer | None = None,
    ) -> None:
        self.current = Path(root) / ".policy" / "current"
        self.renderer = renderer or EffectiveRulesRenderer()

    def write(
        self,
        task: TaskContext,
        effective_rules: EffectiveRules,
        trace: dict[str, Any],
        project_context: dict[str, Any] | None = None,
    ) -> tuple[Path, dict[str, Any]]:
        self.current.mkdir(parents=True, exist_ok=True)
        trace = {"generated_at": _utc_now(), **trace}
        task_id = str(trace.get("task_id", "task_current"))
        summary = str(trace.get("task", trace.get("summary", "")))
        mapping = self.renderer.to_mapping(
            task=task,
            task_id=task_id,
            summary=summary,
            rules=effective_rules,
            trace=trace,
        )
        self._write_task_context(task_id, summary, task)
        if project_context is not None:
            _write_json(self.current / "project-context.json", project_context)
        self._write_effective_rules(mapping)
        _write_json(self.current / "trace.json", trace)
        return self.current, mapping

    def _write_task_context(
        self, task_id: str, summary: str, task: TaskContext
    ) -> None:
        _write_json(
            self.current / "task-context.json",
            {
                "task": {
                    "id": task_id,
                    "summary": summary,
                    "context": {
                        **task.context,
                        "domain": task.domain,
                        "task_type": task.task_type,
                        "capabilities": list(task.capabilities),
                        "tags": list(task.tags),
                    },
                }
            },
        )

    def _write_effective_rules(self, mapping: dict[str, Any]) -> None:
        files = {
            "effective-rules.json": self.renderer.to_json(mapping),
            "effective-rules.yaml": self.renderer.to_yaml(mapping),
            "effective-prompt.md": self.renderer.to_prompt(mapping),
        }
        for name, text in files.items():
            (self.current / name).write_text(text, encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, data: Any) -> None:
    import json

    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
