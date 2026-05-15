from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ai_policy_runtime.adapters.agent import POST_REFINE_PACK_ID


class JsonResult(Protocol):
    """Protocol for CLI results that can be serialized and return an exit code."""

    exit_code: int

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""


@dataclass(frozen=True)
class AgentCliSpec:
    """Command-line differences between policy-aware agent adapters."""

    prog: str
    description: str
    command_option: str
    command_default: str
    command_help: str
    arg_option: str
    arg_help: str
    no_exec_help: str


def run_agent_cli(
    spec: AgentCliSpec,
    make_options: Callable[[argparse.Namespace], object],
    run_wrapper: Callable[[object], JsonResult],
) -> None:
    """Parse shared agent CLI options and run the configured wrapper."""

    parser = _build_parser(spec)
    args = parser.parse_args()
    result = run_wrapper(make_options(args))
    print(json.dumps(result.to_dict(), indent=2))
    if result.exit_code:
        raise SystemExit(result.exit_code)


def _build_parser(spec: AgentCliSpec) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=spec.prog, description=spec.description)
    parser.add_argument("task", help="Natural-language task description.")
    parser.add_argument("--root", default=".", help="Target project root.")
    parser.add_argument(
        "--policy-root",
        default=None,
        help="Policy runtime asset root containing skills/ and packs/. Defaults to --root.",
    )
    parser.add_argument("--skills", default="skills", help="Skill directory relative to policy root.")
    parser.add_argument("--packs", default="packs", help="Pack directory relative to policy root.")
    parser.add_argument("--pack", action="append", default=[], help="Pack id to expand.")
    parser.add_argument(
        spec.command_option,
        default=spec.command_default,
        help=spec.command_help,
    )
    parser.add_argument(
        spec.arg_option,
        action="append",
        default=[],
        help=spec.arg_help,
    )
    parser.add_argument("--no-exec", action="store_true", help=spec.no_exec_help)
    parser.add_argument("--verify-target", default=None, help="File or directory to verify after agent.")
    parser.add_argument(
        "--post-refine",
        action="store_true",
        help="Run a standard post-task refinement pass after a successful agent command.",
    )
    parser.add_argument(
        "--post-refine-mode",
        choices=("off", "light", "standard", "strict"),
        default="off",
        help=(
            "Post-task refinement mode. off disables the pass; light only refreshes refinement "
            "context; standard and strict run a second agent pass after success."
        ),
    )
    parser.add_argument(
        "--post-refine-pack",
        action="append",
        default=[],
        help=f"Pack id used for the post-task refinement pass. Defaults to {POST_REFINE_PACK_ID}.",
    )
    return parser


def optional_path(value: str | None) -> Path | None:
    """Convert an optional path string into a Path."""

    return Path(value) if value else None


def post_refine_mode(args: argparse.Namespace) -> str:
    """Return the effective post-refinement mode from shared CLI args."""

    if args.post_refine and args.post_refine_mode == "off":
        return "standard"
    return str(args.post_refine_mode)


def post_refine_packs(args: argparse.Namespace) -> tuple[str, ...]:
    """Return post-refinement packs, including the default when none are provided."""

    packs = tuple(args.post_refine_pack)
    return packs if packs else (POST_REFINE_PACK_ID,)
