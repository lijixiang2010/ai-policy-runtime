from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ai_policy_runtime.application.runtime import PolicyRuntime
from ai_policy_runtime.domain.config import RuntimeConfig
from ai_policy_runtime.infrastructure.schema_loader import SchemaLoader
from ai_policy_runtime.services.validator import validate_effective_rules_file


def main() -> None:
    """Command-line entry point for the policy runtime MVP."""

    parser = argparse.ArgumentParser(prog="policy")
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve", help="Generate Effective Rules for a task.")
    _add_runtime_args(resolve)
    resolve.add_argument("task", help="Natural-language task description.")
    resolve.add_argument("--pack", action="append", default=[], help="Pack id to expand.")

    explain = subparsers.add_parser("explain", help="Explain Task Analysis for a task.")
    _add_runtime_args(explain)
    explain.add_argument("task", help="Natural-language task description.")

    validate = subparsers.add_parser("validate", help="Validate Skill DSL files.")
    _add_runtime_args(validate)

    validate_effective = subparsers.add_parser(
        "validate-effective", help="Validate an effective-rules.yaml file."
    )
    validate_effective.add_argument("path", help="Path to effective-rules.yaml or JSON.")

    schema = subparsers.add_parser("schema", help="Print a bundled JSON Schema.")
    schema.add_argument("name", choices=("skill", "pack", "effective-rules"))

    inspect = subparsers.add_parser("inspect", help="Inspect current runtime state.")
    inspect.add_argument("--root", default=".", help="Project root.")

    cache = subparsers.add_parser("cache", help="Inspect or clear runtime caches.")
    cache.add_argument("action", choices=("list", "clear"))
    cache.add_argument("--root", default=".", help="Project root.")

    verify = subparsers.add_parser("verify", help="Verify files against current Effective Rules.")
    verify.add_argument("--root", default=".", help="Project root.")
    verify.add_argument("--target", default=".", help="File or directory to verify.")

    repair_plan = subparsers.add_parser(
        "repair-plan", help="Generate repair instructions from current violations."
    )
    repair_plan.add_argument("--root", default=".", help="Project root.")

    inject = subparsers.add_parser("inject", help="Inject current Effective Prompt into an agent file.")
    inject.add_argument("--root", default=".", help="Project root.")
    inject.add_argument(
        "--target",
        choices=("codex", "claude", "custom"),
        default="codex",
        help="Injection target.",
    )

    run = subparsers.add_parser("run", help="Resolve, inject, and optionally verify a task.")
    _add_runtime_args(run)
    run.add_argument("task", help="Natural-language task description.")
    run.add_argument("--pack", action="append", default=[], help="Pack id to expand.")
    run.add_argument(
        "--agent",
        choices=("codex", "claude", "custom"),
        default="custom",
        help="Agent injection target.",
    )
    run.add_argument("--verify-target", default=None, help="File or directory to verify after injection.")

    args = parser.parse_args()
    output, exit_code = _dispatch(args)
    print(json.dumps(output, indent=2))
    if exit_code:
        raise SystemExit(exit_code)


def _add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=".", help="Target project root.")
    parser.add_argument(
        "--policy-root",
        default=None,
        help="Policy runtime asset root containing skills/ and packs/. Defaults to --root.",
    )
    parser.add_argument("--skills", default="skills", help="Skill directory relative to policy root.")
    parser.add_argument("--packs", default="packs", help="Pack directory relative to policy root.")


def _runtime_from_args(args: argparse.Namespace) -> PolicyRuntime:
    return PolicyRuntime(
        RuntimeConfig.from_values(
            root=Path(args.root),
            policy_root=getattr(args, "policy_root", None),
            skills_dir=getattr(args, "skills", "skills"),
            packs_dir=getattr(args, "packs", "packs"),
        )
    )


