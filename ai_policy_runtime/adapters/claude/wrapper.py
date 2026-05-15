from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ai_policy_runtime.adapters.agent import (
    AgentWrapperOptions,
    AgentWrapperResult,
    POST_REFINE_PACK_ID,
    build_agent_command,
    run_policy_agent_wrapper,
)


@dataclass(frozen=True)
class ClaudeWrapperOptions:
    """Options for the Claude Code policy wrapper."""

    task: str
    root: Path = Path(".")
    policy_root: Path | None = None
    skills_dir: str = "skills"
    packs_dir: str = "packs"
    pack_ids: tuple[str, ...] = ()
    claude_command: tuple[str, ...] = ("claude",)
    claude_args: tuple[str, ...] = ()
    execute: bool = True
    verify_target: str | Path | None = None
    post_refine_mode: str = "off"
    post_refine_pack_ids: tuple[str, ...] = (POST_REFINE_PACK_ID,)

    def to_agent_options(self) -> AgentWrapperOptions:
        """Return generic wrapper options for the Claude Code adapter."""

        return AgentWrapperOptions(
            task=self.task,
            agent="claude",
            root=self.root,
            policy_root=self.policy_root,
            skills_dir=self.skills_dir,
            packs_dir=self.packs_dir,
            pack_ids=self.pack_ids,
            command=self.claude_command,
            command_args=self.claude_args,
            execute=self.execute,
            verify_target=self.verify_target,
            post_refine_mode=self.post_refine_mode,
            post_refine_pack_ids=self.post_refine_pack_ids,
        )


ClaudeWrapperResult = AgentWrapperResult


def run_claude_policy_wrapper(options: ClaudeWrapperOptions) -> ClaudeWrapperResult:
    """Resolve task policy, inject CLAUDE.md, then optionally invoke Claude Code."""

    return run_policy_agent_wrapper(options.to_agent_options())


def _build_claude_command(
    claude_command: Sequence[str],
    claude_args: Sequence[str],
    task: str,
) -> tuple[str, ...]:
    return build_agent_command(claude_command, claude_args, task)
