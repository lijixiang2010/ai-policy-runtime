from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    payload = _read_payload()
    prompt = str(payload.get("prompt", ""))
    if not prompt.strip():
        return 0

    project_root = Path(payload.get("cwd") or ".").resolve()
    policy_root = Path(os.environ.get("AI_POLICY_ROOT", PLUGIN_ROOT)).resolve()

    try:
        additional_context = _resolve_effective_prompt(prompt, project_root, policy_root)
    except Exception as exc:
        additional_context = (
            "AI Policy Runtime hook could not generate Effective Rules for this turn. "
            f"Error: {type(exc).__name__}: {exc}"
        )

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": additional_context,
                }
            },
            ensure_ascii=False,
        )
    )
    return 0


def _read_payload() -> dict[str, object]:
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {}
    return data


def _resolve_effective_prompt(prompt: str, project_root: Path, policy_root: Path) -> str:
    _prepare_imports()

    from ai_policy_runtime import PolicyRuntime, RuntimeConfig

    runtime = PolicyRuntime(
        RuntimeConfig.from_values(
            root=project_root,
            policy_root=policy_root,
        )
    )
    result = runtime.resolve(prompt, _configured_packs())
    return (result.current / "effective-prompt.md").read_text(encoding="utf-8")


def _prepare_imports() -> None:
    if str(PLUGIN_ROOT) not in sys.path:
        sys.path.insert(0, str(PLUGIN_ROOT))

    try:
        import ai_policy_runtime  # noqa: F401
        import jsonschema  # noqa: F401
        import yaml  # noqa: F401
    except ModuleNotFoundError:
        _bootstrap_package()
        import ai_policy_runtime  # noqa: F401
        import jsonschema  # noqa: F401
        import yaml  # noqa: F401


def _bootstrap_package() -> None:
    if os.environ.get("AI_POLICY_AUTO_INSTALL", "1") in {"0", "false", "False"}:
        raise RuntimeError(
            "Python dependencies are missing and AI_POLICY_AUTO_INSTALL is disabled."
        )
    if not (PLUGIN_ROOT / "pyproject.toml").exists():
        raise RuntimeError(f"pyproject.toml not found under plugin root: {PLUGIN_ROOT}")

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "-e",
        str(PLUGIN_ROOT),
    ]
    subprocess.run(
        command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def _configured_packs() -> tuple[str, ...]:
    raw = os.environ.get("AI_POLICY_PACKS", "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


if __name__ == "__main__":
    raise SystemExit(main())
