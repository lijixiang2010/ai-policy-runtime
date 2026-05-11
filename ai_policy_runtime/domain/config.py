from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimePaths:
    """Resolved filesystem paths used by the policy runtime."""

    root: Path
    skills: Path
    packs: Path
    current: Path


@dataclass(frozen=True)
class RuntimeConfig:
    """User-facing runtime configuration with conservative defaults."""

    root: Path = Path(".")
    policy_root: Path | None = None
    skills_dir: str = "skills"
    packs_dir: str = "packs"

    @property
    def paths(self) -> RuntimePaths:
        root = self.root
        policy_root = self.policy_root or root
        return RuntimePaths(
            root=root,
            skills=_resolve_policy_path(policy_root, self.skills_dir),
            packs=_resolve_policy_path(policy_root, self.packs_dir),
            current=root / ".policy" / "current",
        )

    @classmethod
    def from_values(
        cls,
        *,
        root: str | Path = ".",
        policy_root: str | Path | None = None,
        skills_dir: str = "skills",
        packs_dir: str = "packs",
    ) -> "RuntimeConfig":
        return cls(
            root=Path(root),
            policy_root=Path(policy_root) if policy_root is not None else None,
            skills_dir=skills_dir,
            packs_dir=packs_dir,
        )


def _resolve_policy_path(policy_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return policy_root / path
