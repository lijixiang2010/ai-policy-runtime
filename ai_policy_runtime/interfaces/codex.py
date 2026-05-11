from __future__ import annotations

import argparse
from pathlib import Path

from ai_policy_runtime.adapters.codex import CodexWrapperOptions, run_codex_policy_wrapper
from ai_policy_runtime.interfaces.agent_cli import AgentCliSpec, optional_path, run_agent_cli


SPEC = AgentCliSpec(
    prog="policy-codex",
    description="Resolve Effective Rules, inject AGENTS.md, then invoke Codex.",
    command_option="--codex-command",
    command_default="codex",
    command_help="Codex executable path. Use quotes when the path contains spaces.",
    arg_option="--codex-arg",
    arg_help="Extra argument passed to Codex before the task. Repeat for multiple args.",
    no_exec_help="Only resolve and inject AGENTS.md; do not invoke Codex.",
)


def main() -> None:
    """Policy-aware Codex entry point."""

    run_agent_cli(SPEC, _options_from_args, run_codex_policy_wrapper)


def _options_from_args(args: argparse.Namespace) -> CodexWrapperOptions:
    return CodexWrapperOptions(
        task=args.task,
        root=Path(args.root),
        policy_root=optional_path(args.policy_root),
        skills_dir=args.skills,
        packs_dir=args.packs,
        pack_ids=tuple(args.pack),
        codex_command=(args.codex_command,),
        codex_args=tuple(args.codex_arg),
        execute=not args.no_exec,
        verify_target=args.verify_target,
    )


if __name__ == "__main__":
    main()
