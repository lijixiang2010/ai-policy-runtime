from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ai_policy_runtime.domain.pack import PackRegistry
from ai_policy_runtime.domain.rule import Rule
from ai_policy_runtime.domain.skill import Skill
from ai_policy_runtime.domain.task import TaskContext
from ai_policy_runtime.infrastructure.conditions import ConditionError, evaluate_condition
from ai_policy_runtime.infrastructure.loader import load_packs_from_dir, load_skills_from_dir


GENERIC_ACTIVATION_TAGS = frozenset(
    {
        "cpp",
        "generation",
        "review",
        "core-guidelines",
        "standard-library",
    }
)


class SkillRegistry:
    """In-memory index for Skill activation and Pack expansion."""

    def __init__(
        self, skills: Iterable[Skill] = (), packs: PackRegistry | None = None
    ) -> None:
        self._skills: dict[str, Skill] = {}
        self.packs = packs or PackRegistry()
        for skill in skills:
            self.register(skill)

    @classmethod
    def from_dir(cls, path: str | Path) -> "SkillRegistry":
        return cls(load_skills_from_dir(path))

    @classmethod
    def from_dirs(cls, skills_path: str | Path, packs_path: str | Path) -> "SkillRegistry":
        return cls(
            load_skills_from_dir(skills_path),
            PackRegistry(load_packs_from_dir(packs_path)),
        )

    def register(self, skill: Skill) -> None:
        if skill.skill_id in self._skills:
            raise ValueError(f"Duplicate skill_id: {skill.skill_id}")
        self._skills[skill.skill_id] = skill

    def get(self, skill_id: str) -> Skill:
        return self._skills[skill_id]

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def activate(
        self, task: TaskContext, pack_ids: Iterable[str] = ()
    ) -> tuple[list[Skill], tuple[Rule, ...]]:
        activation = ActivationSet(self._skills)
        activation.add(skill for skill in self._skills.values() if self._matches(skill, task))
        pack_overrides = (
            self._apply_packs(activation, pack_ids)
            if _pack_activation_allowed(task)
            else []
        )
        activation.include_dependencies()
        return activation.filtered(), tuple(pack_overrides)

    def active_skills(self, task: TaskContext, pack_ids: Iterable[str] = ()) -> list[Skill]:
        skills, _ = self.activate(task, pack_ids)
        return skills

    def _resolve_skill_pattern(self, pattern: str) -> list[str]:
        if pattern.endswith(".*"):
            prefix = pattern[:-1]
            return [skill_id for skill_id in self._skills if skill_id.startswith(prefix)]
        return [pattern]

    def _apply_packs(
        self, activation: "ActivationSet", pack_ids: Iterable[str]
    ) -> list[Rule]:
        overrides: list[Rule] = []
        for pack_id in pack_ids:
            includes, pack_overrides = self.packs.expand(pack_id)
            overrides.extend(pack_overrides)
            for pattern in includes:
                activation.add_by_id(self._resolve_skill_pattern(pattern))
        return overrides

    def _matches(self, skill: Skill, task: TaskContext) -> bool:
        if skill.status in {"deprecated", "removed"}:
            return False
        if skill.domains and task.domain not in skill.domains:
            return False
        if skill.triggers and task.task_type not in skill.triggers:
            return False
        if skill.capabilities and not set(skill.capabilities).intersection(task.capabilities):
            return False
        if not _tags_match(skill.tags, task.tags):
            return False
        if not self._context_matches(skill, task):
            return False
        try:
            return evaluate_condition(skill.activation_when, task.condition_context())
        except ConditionError:
            return False

    def _context_matches(self, skill: Skill, task: TaskContext) -> bool:
        for key, expected in skill.context.items():
            if key not in task.context:
                return False
            if not _matches_expected(task.context[key], expected):
                return False
        return True


def _matches_expected(actual: object, expected: object) -> bool:
    if isinstance(expected, str) and expected.startswith(">="):
        try:
            return float(actual) >= float(expected[2:])
        except (TypeError, ValueError):
            return False
    return actual == expected


def _tags_match(skill_tags: tuple[str, ...], task_tags: tuple[str, ...]) -> bool:
    meaningful_skill_tags = set(skill_tags) - GENERIC_ACTIVATION_TAGS
    if not meaningful_skill_tags:
        return True
    return bool(meaningful_skill_tags.intersection(task_tags))


def _pack_activation_allowed(task: TaskContext) -> bool:
    """Packs refine an identified task; they must not create one from context alone."""

    if task.task_type == "unknown":
        return False
    if task.domain != "general":
        return True
    return task.context.get("artifact_type") == "code" or bool(task.context.get("language"))


class ActivationSet:
    """Mutable active-skill set with dependency and compatibility handling."""

    def __init__(self, available: dict[str, Skill]) -> None:
        self._available = available
        self._active: dict[str, Skill] = {}

    def add(self, skills: Iterable[Skill]) -> None:
        for skill in skills:
            self._active[skill.skill_id] = skill

    def add_by_id(self, skill_ids: Iterable[str]) -> None:
        self.add(self._available[skill_id] for skill_id in skill_ids if skill_id in self._available)

    def include_dependencies(self) -> None:
        changed = True
        while changed:
            changed = False
            for skill in list(self._active.values()):
                for dependency in skill.dependencies:
                    if dependency not in self._active and dependency in self._available:
                        self._active[dependency] = self._available[dependency]
                        changed = True

    def filtered(self) -> list[Skill]:
        active_ids = set(self._active)
        return [
            skill
            for skill in self._active.values()
            if skill.status not in {"deprecated", "removed"}
            and not any(item in active_ids for item in skill.incompatibilities)
        ]
