from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Any


PLUGIN_NAME = "ai-policy-runtime"
MARKETPLACE_NAME = "ai-policy-runtime"
PLUGIN_ID = f"{PLUGIN_NAME}@{MARKETPLACE_NAME}"
DEFAULT_POST_REFINE_PACK = "generic.production_refinement"
POST_REFINE_MODES = ("off", "light", "standard", "strict")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Configure Claude Desktop / Claude Code for AI Policy Runtime.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Common commands:
              Show status:
                python tools/configure_claude_desktop.py --root C:\\work\\project --status

              Enable Claude Desktop plugin for a workspace:
                python tools/configure_claude_desktop.py --root C:\\work\\project --plugin-root D:\\MilesLi\\ai-policy-runtime

              Enable post-refinement:
                python tools/configure_claude_desktop.py --root C:\\work\\project --post-refine standard

              Disable post-refinement:
                python tools/configure_claude_desktop.py --root C:\\work\\project --post-refine off

              Disable the runtime and plugin:
                python tools/configure_claude_desktop.py --root C:\\work\\project --disable

              Toggle only the Claude plugin setting:
                python tools/configure_claude_desktop.py --root C:\\work\\project --enable-plugin
                python tools/configure_claude_desktop.py --root C:\\work\\project --disable-plugin
            """
        ),
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
        "--status",
        action="store_true",
        help="Print current policy and Claude plugin status without modifying files.",
    )
    parser.add_argument(
        "--disable",
        action="store_true",
        help="Disable the policy runtime and Claude plugin for this scope.",
    )
    parser.add_argument(
        "--enable-plugin",
        action="store_true",
        help="Enable only the Claude plugin setting without changing policy runtime options.",
    )
    parser.add_argument(
        "--disable-plugin",
        action="store_true",
        help="Disable only the Claude plugin setting without changing policy runtime options.",
    )
    parser.add_argument(
        "--claude-command",
        default="claude",
        help="Claude CLI executable used with --install.",
    )
    parser.add_argument(
        "--post-refine",
        choices=POST_REFINE_MODES,
        default=None,
        help=(
            "Configure Stop-hook post-refinement mode. Use standard to enable "
            "one extra refinement pass, or off to disable."
        ),
    )
    parser.add_argument(
        "--post-refine-pack",
        action="append",
        default=[],
        help=(
            "Pack id used for the post-refinement continuation. Repeat for "
            f"multiple packs. Defaults to {DEFAULT_POST_REFINE_PACK} when "
            "--post-refine is enabled."
        ),
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    plugin_root = Path(args.plugin_root).resolve()

    if args.status:
        print(json.dumps(status(root, plugin_root, args.scope), ensure_ascii=False, indent=2))
        return 0

    _validate_plugin_root(plugin_root)
    root.mkdir(parents=True, exist_ok=True)

    if args.disable_plugin and args.enable_plugin:
        parser.error("--enable-plugin and --disable-plugin cannot be used together.")
    if args.disable and (args.enable_plugin or args.disable_plugin):
        parser.error("--disable cannot be combined with plugin-only toggles.")
    if args.post_refine_pack and args.post_refine is None:
        parser.error("--post-refine-pack requires --post-refine.")
    if args.post_refine == "off" and args.post_refine_pack:
        parser.error("--post-refine-pack cannot be used with --post-refine off.")

    policy_exists = (root / ".policy" / "config.json").exists()
    plugin_toggle = args.enable_plugin or args.disable_plugin
    settings_only = plugin_toggle and args.post_refine is None and not args.install
    post_refine_update_only = (
        args.post_refine is not None
        and not args.disable
        and not args.install
        and not plugin_toggle
        and (policy_exists or args.post_refine == "off")
    )
    plugin_enabled = False if args.disable_plugin or args.disable else True

    policy_path = None
    if not settings_only:
        policy_path = configure_policy(
            root,
            plugin_root,
            enabled=not args.disable,
            post_refine=args.post_refine,
            post_refine_packs=tuple(args.post_refine_pack),
            configure_runtime=not post_refine_update_only,
        )
    settings_path = None
    if not post_refine_update_only:
        settings_path = configure_claude_settings(
            root,
            plugin_root,
            args.scope,
            enabled=plugin_enabled,
        )

    if policy_path is not None:
        print(f"Updated policy config: {policy_path}")
    if settings_path is not None:
        print(f"Updated Claude settings: {settings_path}")
        print(f"{'Enabled' if plugin_enabled else 'Disabled'} plugin: {PLUGIN_ID}")

    if args.install:
        install_with_claude_cli(args.claude_command, plugin_root, args.scope)

    return 0


def configure_policy(
    root: Path,
    plugin_root: Path,
    *,
    enabled: bool = True,
    post_refine: str | None = None,
    post_refine_packs: tuple[str, ...] = (),
    configure_runtime: bool = True,
) -> Path:
    path = root / ".policy" / "config.json"
    config = _read_json_object(path)
    if configure_runtime:
        config["enabled"] = enabled
        if enabled:
            config["agents"] = _append_unique(config.get("agents"), "claude")
            config.setdefault("packs", [])
            config["policyRoot"] = str(plugin_root)
            _ensure_git_commit_style(config)
        else:
            config["agents"] = [
                agent for agent in _string_list(config.get("agents")) if agent != "claude"
            ]
    if post_refine is not None:
        config["postRefine"] = post_refine
        if post_refine != "off":
            config["postRefinePacks"] = (
                list(post_refine_packs) if post_refine_packs else [DEFAULT_POST_REFINE_PACK]
            )
        else:
            config["postRefinePacks"] = []
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, config)
    return path


def configure_claude_settings(
    root: Path,
    plugin_root: Path,
    scope: str,
    *,
    enabled: bool = True,
) -> Path:
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

    enabled_plugins = settings.setdefault("enabledPlugins", {})
    if not isinstance(enabled_plugins, dict):
        raise ValueError("enabledPlugins must be a JSON object when present.")
    enabled_plugins[PLUGIN_ID] = bool(enabled)

    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, settings)
    return path


def status(root: Path, plugin_root: Path, scope: str) -> dict[str, Any]:
    """Return current project policy and Claude plugin status."""

    policy_path = root / ".policy" / "config.json"
    settings_path = _settings_path(root, scope)
    policy = _read_json_object(policy_path)
    settings = _read_json_object(settings_path)
    enabled_plugins = settings.get("enabledPlugins", {})
    marketplaces = settings.get("extraKnownMarketplaces", {})
    marketplace_root = _marketplace_runtime_root(settings)
    policy_root = policy.get("policyRoot")
    return {
        "policy_config": str(policy_path),
        "claude_settings": str(settings_path),
        "runtime_enabled": bool(policy.get("enabled", False)),
        "claude_agent_enabled": "claude" in _string_list(policy.get("agents")),
        "packs": _string_list(policy.get("packs")),
        "policy_root": policy_root,
        "policy_root_matches_expected": _same_path(policy_root, plugin_root),
        "git_commit_style": _git_commit_style(policy),
        "post_refine": policy.get("postRefine", "off"),
        "post_refine_packs": _string_list(policy.get("postRefinePacks")),
        "plugin_id": PLUGIN_ID,
        "plugin_enabled": (
            isinstance(enabled_plugins, dict)
            and bool(enabled_plugins.get(PLUGIN_ID, False))
        ),
        "marketplace_registered": (
            isinstance(marketplaces, dict)
            and MARKETPLACE_NAME in marketplaces
        ),
        "marketplace_root": marketplace_root,
        "marketplace_root_matches_expected": _same_path(marketplace_root, plugin_root),
        "expected_plugin_root": str(plugin_root),
    }


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
        plugin_root / "hooks" / "hooks.json",
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


def _ensure_git_commit_style(config: dict[str, Any]) -> None:
    git_config = config.setdefault("git", {})
    if isinstance(git_config, dict):
        git_config.setdefault("commitStyle", "auto")


def _git_commit_style(config: dict[str, Any]) -> str:
    git_config = config.get("git")
    if isinstance(git_config, dict):
        return str(git_config.get("commitStyle") or "auto")
    return str(config.get("gitCommitStyle") or "auto")


def _marketplace_runtime_root(settings: dict[str, Any]) -> str | None:
    marketplaces = settings.get("extraKnownMarketplaces")
    if not isinstance(marketplaces, dict):
        return None
    marketplace = marketplaces.get(MARKETPLACE_NAME)
    if not isinstance(marketplace, dict):
        return None
    source = marketplace.get("source")
    if not isinstance(source, dict):
        return None
    if source.get("source") != "directory":
        return None
    path = source.get("path")
    return str(path) if path else None


def _same_path(left: Any, right: Path) -> bool:
    if not left:
        return False
    try:
        left_path = Path(str(left)).resolve()
    except OSError:
        return False
    if sys.platform == "win32":
        return str(left_path).lower() == str(right.resolve()).lower()
    return left_path == right.resolve()


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
