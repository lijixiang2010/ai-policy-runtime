from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ai_policy_runtime.application.runtime import PolicyRuntime
from ai_policy_runtime.domain.config import RuntimeConfig


@dataclass(frozen=True)
class AgentWrapperOptions:
    """Options shared by policy-aware agent wrappers."""

    task: str
    agent: str
    root: Path = Path(".")
    policy_root: Path | None = None
    skills_dir: str = "skills"
    packs_dir: str = "packs"
    pack_ids: tuple[str, ...] = ()
    command: tuple[str, ...] = ()
    command_args: tuple[str, ...] = ()
    execute: bool = True
    verify_target: str | Path | None = None


@dataclass(frozen=True)
class AgentWrapperResult:
    """Result of resolving policy, injecting agent context, and optionally running an agent."""

    current: Path
    injected: Path
    command: tuple[str, ...]
    executed: bool
    exit_code: int
    verified: bool
    violations: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "current": str(self.current),
            "injected": str(self.injected),
            "command": list(self.command),
            "executed": self.executed,
            "exit_code": self.exit_code,
            "verified": self.verified,
            "violations": list(self.violations),
        }


class PolicyAgentWrapper:
    """Run the shared policy-enhancement flow for a command-line coding agent."""

    def __init__(self, options: AgentWrapperOptions) -> None:
        self.options = options

    def run(self) -> AgentWrapperResult:
        runtime = self._runtime()
        resolved = runtime.resolve(self.options.task, self.options.pack_ids)
        injected = runtime.inject(self.options.agent)
        command = build_agent_command(
            self.options.command,
            self.options.command_args,
            self.options.task,
        )
        exit_code, executed = self._maybe_execute(command)
        violations = self._maybe_verify(runtime, exit_code)
        if violations and exit_code == 0:
            exit_code = 1
        return AgentWrapperResult(
            current=resolved.current,
            injected=injected,
            command=command,
            executed=executed,
            exit_code=exit_code,
            verified=self.options.verify_target is not None,
            violations=violations,
        )

    def _runtime(self) -> PolicyRuntime:
        return PolicyRuntime(
            RuntimeConfig.from_values(
                root=self.options.root,
                policy_root=self.options.policy_root,
                skills_dir=self.options.skills_dir,
                packs_dir=self.options.packs_dir,
            )
        )

    def _maybe_execute(self, command: tuple[str, ...]) -> tuple[int, bool]:
        if not self.options.execute:
            return 0, False
        try:
            completed = subprocess.run(command, cwd=self.options.root, check=False)
            return completed.returncode, True
        except FileNotFoundError:
            return 127, True

    def _maybe_verify(
        self,
        runtime: PolicyRuntime,
        exit_code: int,
    ) -> tuple[dict[str, object], ...]:
        if self.options.verify_target is None:
            return ()
        return tuple(item.to_dict() for item in runtime.verify(self.options.verify_target))


def build_agent_command(
    command: Sequence[str],
    command_args: Sequence[str],
    task: str,
) -> tuple[str, ...]:
    """Build an agent command with the user task as the final argument."""

    if not command:
        raise ValueError("agent command must not be empty")
    return (*command, *command_args, task)


def run_policy_agent_wrapper(options: AgentWrapperOptions) -> AgentWrapperResult:
    """Resolve policy, inject context, and optionally run the configured agent."""

    return PolicyAgentWrapper(options).run()
