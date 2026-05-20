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
    _current_agent,
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
    """Return the agent Stop-hook response for optional refinement continuation."""

    if bool(payload.get("stop_hook_active")):
        return {"continue": True}

    project_root = Path(payload.get("cwd") or ".").resolve()
    config = ProjectHookConfig.load(project_root)
    if not config.enabled_for(_current_agent()) or config.post_refine_mode == "off":
        return {"continue": True}
    config.apply_environment()
    config.ensure_semantic_dependencies(project_root)

    prompt = _original_prompt(project_root, payload)
    if prompt is None:
        return {"continue": True}
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


def _original_prompt(project_root: Path, payload: dict[str, object]) -> str | None:
    state = _load_turn_state(project_root)
    return _state_prompt_for_turn(state, payload)


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
    if state.get("effective_rules_generated") is not True:
        return None
    if not _same_optional_id(state.get("turn_id"), payload.get("turn_id")):
        return None
    if not _same_optional_id(state.get("session_id"), payload.get("session_id")):
        return None
    prompt = state.get("prompt")
    return str(prompt).strip() if prompt else None


def _same_optional_id(state_value: object, payload_value: object) -> bool:
    """Return whether a stored turn/session id can be trusted for this payload."""

    if state_value is None:
        return True
    return payload_value is not None and state_value == payload_value


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
