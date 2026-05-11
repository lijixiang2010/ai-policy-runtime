from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class Violation:
    """A deterministic policy violation found in an output file."""

    rule_id: str
    severity: str
    path: str
    line: int
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "path": self.path,
            "line": self.line,
            "message": self.message,
        }


class FileVerifier:
    """Run configured rule verifiers against files."""

    suffixes = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".txt"}

    def __init__(self, verifiers: list["RuleVerifier"] | None = None) -> None:
        self._verifiers = verifiers or [
            ForbiddenTextVerifier(),
            ForbiddenRegexVerifier(),
            RequiredTextVerifier(),
        ]

    def verify_current_state(self, root: str | Path, target: str | Path) -> list[Violation]:
        root_path = Path(root)
        rules_path = root_path / ".policy" / "current" / "effective-rules.json"
        if not rules_path.exists():
            raise FileNotFoundError(f"Effective rules not found: {rules_path}")
        data = json.loads(rules_path.read_text(encoding="utf-8"))
        hard_rules = list(data.get("effective_rules", {}).get("hard", ()))
        return self.verify_rules(hard_rules, Path(target))

    def verify_rules(self, rules: list[dict[str, Any]], target: Path) -> list[Violation]:
        return [
            violation
            for rule in rules
            for path in self._iter_files(target)
            for verifier in self._verifiers
            if verifier.supports(rule)
            for violation in verifier.verify(rule, path)
        ]

    def _iter_files(self, target: Path) -> list[Path]:
        if target.is_file():
            return [target]
        if not target.exists():
            return []
        return [
            path
            for path in target.rglob("*")
            if path.is_file()
            and path.suffix.lower() in self.suffixes
            and ".policy" not in path.parts
        ]


class RuleVerifier(Protocol):
    """Protocol for pluggable deterministic rule verifiers."""

    def supports(self, rule: dict[str, Any]) -> bool:
        """Return whether this verifier can check the rule."""

    def verify(self, rule: dict[str, Any], path: Path) -> list[Violation]:
        """Return violations for a supported rule and file."""


class ForbiddenTextVerifier:
    """Verifier for text-searchable forbid rules."""

    def supports(self, rule: dict[str, Any]) -> bool:
        if str(rule.get("action", "")).lower() != "forbid":
            return False
        return bool(_forbidden_needle(rule))

    def verify(self, rule: dict[str, Any], path: Path) -> list[Violation]:
        needle = _forbidden_needle(rule)
        if not needle:
            return []
        return _scan_file(rule, needle, path)


class ForbiddenRegexVerifier:
    """Verifier for forbid rules that declare a regex pattern."""

    def supports(self, rule: dict[str, Any]) -> bool:
        return (
            str(rule.get("action", "")).lower() == "forbid"
            and bool(rule.get("pattern") or rule.get("regex"))
        )

    def verify(self, rule: dict[str, Any], path: Path) -> list[Violation]:
        pattern = str(rule.get("pattern", rule.get("regex", "")))
        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            return [
                Violation(
                    rule_id=str(rule.get("id", "")),
                    severity="error",
                    path=str(path),
                    line=0,
                    message=f"Invalid verification regex: {exc}",
                )
            ]
        return _scan_regex(rule, compiled, path)


class RequiredTextVerifier:
    """Verifier for require rules whose value must appear in checked files."""

    def supports(self, rule: dict[str, Any]) -> bool:
        return (
            str(rule.get("action", "")).lower() == "require"
            and bool(_required_needle(rule))
        )

    def verify(self, rule: dict[str, Any], path: Path) -> list[Violation]:
        needle = _required_needle(rule)
        if not needle or _file_contains(path, needle):
            return []
        return [
            Violation(
                rule_id=str(rule.get("id", "")),
                severity="error",
                path=str(path),
                line=0,
                message=f"Required value '{needle}' not found.",
            )
        ]


_DEFAULT_VERIFIER = FileVerifier()


def verify_current_state(root: str | Path, target: str | Path) -> list[Violation]:
    return _DEFAULT_VERIFIER.verify_current_state(root, target)


def verify_rules(rules: list[dict[str, Any]], target: Path) -> list[Violation]:
    return _DEFAULT_VERIFIER.verify_rules(rules, target)


def write_violations(root: str | Path, violations: list[Violation]) -> Path:
    return ViolationWriter(root).write(violations)


class ViolationWriter:
    """Persist verification output under .policy/current."""

    def __init__(self, root: str | Path) -> None:
        self.current = Path(root) / ".policy" / "current"

    def write(self, violations: list[Violation]) -> Path:
        self.current.mkdir(parents=True, exist_ok=True)
        path = self.current / "violations.json"
        path.write_text(
            json.dumps(
                {"violations": [item.to_dict() for item in violations]},
                indent=2,
            ),
            encoding="utf-8",
        )
        return path


def _scan_file(rule: dict[str, Any], needle: str, path: Path) -> list[Violation]:
    violations: list[Violation] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return violations
    for index, line in enumerate(lines, start=1):
        if needle in line:
            violations.append(
                Violation(
                    rule_id=str(rule.get("id", "")),
                    severity="error",
                    path=str(path),
                    line=index,
                    message=f"Forbidden value '{needle}' found.",
                )
            )
    return violations


def _scan_regex(rule: dict[str, Any], pattern: re.Pattern[str], path: Path) -> list[Violation]:
    violations: list[Violation] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return violations
    for index, line in enumerate(lines, start=1):
        if pattern.search(line):
            violations.append(
                Violation(
                    rule_id=str(rule.get("id", "")),
                    severity="error",
                    path=str(path),
                    line=index,
                    message=f"Forbidden pattern '{pattern.pattern}' found.",
                )
            )
    return violations


def _file_contains(path: Path, needle: str) -> bool:
    try:
        return needle in path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False


def _looks_textual(value: str) -> bool:
    return any(ch.isalpha() or ch in "_:" for ch in value)


def _forbidden_needle(rule: dict[str, Any]) -> str:
    needle = str(rule.get("value", "")).strip()
    if not needle:
        needle = str(rule.get("target", "")).strip()
    return needle if needle and _looks_textual(needle) else ""


def _required_needle(rule: dict[str, Any]) -> str:
    needle = str(rule.get("value", "")).strip()
    if not needle:
        needle = str(rule.get("target", "")).strip()
    return needle if needle and _looks_textual(needle) else ""
