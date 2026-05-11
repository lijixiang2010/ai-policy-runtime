from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .rule import Rule, RuleStrength
from .skill import _normalize_rule_data


@dataclass(frozen=True)
class SkillPack:
    """A named composition of skills and pack-level override rules."""

    pack_id: str
    name: str
    version: str = "1.0.0"
    description: str = ""
    includes: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    extends: tuple[str, ...] = ()
    override_rules: tuple[Rule, ...] = ()

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "SkillPack":
        meta = data.get("pack", {})
        pack_id = str(meta["id"])
        override_rules: list[Rule] = []
        for item in data.get("overrides", ()):
            rule_data = _normalize_rule_data(dict(item), RuleStrength.PREFERENCE, pack_id)
            override_rules.append(
                Rule.from_mapping(
                    rule_data,
                    strength=RuleStrength.PREFERENCE,
                    source=pack_id,
                    level="PROJECT",
                    priority=100,
                )
            )
        return cls(
            pack_id=pack_id,
            name=str(meta.get("name", pack_id)),
            version=str(meta.get("version", "1.0.0")),
            description=str(meta.get("description", "")),
            includes=tuple(data.get("includes", ())),
            excludes=tuple(data.get("excludes", ())),
            extends=tuple(data.get("extends", ())),
            override_rules=tuple(override_rules),
        )


class PackRegistry:
    """Registry and expansion service for Skill Packs."""

    def __init__(self, packs: list[SkillPack] | None = None) -> None:
        self._packs = {pack.pack_id: pack for pack in packs or []}

    def get(self, pack_id: str) -> SkillPack:
        return self._packs[pack_id]

    def all(self) -> list[SkillPack]:
        return list(self._packs.values())

    def expand(self, pack_id: str) -> tuple[set[str], tuple[Rule, ...]]:
        seen: set[str] = set()
        includes: set[str] = set()
        excludes: set[str] = set()
        overrides: list[Rule] = []
        self._expand_into(pack_id, seen, includes, excludes, overrides)
        return includes - excludes, tuple(overrides)

    def _expand_into(
        self,
        pack_id: str,
        seen: set[str],
        includes: set[str],
        excludes: set[str],
        overrides: list[Rule],
    ) -> None:
        if pack_id in seen:
            return
        seen.add(pack_id)
        pack = self.get(pack_id)
        for parent in pack.extends:
            self._expand_into(parent, seen, includes, excludes, overrides)
        includes.update(pack.includes)
        excludes.update(pack.excludes)
        overrides.extend(pack.override_rules)
