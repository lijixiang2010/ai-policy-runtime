from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from hooks.user_prompt_submit import (
    HOOK_STATE_PATH,
    ProjectHookConfig,
    _prepare_imports,
    _read_payload,
)

_prepare_imports()

from ai_policy_runtime import PolicyRuntime, RuntimeConfig
from ai_policy_runtime.adapters.agent import build_post_refinement_task, merge_pack_ids


def main() -> int:
    payload = _read_payload()
    try:
        response = build_stop_response(payload)
    except Exception as exc:
        response = {
            "continue": True,
            "systemMessage": (
                "AI Policy Runtime Stop hook could not prepare post-task refinement. "
                f"{type(exc).__name__}: {exc}"
            ),
        }
    print(json.dumps(response, ensure_ascii=False))
    return 0


def build_stop_response(payload: dict[str, object]) -> dict[str, object]:
    """Return the Codex Stop-hook response for optional refinement continuation."""

    if bool(payload.get("stop_hook_active")):
        return {"continue": True}

    project_root = Path(payload.get("cwd") or ".").resolve()
    config = ProjectHookConfig.load(project_root)
    if not config.enabled or config.post_refine_mode == "off":
        return {"continue": True}

    prompt = _original_prompt(project_root, payload)
    reason = build_refinement_continuation_prompt(prompt, project_root, config)
    return {
        "decision": "block",
        "reason": reason,
    }


def build_refinement_continuation_prompt(
    prompt: str,
    project_root: Path,
    config: ProjectHookConfig,
) -> str:
    """Build the prompt Codex receives when Stop requests one more pass."""

    refinement_task = build_post_refinement_task(prompt, config.post_refine_mode)
    effective_prompt = _resolve_refinement_effective_prompt(
        refinement_task,
        project_root,
        config,
    )
    verification = _verification_instruction(config.verify_target)
    return (
        f"{refinement_task}\n\n"
        "Apply these task-scoped Effective Rules during this continuation pass:\n\n"
        f"{effective_prompt}\n\n"
        f"{verification}"
    )


def _resolve_refinement_effective_prompt(
    refinement_task: str,
    project_root: Path,
    config: ProjectHookConfig,
) -> str:
    runtime = PolicyRuntime(
        RuntimeConfig.from_values(
            root=project_root,
            policy_root=config.policy_root(project_root),
        )
    )
    pack_ids = merge_pack_ids(config.packs, config.post_refine_pack_ids)
    result = runtime.resolve(refinement_task, pack_ids)
    return (result.current / "effective-prompt.md").read_text(encoding="utf-8")


def _original_prompt(project_root: Path, payload: dict[str, object]) -> str:
    state = _load_turn_state(project_root)
    prompt = _state_prompt_for_turn(state, payload)
    if prompt:
        return prompt
    return "the just-completed Codex task"


def _load_turn_state(project_root: Path) -> dict[str, Any]:
    path = project_root / HOOK_STATE_PATH
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _state_prompt_for_turn(
    state: dict[str, Any],
    payload: dict[str, object],
) -> str | None:
    state_turn_id = state.get("turn_id")
    payload_turn_id = payload.get("turn_id")
    if state_turn_id and payload_turn_id and state_turn_id != payload_turn_id:
        return None
    prompt = state.get("prompt")
    return str(prompt).strip() if prompt else None


def _verification_instruction(verify_target: str | None) -> str:
    if not verify_target:
        return (
            "Before ending, run the relevant local checks when practical. Report the commands, "
            "results, and any checks intentionally skipped."
        )
    return (
        f"Before ending, verify the final changes for `{verify_target}` with the strongest "
        "practical local checks. Report the commands, results, and any checks intentionally skipped."
    )


if __name__ == "__main__":
    raise SystemExit(main())
