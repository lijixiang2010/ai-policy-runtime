from __future__ import annotations

import argparse
from pathlib import Path

from ai_policy_runtime.adapters.claude import ClaudeWrapperOptions, run_claude_policy_wrapper
from ai_policy_runtime.interfaces.agent_cli import (
    AgentCliSpec,
    optional_path,
    post_refine_mode,
    post_refine_packs,
    run_agent_cli,
)


SPEC = AgentCliSpec(
    prog="policy-claude",
    description="Resolve Effective Rules, inject CLAUDE.md, then invoke Claude Code.",
    command_option="--claude-command",
    command_default="claude",
    command_help="Claude executable path. Use quotes when the path contains spaces.",
    arg_option="--claude-arg",
    arg_help="Extra argument passed to Claude before the task. Repeat for multiple args.",
    no_exec_help="Only resolve and inject CLAUDE.md; do not invoke Claude.",
)


def main() -> None:
    """Policy-aware Claude Code entry point."""

    run_agent_cli(SPEC, _options_from_args, run_claude_policy_wrapper)


def _options_from_args(args: argparse.Namespace) -> ClaudeWrapperOptions:
    return ClaudeWrapperOptions(
        task=args.task,
        root=Path(args.root),
        policy_root=optional_path(args.policy_root),
        skills_dir=args.skills,
        packs_dir=args.packs,
        pack_ids=tuple(args.pack),
        claude_command=(args.claude_command,),
        claude_args=tuple(args.claude_arg),
        execute=not args.no_exec,
        verify_target=args.verify_target,
        post_refine_mode=post_refine_mode(args),
        post_refine_pack_ids=post_refine_packs(args),
    )


if __name__ == "__main__":
    main()
