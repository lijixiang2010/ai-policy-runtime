from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ai_policy_runtime.adapters.agent import (
    AgentWrapperOptions,
    AgentWrapperResult,
    build_agent_command,
    run_policy_agent_wrapper,
)


@dataclass(frozen=True)
class CodexWrapperOptions:
    """Options for the Codex policy wrapper."""

    task: str
    root: Path = Path(".")
    policy_root: Path | None = None
    skills_dir: str = "skills"
    packs_dir: str = "packs"
    pack_ids: tuple[str, ...] = ()
    codex_command: tuple[str, ...] = ("codex",)
    codex_args: tuple[str, ...] = ()
    execute: bool = True
    verify_target: str | Path | None = None

    def to_agent_options(self) -> AgentWrapperOptions:
        """Return generic wrapper options for the Codex adapter."""

        return AgentWrapperOptions(
            task=self.task,
            agent="codex",
            root=self.root,
            policy_root=self.policy_root,
            skills_dir=self.skills_dir,
            packs_dir=self.packs_dir,
            pack_ids=self.pack_ids,
            command=self.codex_command,
            command_args=self.codex_args,
            execute=self.execute,
            verify_target=self.verify_target,
        )


CodexWrapperResult = AgentWrapperResult


def run_codex_policy_wrapper(options: CodexWrapperOptions) -> CodexWrapperResult:
    """Resolve task policy, inject AGENTS.md, then optionally invoke Codex."""

    return run_policy_agent_wrapper(options.to_agent_options())


def _build_codex_command(
    codex_command: Sequence[str],
    codex_args: Sequence[str],
    task: str,
) -> tuple[str, ...]:
    return build_agent_command(codex_command, codex_args, task)
