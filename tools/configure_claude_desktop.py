from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


PLUGIN_NAME = "ai-policy-runtime"
MARKETPLACE_NAME = "ai-policy-runtime"
PLUGIN_ID = f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"
DEFAULT_PACK = "cpp.safe_generation"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Configure Claude Desktop / Claude Code for AI Policy Runtime."
    )
    parser.add_argument("--root", default=".", help="Project root to configure.")
    parser.add_argument(
        "--plugin-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="AI Policy Runtime checkout or installable plugin root.",
    )
    parser.add_argument(
        "--scope",
        choices=("local", "project", "user"),
        default="local",
        help="Claude settings scope to update.",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Also call the Claude CLI to add and install the plugin.",
    )
    parser.add_argument(
        "--claude-command",
        default="claude",
        help="Claude CLI executable used with --install.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    plugin_root = Path(args.plugin_root).resolve()
    _validate_plugin_root(plugin_root)

    root.mkdir(parents=True, exist_ok=True)
    policy_path = configure_policy(root, plugin_root)
    settings_path = configure_claude_settings(root, plugin_root, args.scope)

    print(f"Updated policy config: {policy_path}")
    print(f"Updated Claude settings: {settings_path}")
    print(f"Enabled plugin: {PLUGIN_ID}")

    if args.install:
        install_with_claude_cli(args.claude_command, plugin_root, args.scope)

    return 0


def configure_policy(root: Path, plugin_root: Path) -> Path:
    path = root / ".policy" / "config.json"
    config = _read_json_object(path)
    config["enabled"] = True
    config["agents"] = _append_unique(config.get("agents"), "claude")
    if not config.get("packs"):
        config["packs"] = [DEFAULT_PACK]
    if not config.get("policyRoot"):
        config["policyRoot"] = str(plugin_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, config)
    return path


def configure_claude_settings(root: Path, plugin_root: Path, scope: str) -> Path:
    path = _settings_path(root, scope)
    settings = _read_json_object(path)

    marketplaces = settings.setdefault("extraKnownMarketplaces", {})
    if not isinstance(marketplaces, dict):
        raise ValueError("extraKnownMarketplaces must be a JSON object when present.")
    marketplaces[MARKETPLACE_NAME] = {
        "source": {
            "source": "directory",
            "path": str(plugin_root),
        }
    }

    enabled = settings.setdefault("enabledPlugins", {})
    if not isinstance(enabled, dict):
        raise ValueError("enabledPlugins must be a JSON object when present.")
    enabled[PLUGIN_ID] = True

    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, settings)
    return path


def install_with_claude_cli(command: str, plugin_root: Path, scope: str) -> None:
    marketplace_scope = "user" if scope == "user" else "project"
    subprocess.run(
        [
            command,
            "plugin",
            "marketplace",
            "add",
            str(plugin_root),
            "--scope",
            marketplace_scope,
        ],
        check=True,
    )
    subprocess.run(
        [command, "plugin", "install", PLUGIN_ID],
        check=True,
    )


def _settings_path(root: Path, scope: str) -> Path:
    if scope == "user":
        return Path.home() / ".claude" / "settings.json"
    if scope == "project":
        return root / ".claude" / "settings.json"
    return root / ".claude" / "settings.local.json"


def _validate_plugin_root(plugin_root: Path) -> None:
    required = (
        plugin_root / ".claude-plugin" / "plugin.json",
        plugin_root / ".claude-plugin" / "marketplace.json",
        plugin_root / "hooks" / "claude-hooks.json",
    )
    missing = [path for path in required if not path.exists()]
    if missing:
        formatted = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"Claude plugin files are missing:\n{formatted}")


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
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        items = [str(part).strip() for part in value if str(part).strip()]
    else:
        items = []
    if item not in items:
        items.append(item)
    return items


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
