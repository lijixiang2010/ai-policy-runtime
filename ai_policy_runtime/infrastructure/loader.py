from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_policy_runtime.domain.pack import SkillPack
from ai_policy_runtime.domain.skill import Skill


class PolicyLoader:
    """Load Skill and Pack objects from JSON/YAML files."""

    suffixes = {".json", ".yaml", ".yml"}

    def load_mapping(self, path: str | Path) -> dict[str, Any]:
        file_path = Path(path)
        suffix = file_path.suffix.lower()
        text = file_path.read_text(encoding="utf-8")

        if suffix == ".json":
            return json.loads(text)

        if suffix in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "YAML skill files require PyYAML. Use JSON skill files or install PyYAML."
                ) from exc
            loaded = yaml.safe_load(text)
            return loaded or {}

        raise ValueError(f"Unsupported file extension: {file_path.suffix}")

    def load_skill(self, path: str | Path) -> Skill:
        return Skill.from_mapping(self.load_mapping(path))

    def load_pack(self, path: str | Path) -> SkillPack:
        return SkillPack.from_mapping(self.load_mapping(path))

    def load_skills(self, path: str | Path) -> list[Skill]:
        return [self.load_skill(item) for item in self._iter_files(path, pack=False)]

    def load_packs(self, path: str | Path) -> list[SkillPack]:
        return [self.load_pack(item) for item in self._iter_files(path, pack=True)]

    def _iter_files(self, path: str | Path, *, pack: bool) -> list[Path]:
        root = Path(path)
        if not root.exists():
            return []
        marker = ".pack."
        return [
            file_path
            for file_path in sorted(root.rglob("*"))
            if file_path.is_file()
            and file_path.suffix.lower() in self.suffixes
            and ((marker in file_path.name) is pack)
        ]


_DEFAULT_LOADER = PolicyLoader()


def load_mapping(path: str | Path) -> dict[str, Any]:
    return _DEFAULT_LOADER.load_mapping(path)


def load_skill(path: str | Path) -> Skill:
    return _DEFAULT_LOADER.load_skill(path)


def load_pack(path: str | Path) -> SkillPack:
    return _DEFAULT_LOADER.load_pack(path)


def load_skills_from_dir(path: str | Path) -> list[Skill]:
    return _DEFAULT_LOADER.load_skills(path)


def load_packs_from_dir(path: str | Path) -> list[SkillPack]:
    return _DEFAULT_LOADER.load_packs(path)
