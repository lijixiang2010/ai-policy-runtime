from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from ai_policy_runtime.domain.task import TaskContext
from ai_policy_runtime.task_analysis.schema import ExtractionEvidence, TaskAnalysis


PROJECT_CONFIDENCE_THRESHOLD = 0.7
WEAK_TAG_CONFIDENCE = 0.58
MAX_CMAKE_FILES = 20
IGNORED_LAYOUT_DIRS = {".git", ".policy", ".venv", "node_modules", "__pycache__", "models"}
CPP_SOURCE_SUFFIXES = (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx")


@dataclass(frozen=True)
class ManifestProbe:
    """A simple manifest-file probe for project language and build-system facts."""

    filename: str
    language: str
    build_system: str
    confidence: float


MANIFEST_PROBES = (
    ManifestProbe("Cargo.toml", "rust", "cargo", 0.94),
    ManifestProbe("pyproject.toml", "python", "python", 0.92),
    ManifestProbe("package.json", "javascript", "node", 0.9),
    ManifestProbe("go.mod", "go", "go", 0.94),
    ManifestProbe("vcpkg.json", "cpp", "vcpkg", 0.72),
    ManifestProbe("conanfile.txt", "cpp", "conan", 0.72),
    ManifestProbe("conanfile.py", "cpp", "conan", 0.72),
)


@dataclass(frozen=True)
class ProjectFact:
    """A project-level fact with provenance and confidence."""

    field: str
    value: Any
    source: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "source": self.source,
            "confidence": round(self.confidence, 3),
        }


@dataclass(frozen=True)
class ProjectAnalysis:
    """Deterministic project context inferred from repository files."""

    facts: tuple[ProjectFact, ...]
    selected: tuple[ProjectFact, ...]

    @property
    def primary_language(self) -> str | None:
        fact = self.fact("domain")
        return str(fact.value) if fact else None

    def fact(self, field: str) -> ProjectFact | None:
        for item in self.selected:
            if item.field == field:
                return item
        return None

    def context(self, *, min_confidence: float = 0.7) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for fact in self.selected:
            if not fact.field.startswith("context.") or fact.confidence < min_confidence:
                continue
            values[fact.field.removeprefix("context.")] = fact.value
        return values

    def tags(self, *, min_confidence: float = 0.7) -> tuple[str, ...]:
        values: set[str] = set()
        for fact in self.selected:
            if fact.field == "tag" and fact.confidence >= min_confidence:
                values.add(str(fact.value))
        return tuple(sorted(values))

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": [item.to_dict() for item in self.selected],
            "facts": [item.to_dict() for item in self.facts],
        }


