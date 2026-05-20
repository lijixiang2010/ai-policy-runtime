from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import textwrap
from typing import Any


DEFAULT_PACK = "cpp.safe_generation"
HOOKS_CONFIG_FILE = Path(".codex") / "hooks.json"
PLUGIN_HOOKS_CONFIG_FILE = Path("hooks") / "codex-hooks.json"
CODEX_CONFIG_FILE = Path(".codex") / "config.toml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Configure Codex for AI Policy Runtime.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Common commands:
              Show status:
                python tools/configure_codex.py --root C:\\work\\project --status

              Enable Codex hooks for a workspace:
                python tools/configure_codex.py --root C:\\work\\project --plugin-root D:\\MilesLi\\ai-policy-runtime

              Disable Codex for a workspace:
                python tools/configure_codex.py --root C:\\work\\project --disable
            """
        ),
    )
    parser.add_argument("--root", default=".", help="Project root to configure.")
    parser.add_argument(
        "--plugin-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="AI Policy Runtime checkout or installed package root.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current policy and Codex plugin asset status without modifying files.",
    )
    parser.add_argument(
        "--disable",
        action="store_true",
        help="Disable the Codex agent in this workspace policy config.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    plugin_root = Path(args.plugin_root).resolve()

    if args.status:
        print(json.dumps(status(root, plugin_root), ensure_ascii=False, indent=2))
        return 0

    _validate_plugin_root(plugin_root)
    root.mkdir(parents=True, exist_ok=True)
    policy_path = configure_policy(root, plugin_root, enabled=not args.disable)
    hooks_path = configure_codex_hooks(root, plugin_root, enabled=not args.disable)
    config_path = configure_codex_config(root, enabled=not args.disable)
    print(f"Updated policy config: {policy_path}")
    print(f"Updated Codex hooks: {hooks_path}")
    print(f"Updated Codex config: {config_path}")
    print(f"{'Enabled' if not args.disable else 'Disabled'} Codex agent: codex")
    return 0


def configure_policy(root: Path, plugin_root: Path, *, enabled: bool = True) -> Path:
    path = root / ".policy" / "config.json"
    config = _read_json_object(path)
    if enabled:
        config["enabled"] = True
        config["agents"] = _append_unique(config.get("agents"), "codex")
        if not config.get("packs"):
            config["packs"] = [DEFAULT_PACK]
        if not config.get("policyRoot"):
            config["policyRoot"] = str(plugin_root)
    else:
        agents = [agent for agent in _string_list(config.get("agents")) if agent != "codex"]
        config["agents"] = agents
        if not agents:
            config["enabled"] = False
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, config)
    return path


def status(root: Path, plugin_root: Path) -> dict[str, Any]:
    """Return current project policy and Codex plugin asset status."""

    policy_path = root / ".policy" / "config.json"
    project_hooks = root / HOOKS_CONFIG_FILE
    codex_config = root / CODEX_CONFIG_FILE
    policy = _read_json_object(policy_path)
    plugin_manifest = plugin_root / ".codex-plugin" / "plugin.json"
    hooks_config = plugin_root / PLUGIN_HOOKS_CONFIG_FILE
    project_hooks_config = _read_json_object(project_hooks)
    return {
        "policy_config": str(policy_path),
        "codex_config": str(codex_config),
        "codex_hooks_config": str(project_hooks),
        "runtime_enabled": bool(policy.get("enabled", False)),
        "codex_agent_enabled": "codex" in _string_list(policy.get("agents")),
        "packs": _string_list(policy.get("packs")),
        "policy_root": policy.get("policyRoot"),
        "codex_hooks_enabled": _codex_hooks_enabled(codex_config),
        "project_hooks_present": project_hooks.exists(),
        "project_hooks_configured": _project_hooks_configured(project_hooks_config),
        "plugin_manifest": str(plugin_manifest),
        "hooks_config": str(hooks_config),
        "plugin_assets_present": plugin_manifest.exists() and hooks_config.exists(),
        "expected_plugin_root": str(plugin_root),
    }


def configure_codex_hooks(root: Path, plugin_root: Path, *, enabled: bool = True) -> Path:
    """Write project-local Codex hook commands for bare `codex` CLI usage."""

    path = root / HOOKS_CONFIG_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    config = _read_json_object(path)
    hooks = config.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"Codex hooks config must contain a JSON object at hooks: {path}")

    user_prompt_hook = _codex_hook_entry(
        plugin_root,
        "codex-user-prompt-submit",
        "Generating Effective Rules",
    )
    stop_hook = _codex_hook_entry(
        plugin_root,
        "codex-stop-refinement",
        "Checking post-task refinement",
    )

    if not enabled:
        _remove_event_hook(hooks, "UserPromptSubmit", user_prompt_hook)
        _remove_event_hook(hooks, "Stop", stop_hook)
        _write_json(path, config)
        return path

    _upsert_event_hook(hooks, "UserPromptSubmit", user_prompt_hook)
    _upsert_event_hook(hooks, "Stop", stop_hook)
    _write_json(path, config)
    return path


def _codex_hook_entry(plugin_root: Path, hook_name: str, status_message: str) -> dict[str, object]:
    node_command = _node_command()
    hook_runner = plugin_root / "bin" / "ai-policy-hook.js"
    return {
        "hooks": [
            {
                "type": "command",
                "command": _shell_command(node_command, hook_runner, hook_name),
                "timeout": 30,
                "statusMessage": status_message,
            }
        ]
    }


def _upsert_event_hook(hooks: dict[str, object], event: str, entry: dict[str, object]) -> None:
    entries = hooks.setdefault(event, [])
    if not isinstance(entries, list):
        raise ValueError(f"Codex hook event must contain a list: {event}")
    _remove_ai_policy_entries(entries)
    entries.append(entry)


def _remove_event_hook(hooks: dict[str, object], event: str, entry: dict[str, object]) -> None:
    entries = hooks.get(event)
    if entries is None:
        return
    if not isinstance(entries, list):
        raise ValueError(f"Codex hook event must contain a list: {event}")
    _remove_ai_policy_entries(entries)
    if not entries:
        hooks.pop(event, None)


def _remove_ai_policy_entries(entries: list[object]) -> None:
    entries[:] = [entry for entry in entries if not _is_ai_policy_hook_entry(entry)]


def _is_ai_policy_hook_entry(entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    hook_items = entry.get("hooks")
    if not isinstance(hook_items, list):
        return False
    for item in hook_items:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command", ""))
        if "ai-policy-hook.js" in command:
            return True
    return False


def configure_codex_config(root: Path, *, enabled: bool = True) -> Path:
    """Ensure the project Codex config enables hook support for bare CLI sessions."""

    path = root / CODEX_CONFIG_FILE
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    updated = _set_toml_bool(
        original,
        "features",
        "hooks",
        enabled,
        remove_keys=("codex_hooks",),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    return path


def _validate_plugin_root(plugin_root: Path) -> None:
    required = (
        plugin_root / ".codex-plugin" / "plugin.json",
        plugin_root / PLUGIN_HOOKS_CONFIG_FILE,
        plugin_root / "bin" / "ai-policy-hook.js",
    )
    missing = [path for path in required if not path.exists()]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"Codex plugin files are missing:\n{formatted}")


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _codex_hooks_enabled(path: Path) -> bool:
    if not path.exists():
        return False
    return _toml_bool(path.read_text(encoding="utf-8"), "features", "hooks")


def _project_hooks_configured(config: dict[str, Any]) -> bool:
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return False
    return _event_has_ai_policy_hook(hooks, "UserPromptSubmit") and _event_has_ai_policy_hook(
        hooks,
        "Stop",
    )


def _event_has_ai_policy_hook(hooks: dict[str, Any], event: str) -> bool:
    entries = hooks.get(event)
    if not isinstance(entries, list):
        return False
    return any(_is_ai_policy_hook_entry(entry) for entry in entries)


def _node_command() -> str:
    if os.environ.get("AI_POLICY_NODE"):
        return os.environ["AI_POLICY_NODE"]
    return "node"


def _shell_command(command: str, script: Path, hook_name: str) -> str:
    return " ".join((_quote_shell(command), _quote_shell(str(script)), _quote_shell(hook_name)))


def _quote_shell(value: str) -> str:
    escaped = value.replace('"', '\\"')
    if any(character.isspace() for character in escaped) or "\\" in escaped or ":" in escaped:
        return f'"{escaped}"'
    return escaped


def _set_toml_bool(
    text: str,
    section: str,
    key: str,
    value: bool,
    *,
    remove_keys: tuple[str, ...] = (),
) -> str:
    lines = text.splitlines()
    target = f"{key} = {'true' if value else 'false'}"
    section_header = f"[{section}]"
    in_section = False
    section_found = False
    key_written = False
    output: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section and not key_written:
                output.append(target)
                key_written = True
            in_section = stripped == section_header
            section_found = section_found or in_section
            output.append(line)
            continue
        if in_section and any(
            stripped.startswith(f"{remove_key} ") and "=" in stripped
            for remove_key in remove_keys
        ):
            continue
        if in_section and stripped.startswith(f"{key} ") and "=" in stripped:
            output.append(target)
            key_written = True
            continue
        output.append(line)

    if not section_found:
        if output and output[-1].strip():
            output.append("")
        output.extend([section_header, target])
    elif in_section and not key_written:
        output.append(target)

    return "\n".join(output).rstrip() + "\n"


def _toml_bool(text: str, section: str, key: str) -> bool:
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == f"[{section}]"
            continue
        if in_section and stripped.startswith(f"{key} ") and "=" in stripped:
            value = stripped.split("=", 1)[1].strip().split("#", 1)[0].strip().lower()
            return value == "true"
    return False


def _append_unique(value: Any, item: str) -> list[str]:
    items = _string_list(value)
    if item not in items:
        items.append(item)
    return items


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
