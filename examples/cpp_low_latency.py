from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_policy_runtime import PolicyEngine, SkillRegistry, TaskContext
from ai_policy_runtime.prompt_builder import build_prompt_section


def main() -> None:
    registry = SkillRegistry.from_dir(ROOT / "skills")
    task = TaskContext(
        domain="cpp",
        task_type="write_code",
        capabilities=("code_generation",),
        tags=("low_latency", "hot_path"),
        context={
            "language": "cpp",
            "standard": 20,
            "hot_path": True,
            "scenario": "matching_engine",
        },
    )

    effective = PolicyEngine(registry).evaluate(task)
    print(json.dumps(effective.to_dict(), indent=2))
    print()
    print(build_prompt_section(effective))


if __name__ == "__main__":
    main()