def _dispatch(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    return CommandDispatcher().dispatch(args)


class CommandDispatcher:
    """Dispatch parsed CLI arguments to application services."""

    def dispatch(self, args: argparse.Namespace) -> tuple[dict[str, Any], int]:
        handlers = {
            "resolve": self._resolve,
            "explain": self._explain,
            "validate": self._validate,
            "validate-effective": self._validate_effective,
            "schema": self._schema,
            "inspect": self._inspect,
            "cache": self._cache,
            "verify": self._verify,
            "repair-plan": self._repair_plan,
            "inject": self._inject,
            "run": self._run,
        }
        try:
            return handlers[args.command](args)
        except KeyError as exc:
            raise ValueError(f"Unsupported command: {args.command}") from exc

    def _resolve(self, args: argparse.Namespace) -> tuple[dict[str, Any], int]:
        return _runtime_from_args(args).resolve(args.task, tuple(args.pack)).to_dict(), 0

    def _explain(self, args: argparse.Namespace) -> tuple[dict[str, Any], int]:
        return _runtime_from_args(args).explain(args.task).to_dict(), 0

    def _validate(self, args: argparse.Namespace) -> tuple[dict[str, Any], int]:
        diagnostics = _runtime_from_args(args).validate()
        return _diagnostics_output(diagnostics)

    def _validate_effective(
        self, args: argparse.Namespace
    ) -> tuple[dict[str, Any], int]:
        return _diagnostics_output(validate_effective_rules_file(args.path))

    def _schema(self, args: argparse.Namespace) -> tuple[dict[str, Any], int]:
        return SchemaLoader().load(args.name), 0

    def _inspect(self, args: argparse.Namespace) -> tuple[dict[str, Any], int]:
        current = Path(args.root) / ".policy" / "current"
        trace_path = current / "trace.json"
        if not trace_path.exists():
            return {"current": str(current), "exists": False}, 0
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        return {
            "current": str(current),
            "exists": True,
            "task": trace.get("task"),
            "active_skills": trace.get("active_skills", []),
            "task_analysis": trace.get("task_analysis", {}),
            "conflict_count": trace.get("conflict_count", 0),
        }, 0

    def _cache(self, args: argparse.Namespace) -> tuple[dict[str, Any], int]:
        cache_dir = Path(args.root) / ".policy" / "cache" / "semantic-index"
        if args.action == "list":
            files = [
                {"name": item.name, "size": item.stat().st_size}
                for item in sorted(cache_dir.glob("*.json"))
            ] if cache_dir.exists() else []
            return {"cache": str(cache_dir), "entries": files}, 0
        if cache_dir.exists():
            for item in cache_dir.glob("*.json"):
                item.unlink()
        return {"cache": str(cache_dir), "cleared": True}, 0

    def _verify(self, args: argparse.Namespace) -> tuple[dict[str, Any], int]:
        violations = _runtime_from_args(args).verify(Path(args.target))
        return {"violations": [item.to_dict() for item in violations]}, int(bool(violations))

    def _repair_plan(self, args: argparse.Namespace) -> tuple[dict[str, Any], int]:
        instructions = _runtime_from_args(args).repair_plan()
        return {"repair_plan": [item.to_dict() for item in instructions]}, 0

    def _inject(self, args: argparse.Namespace) -> tuple[dict[str, Any], int]:
        return {"injected": str(_runtime_from_args(args).inject(args.target)), "target": args.target}, 0

    def _run(self, args: argparse.Namespace) -> tuple[dict[str, Any], int]:
        result = _runtime_from_args(args).run(
            args.task,
            pack_ids=tuple(args.pack),
            agent=args.agent,
            verify_target=args.verify_target,
        )
        return result.to_dict(), int(bool(result.violations))


def _diagnostics_output(diagnostics: list[Any]) -> tuple[dict[str, Any], int]:
    return {"diagnostics": [item.to_dict() for item in diagnostics]}, int(bool(diagnostics))


if __name__ == "__main__":
    main()