class ProjectContextAnalyzer:
    """Extract high-confidence project facts from common build files."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def analyze(self) -> ProjectAnalysis:
        facts = [
            fact
            for collector in (
                self._policy_project_facts,
                self._compile_commands_facts,
                self._cmake_facts,
                self._manifest_facts,
                self._file_layout_facts,
                self._weak_text_facts,
            )
            for fact in collector()
        ]
        return ProjectAnalysis(facts=tuple(facts), selected=tuple(_select_facts(facts)))

    def _policy_project_facts(self) -> list[ProjectFact]:
        path = self.root / ".policy" / "project.yaml"
        if not path.exists():
            path = self.root / ".policy" / "project.yml"
        if not path.exists():
            return []
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            return []
        if not isinstance(data, dict):
            return []

        facts: list[ProjectFact] = []
        source = _relative(path, self.root)
        if domain := data.get("domain") or data.get("language"):
            facts.extend(_language_facts(_normalize_language(str(domain)), source, 0.99))
        if build_system := data.get("build_system"):
            facts.append(ProjectFact("context.build_system", str(build_system), source, 0.99))
        if isinstance(data.get("context"), dict):
            for key, value in data["context"].items():
                facts.append(ProjectFact(f"context.{key}", value, source, 0.99))
        if isinstance(data.get("tags"), list):
            for value in data["tags"]:
                facts.append(ProjectFact("tag", str(value), source, 0.95))
        return facts

    def _compile_commands_facts(self) -> list[ProjectFact]:
        path = self.root / "compile_commands.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []

        facts: list[ProjectFact] = [
            *_language_facts("cpp", _relative(path, self.root), 0.96),
        ]
        standards: list[int] = []
        for index, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            command = _compile_command_text(item)
            standard = _extract_cpp_standard(command)
            if standard is None:
                continue
            standards.append(standard)
            source = f"{_relative(path, self.root)}[{index}]: {_std_fragment(command)}"
            facts.append(ProjectFact("context.standard", standard, source, 0.98))
            facts.append(ProjectFact("context.selected_standard_is_known", True, source, 0.98))
        if standards:
            common_standard, count = Counter(standards).most_common(1)[0]
            confidence = min(0.99, 0.96 + count / max(len(standards), 1) * 0.03)
            facts.append(
                ProjectFact(
                    "context.standard",
                    common_standard,
                    f"{_relative(path, self.root)}: most common -std across {len(standards)} commands",
                    confidence,
                )
            )
        return facts

    def _cmake_facts(self) -> list[ProjectFact]:
        paths = list(self.root.rglob("CMakeLists.txt"))
        if not paths:
            return []
        facts: list[ProjectFact] = [
            *_language_facts("cpp", _relative(paths[0], self.root), 0.88),
            ProjectFact("context.build_system", "cmake", _relative(paths[0], self.root), 0.95),
        ]
        for path in paths[:MAX_CMAKE_FILES]:
            for lineno, line in _iter_meaningful_lines(path):
                standard = _cmake_standard_from_line(line)
                if standard is None:
                    continue
                source = f"{_relative(path, self.root)}:{lineno}: {line.strip()}"
                confidence = 0.95 if "target_compile_features" in line.lower() else 0.9
                facts.append(ProjectFact("context.standard", standard, source, confidence))
                facts.append(
                    ProjectFact("context.selected_standard_is_known", True, source, confidence)
                )
        return facts

    def _manifest_facts(self) -> list[ProjectFact]:
        facts: list[ProjectFact] = []
        for probe in MANIFEST_PROBES:
            path = self.root / probe.filename
            if not path.exists():
                continue
            source = _relative(path, self.root)
            facts.extend(_language_facts(probe.language, source, probe.confidence))
            facts.append(
                ProjectFact("context.build_system", probe.build_system, source, probe.confidence)
            )
        return facts

    def _file_layout_facts(self) -> list[ProjectFact]:
        counts = {
            "cpp": _count_files(self.root, CPP_SOURCE_SUFFIXES),
            "python": _count_files(self.root, (".py",)),
            "rust": _count_files(self.root, (".rs",)),
            "javascript": _count_files(self.root, (".js", ".jsx", ".ts", ".tsx")),
            "go": _count_files(self.root, (".go",)),
        }
        language, count = max(counts.items(), key=lambda item: item[1])
        if count <= 0:
            return []
        confidence = 0.65 if count < 5 else 0.78
        source = f"file layout: {count} {language} source/header files"
        return _language_facts(language, source, confidence)

    def _weak_text_facts(self) -> list[ProjectFact]:
        facts: list[ProjectFact] = []
        for path in (self.root / "README.md", self.root / "readme.md"):
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            if any(token in text for token in ("low latency", "low-latency", "低延迟")):
                facts.append(
                    ProjectFact("tag", "low_latency", _relative(path, self.root), WEAK_TAG_CONFIDENCE)
                )
            if any(token in text for token in ("matching engine", "撮合")):
                facts.append(
                    ProjectFact("tag", "trading", _relative(path, self.root), WEAK_TAG_CONFIDENCE)
                )
        return facts


def merge_project_analysis(
    task_analysis: TaskAnalysis,
    project: ProjectAnalysis,
    *,
    supported_domains: set[str] | None = None,
) -> TaskAnalysis:
    """Merge project facts into task analysis without overriding explicit prompt facts."""

    return ProjectContextMerger(project, supported_domains=supported_domains).merge(task_analysis)


class ProjectContextMerger:
    """Merge project facts into task analysis under explicit precedence rules."""

    def __init__(
        self,
        project: ProjectAnalysis,
        *,
        supported_domains: set[str] | None = None,
    ) -> None:
        self.project = project
        self.supported_domains = supported_domains
        self.domain_fact = project.fact("domain")

    def merge(self, analysis: TaskAnalysis) -> TaskAnalysis:
        task = analysis.task
        evidence = list(analysis.evidence)
        domain = self._merged_domain(task.domain, evidence)
        context, tags = self._merged_context_and_tags(task, evidence)
        if domain != "general":
            context.setdefault("language", domain)
            tags.add(domain)
        merged_task = TaskContext(
            domain=domain,
            task_type=task.task_type,
            capabilities=task.capabilities,
            tags=tuple(sorted(tags)),
            context=context,
        )
        confidence = min(1.0, max(analysis.confidence, _merged_confidence(analysis, self.project)))
        return TaskAnalysis(
            task=merged_task,
            confidence=confidence,
            evidence=tuple(evidence),
            needs_review=confidence < PROJECT_CONFIDENCE_THRESHOLD,
        )

    @property
    def project_domain_supported(self) -> bool:
        return (
            self.domain_fact is not None
            and (
                self.supported_domains is None
                or str(self.domain_fact.value) in self.supported_domains
            )
        )

    def _merged_domain(
        self,
        current_domain: str,
        evidence: list[ExtractionEvidence],
    ) -> str:
        if (
            current_domain == "general"
            and self.domain_fact
            and self.project_domain_supported
            and self.domain_fact.confidence >= PROJECT_CONFIDENCE_THRESHOLD
        ):
            evidence.append(_project_evidence(self.domain_fact))
            return str(self.domain_fact.value)
        return current_domain

    def _merged_context_and_tags(
        self,
        task: TaskContext,
        evidence: list[ExtractionEvidence],
    ) -> tuple[dict[str, Any], set[str]]:
        context = dict(task.context)
        tags = set(task.tags)
        context_compatible = self._project_context_compatible(task.domain)
        for fact in self.project.selected:
            if fact.field.startswith("context."):
                self._merge_context_fact(fact, context, evidence, context_compatible)
            elif fact.field == "tag" and fact.confidence >= PROJECT_CONFIDENCE_THRESHOLD:
                tags.add(str(fact.value))
                evidence.append(_project_evidence(fact))
        return context, tags

    def _merge_context_fact(
        self,
        fact: ProjectFact,
        context: dict[str, Any],
        evidence: list[ExtractionEvidence],
        context_compatible: bool,
    ) -> None:
        if fact.confidence < PROJECT_CONFIDENCE_THRESHOLD or not context_compatible:
            return
        key = fact.field.removeprefix("context.")
        if key == "language" and not self.project_domain_supported:
            return
        if key in context or _has_prompt_evidence(evidence, fact.field):
            return
        context[key] = fact.value
        evidence.append(_project_evidence(fact))

    def _project_context_compatible(self, task_domain: str) -> bool:
        if self.domain_fact is None:
            return True
        value = str(self.domain_fact.value)
        if self.supported_domains is not None and value not in self.supported_domains:
            return False
        return task_domain == "general" or task_domain == value


def _select_facts(facts: Iterable[ProjectFact]) -> list[ProjectFact]:
    grouped: dict[str, list[ProjectFact]] = {}
    for fact in facts:
        grouped.setdefault(fact.field, []).append(fact)
    selected: list[ProjectFact] = []
    for field, values in grouped.items():
        if field == "tag":
            selected.extend(_select_tags(values))
            continue
        selected.append(max(values, key=lambda item: (item.confidence, _source_rank(item.source))))
    return sorted(selected, key=lambda item: item.field)


def _select_tags(values: list[ProjectFact]) -> list[ProjectFact]:
    best_by_tag: dict[str, ProjectFact] = {}
    for fact in values:
        key = str(fact.value)
        current = best_by_tag.get(key)
        if current is None or (fact.confidence, _source_rank(fact.source)) > (
            current.confidence,
            _source_rank(current.source),
        ):
            best_by_tag[key] = fact
    return list(best_by_tag.values())


def _source_rank(source: str) -> int:
    normalized = source.replace("\\", "/")
    if normalized.startswith(".policy/project."):
        return 5
    if normalized.startswith("compile_commands.json"):
        return 4
    if "CMakeLists.txt" in normalized:
        return 3
    return 1


def _project_evidence(fact: ProjectFact) -> ExtractionEvidence:
    return ExtractionEvidence(
        field=fact.field,
        value=fact.value,
        source=f"project:{fact.source}",
        confidence=fact.confidence,
    )


def _has_prompt_evidence(evidence: Iterable[ExtractionEvidence], field: str) -> bool:
    return any(item.field == field and not item.source.startswith("project:") for item in evidence)


def _merged_confidence(task_analysis: TaskAnalysis, project: ProjectAnalysis) -> float:
    score = task_analysis.confidence
    if project.fact("domain"):
        score += 0.12
    if project.fact("context.standard"):
        score += 0.08
    return min(score, 1.0)


def _compile_command_text(item: dict[str, Any]) -> str:
    if isinstance(item.get("command"), str):
        return str(item["command"])
    if isinstance(item.get("arguments"), list):
        return " ".join(str(arg) for arg in item["arguments"])
    return ""


def _extract_cpp_standard(text: str) -> int | None:
    match = re.search(r"(?:-std=|/std:)(?:gnu\+\+|c\+\+)(\d{2})", text, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _std_fragment(text: str) -> str:
    match = re.search(r"(?:-std=|/std:)\S+", text, re.IGNORECASE)
    return match.group(0) if match else "standard flag"


def _cmake_standard_from_line(line: str) -> int | None:
    lowered = line.lower()
    match = re.search(r"cxx_std_(\d{2})", lowered)
    if match:
        return int(match.group(1))
    if "cxx_standard" in lowered or "cmake_cxx_standard" in lowered:
        match = re.search(r"\b(11|14|17|20|23|26)\b", lowered)
        if match:
            return int(match.group(1))
    return None


def _iter_meaningful_lines(path: Path) -> Iterable[tuple[int, str]]:
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if line:
            yield lineno, line


def _count_files(root: Path, suffixes: tuple[str, ...]) -> int:
    count = 0
    for path in root.rglob("*"):
        if any(part in IGNORED_LAYOUT_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() in suffixes:
            count += 1
    return count


def _language_facts(language: str, source: str, confidence: float) -> list[ProjectFact]:
    return [
        ProjectFact("domain", language, source, confidence),
        ProjectFact("context.language", language, source, confidence),
    ]


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _normalize_language(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"c++", "cxx"}:
        return "cpp"
    if lowered in {"js", "ts", "node"}:
        return "javascript"
    return lowered
