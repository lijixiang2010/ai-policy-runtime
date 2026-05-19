"""Minimal Skill / Policy Runtime package."""

from .application.runtime import ExplainResult, NonApplicableTaskError, PolicyRuntime
from .domain.config import EmbeddingConfig, RuntimeConfig, RuntimePaths
from .domain.rule import EffectiveRules, Rule
from .domain.skill import Skill
from .domain.task import TaskContext
from .services.engine import PolicyEngine
from .services.registry import SkillRegistry
from .task_analysis import TaskAnalysis, TaskAnalyzer, TaskSignals

__all__ = [
    "EffectiveRules",
    "EmbeddingConfig",
    "ExplainResult",
    "NonApplicableTaskError",
    "PolicyEngine",
    "PolicyRuntime",
    "Rule",
    "RuntimeConfig",
    "RuntimePaths",
    "Skill",
    "SkillRegistry",
    "TaskAnalysis",
    "TaskAnalyzer",
    "TaskContext",
    "TaskSignals",
]
