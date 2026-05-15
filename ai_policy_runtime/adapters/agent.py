from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ai_policy_runtime.application.runtime import PolicyRuntime
from ai_policy_runtime.domain.config import RuntimeConfig


POST_REFINE_PACK_ID = "cpp.production_refinement"
POST_REFINE_MODES = ("off", "light", "standard", "strict")


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
    post_refine_mode: str = "off"
    post_refine_pack_ids: tuple[str, ...] = (POST_REFINE_PACK_ID,)


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
    refinement: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "current": str(self.current),
            "injected": str(self.injected),
            "command": list(self.command),
            "executed": self.executed,
            "exit_code": self.exit_code,
            "verified": self.verified,
            "violations": list(self.violations),
            "refinement": self.refinement,
        }


class PolicyAgentWrapper:
    """Run the shared policy-enhancement flow for a command-line coding agent."""

    def __init__(self, options: AgentWrapperOptions) -> None:
        self.options = options

    def run(self) -> AgentWrapperResult:
        _validate_post_refine_mode(self.options.post_refine_mode)
        runtime = self._runtime()
        resolved = runtime.resolve(self.options.task, self.options.pack_ids)
        injected = runtime.inject(self.options.agent)
        command = build_agent_command(
            self.options.command,
            self.options.command_args,
            self.options.task,
        )
        exit_code, executed = self._maybe_execute(command)
        refinement = self._maybe_post_refine(runtime, exit_code)
        if refinement and refinement.get("executed") and refinement.get("exit_code") not in (0, None):
            exit_code = int(refinement["exit_code"])
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
            refinement=refinement,
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

    def _maybe_post_refine(
        self,
        runtime: PolicyRuntime,
        first_exit_code: int,
    ) -> dict[str, object] | None:
        mode = self.options.post_refine_mode
        if mode == "off":
            return None

        if first_exit_code != 0:
            return {
                "mode": mode,
                "executed": False,
                "skipped_reason": "initial agent command failed",
            }

        task = build_post_refinement_task(self.options.task, mode)
        pack_ids = merge_pack_ids(self.options.pack_ids, self.options.post_refine_pack_ids)
        resolved = runtime.resolve(task, pack_ids)
        injected = runtime.inject(self.options.agent)
        command = build_agent_command(
            self.options.command,
            self.options.command_args,
            task,
        )
        should_execute = self.options.execute and mode in ("standard", "strict")
        if should_execute:
            exit_code, executed = self._maybe_execute(command)
        else:
            exit_code, executed = 0, False

        return {
            "mode": mode,
            "task": task,
            "pack_ids": list(pack_ids),
            "current": str(resolved.current),
            "injected": str(injected),
            "command": list(command),
            "executed": executed,
            "exit_code": exit_code,
        }


def build_agent_command(
    command: Sequence[str],
    command_args: Sequence[str],
    task: str,
) -> tuple[str, ...]:
    """Build an agent command with the user task as the final argument."""

    if not command:
        raise ValueError("agent command must not be empty")
    return (*command, *command_args, task)


def build_post_refinement_task(task: str, mode: str = "standard") -> str:
    """Build the second-pass task used to refine completed implementation work."""

    _validate_post_refine_mode(mode)
    strict_note = (
        "\nFor strict mode, be especially conservative about scope and treat relevant "
        "local checks as part of completion."
        if mode == "strict"
        else ""
    )
    return (
        "Post-implementation refinement pass for the previous task:\n\n"
        f"{task}\n\n"
        f"Mode: {mode}.\n"
        "Preserve observable behavior. Review the code you just changed and make only "
        "proportionate production-quality refinements:\n"
        "- remove accidental complexity while keeping useful domain, safety, and performance complexity\n"
        "- group scattered related state, helper functions, and behavior into coherent components\n"
        "- extract duplicated structure or variation points only when it reduces net complexity\n"
        "- prefer clearer language-native syntax when it preserves correctness and maintainability\n"
        "- reduce user-facing steps and API friction\n"
        "- keep ownership, lifetime, bounds, type-safety, and standard-availability constraints explicit\n"
        "- run relevant local checks when practical and report commands, results, and skipped checks\n\n"
        "Do not broaden scope or rewrite unrelated code. If a larger redesign is needed, report it "
        "instead of doing it."
        f"{strict_note}"
    )


def merge_pack_ids(primary: Sequence[str], secondary: Sequence[str]) -> tuple[str, ...]:
    """Merge pack ids while preserving order and removing duplicates."""

    merged: list[str] = []
    for pack_id in (*primary, *secondary):
        if pack_id and pack_id not in merged:
            merged.append(pack_id)
    return tuple(merged)


def _validate_post_refine_mode(mode: str) -> None:
    if mode not in POST_REFINE_MODES:
        allowed = ", ".join(POST_REFINE_MODES)
        raise ValueError(f"post_refine_mode must be one of: {allowed}")


def run_policy_agent_wrapper(options: AgentWrapperOptions) -> AgentWrapperResult:
    """Resolve policy, inject context, and optionally run the configured agent."""

    return PolicyAgentWrapper(options).run()
