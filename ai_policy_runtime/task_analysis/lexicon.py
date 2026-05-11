from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ai_policy_runtime.infrastructure.loader import PolicyLoader


@dataclass(frozen=True)
class LexiconRule:
    """Data-driven text match rule loaded from Skill metadata."""

    field: str
    value: Any
    phrases: tuple[str, ...]
    confidence: float
    source: str
    set_context: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    semantic_texts: tuple[str, ...] = ()


@dataclass(frozen=True)
class TriggerProfile:
    """Capabilities associated with a task trigger."""

    trigger: str
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskLexicon:
    """Runtime task-analysis lexicon assembled from installed Skills."""

    domain_rules: tuple[LexiconRule, ...] = ()
    trigger_rules: tuple[LexiconRule, ...] = ()
    context_rules: tuple[LexiconRule, ...] = ()
    trigger_profiles: tuple[TriggerProfile, ...] = ()

    @classmethod
    def from_skills_dir(cls, path: str | Path) -> "TaskLexicon":
        loader = PolicyLoader()
        domain_rules: list[LexiconRule] = []
        trigger_rules: list[LexiconRule] = []
        context_rules: list[LexiconRule] = []
        trigger_capabilities: dict[str, set[str]] = {}

        for file_path in _iter_skill_files(path):
            document = SkillAnalysisDocument(loader.load_mapping(file_path), file_path)
            if domain_rule := document.domain_rule():
                domain_rules.append(domain_rule)
            for trigger, values in document.trigger_capabilities().items():
                if values:
                    trigger_capabilities.setdefault(trigger, set()).update(values)
            trigger_rules.extend(document.trigger_rules())
            context_rules.extend(document.context_rules())

        return cls(
            domain_rules=tuple(domain_rules),
            trigger_rules=tuple(trigger_rules),
            context_rules=tuple(context_rules),
            trigger_profiles=tuple(
                TriggerProfile(trigger=trigger, capabilities=tuple(sorted(values)))
                for trigger, values in sorted(trigger_capabilities.items())
            ),
        )

    def capabilities_for(self, trigger: str) -> tuple[str, ...]:
        values = {
            capability
            for profile in self.trigger_profiles
            if profile.trigger == trigger
            for capability in profile.capabilities
        }
        return tuple(sorted(values))


class SkillAnalysisDocument:
    """Task-analysis view over a raw Skill DSL mapping."""

    def __init__(self, data: dict[str, Any], path: Path) -> None:
        self._data = data
        self._path = path
        self._meta = data.get("skill", {})
        self._analysis = data.get("task_analysis", self._meta.get("task_analysis", {}))
        self.skill_id = str(self._meta.get("id", data.get("skill_id", path.stem)))

    def domain_rule(self) -> LexiconRule | None:
        """Return the domain rule declared by this Skill, if any."""

        domain = self._meta.get("domain") or _first(self._data.get("domains"))
        if not domain:
            return None
        phrases = _strings(self._analysis.get("domain_aliases", ())) or (str(domain),)
        return LexiconRule(
            field="domain",
            value=str(domain),
            phrases=_normalize_phrases(phrases),
            confidence=float(self._analysis.get("domain_confidence", 0.9)),
            source=f"skill:{self.skill_id}:domain",
            semantic_texts=_normalize_phrases(
                _strings(self._analysis.get("domain_semantics", ()))
            ),
        )

    def trigger_rules(self) -> tuple[LexiconRule, ...]:
        """Return task-trigger rules declared by this Skill."""

        semantics = dict(self._analysis.get("trigger_semantics", {}))
        return tuple(
            LexiconRule(
                field="task_type",
                value=str(trigger),
                phrases=_normalize_phrases(_strings(aliases)),
                confidence=float(self._analysis.get("trigger_confidence", 0.82)),
                source=f"skill:{self.skill_id}:trigger:{trigger}",
                semantic_texts=_normalize_phrases(
                    _strings(semantics.get(trigger, ()))
                ),
            )
            for trigger, aliases in dict(self._analysis.get("trigger_aliases", {})).items()
        )

    def context_rules(self) -> tuple[LexiconRule, ...]:
        """Return context-setting rules declared by this Skill."""

        return tuple(
            self._context_rule(item)
            for item in self._analysis.get("context_rules", ())
            if isinstance(item, dict)
        )

    def trigger_capabilities(self) -> dict[str, set[str]]:
        """Return trigger-specific capability declarations."""

        return {
            str(trigger): set(_strings(values))
            for trigger, values in dict(
                self._analysis.get("trigger_capabilities", {})
            ).items()
        }

    def _context_rule(self, item: dict[str, Any]) -> LexiconRule:
        return LexiconRule(
            field=str(item.get("field", "context")),
            value=item.get("value"),
            phrases=_normalize_phrases(_strings(item.get("match", ()))),
            confidence=float(item.get("confidence", 0.8)),
            source=f"skill:{self.skill_id}:context",
            set_context=dict(item.get("set", {})),
            tags=tuple(_strings(item.get("tags", ()))),
            semantic_texts=_normalize_phrases(_strings(item.get("semantic_match", ()))),
        )


def _iter_skill_files(path: str | Path) -> Iterable[Path]:
    root = Path(path)
    if not root.exists():
        return ()
    return (
        item
        for item in sorted(root.rglob("*"))
        if item.is_file() and item.name.endswith((".skill.yaml", ".skill.yml", ".skill.json"))
    )


def _first(value: Any) -> Any:
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return None


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def _normalize_phrases(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(" ".join(value.lower().strip().split()) for value in values if value)
