from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import textwrap
from typing import Any


DEFAULT_PACK = "cpp.safe_generation"


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
    print(f"Updated policy config: {policy_path}")
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
    policy = _read_json_object(policy_path)
    plugin_manifest = plugin_root / ".codex-plugin" / "plugin.json"
    hooks_config = plugin_root / "hooks" / "hooks.json"
    return {
        "policy_config": str(policy_path),
        "runtime_enabled": bool(policy.get("enabled", False)),
        "codex_agent_enabled": "codex" in _string_list(policy.get("agents")),
        "packs": _string_list(policy.get("packs")),
        "policy_root": policy.get("policyRoot"),
        "plugin_manifest": str(plugin_manifest),
        "hooks_config": str(hooks_config),
        "plugin_assets_present": plugin_manifest.exists() and hooks_config.exists(),
        "expected_plugin_root": str(plugin_root),
    }


def _validate_plugin_root(plugin_root: Path) -> None:
    required = (
        plugin_root / ".codex-plugin" / "plugin.json",
        plugin_root / "hooks" / "hooks.json",
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
