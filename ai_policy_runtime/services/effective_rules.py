from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable

from ai_policy_runtime.domain.rule import EffectiveRules, Rule
from ai_policy_runtime.domain.task import TaskContext


SCHEMA_VERSION = 1


class EffectiveRulesRenderer:
    """Render Effective Rules into the standardized machine and agent formats."""

    def __init__(
        self,
        *,
        mapper: "RuleEffectiveMapper | None" = None,
        prompt: "PromptRenderer | None" = None,
    ) -> None:
        self._mapper = mapper or RuleEffectiveMapper()
        self._prompt = prompt or PromptRenderer()

    def to_mapping(
        self,
        *,
        task: TaskContext,
        task_id: str,
        summary: str,
        rules: EffectiveRules,
        trace: dict[str, Any],
    ) -> dict[str, Any]:
        generated_at = trace.get("generated_at") or datetime.now(timezone.utc).isoformat()
        structured_trace = {
            "activated_skills": trace.get("active_skills", trace.get("activated_skills", [])),
            "packs": trace.get("packs", []),
            "conflict_count": trace.get("conflict_count", len(rules.conflicts)),
            "generated_at": generated_at,
        }
        return {
            "effective_rules": {
                "schema_version": SCHEMA_VERSION,
                "task": {
                    "id": task_id,
                    "summary": summary,
                    "context": _task_context(task),
                },
                "hard": [self._mapper.rule(rule) for rule in rules.hard],
                "soft": [self._mapper.rule(rule) for rule in rules.soft],
                "preference": [
                    self._mapper.preference(rule) for rule in rules.preferences
                ],
                "exceptions": [
                    self._mapper.exception(rule) for rule in rules.exceptions
                ],
                "verification": self._mapper.verification(rules),
                "trace": structured_trace,
            }
        }

    def to_prompt(self, mapping: dict[str, Any]) -> str:
        return self._prompt.render(mapping)

    def to_yaml(self, mapping: dict[str, Any]) -> str:
        try:
            import yaml  # type: ignore
        except ImportError:
            return _to_simple_yaml(mapping) + "\n"
        return yaml.safe_dump(mapping, sort_keys=False, allow_unicode=True)

    def to_json(self, mapping: dict[str, Any]) -> str:
        return json.dumps(mapping, indent=2, ensure_ascii=False)


class PromptRenderer:
    """Render standardized effective rules into an agent-readable prompt."""

    INTERNAL_CONTEXT_KEYS = frozenset({"semantic_skill_matches"})
    HARD_LIMIT = 8
    SOFT_LIMIT = 12
    PREFERENCE_LIMIT = 6
    VERIFICATION_LIMIT = 6

    def render(self, mapping: dict[str, Any]) -> str:
        effective = mapping["effective_rules"]
        lines = ["# Effective Rules for Current Task", "", "## Task Context", ""]
        context = effective["task"]["context"]
        for key, value in context.items():
            if key in self.INTERNAL_CONTEXT_KEYS:
                continue
            lines.append(f"- {_label(key)}: {_format_context_value(key, value)}")
        prompt_rules = PromptRuleSelector(context)
        self._append_rule_lines(
            lines,
            "HARD Rules",
            prompt_rules.hard(effective["hard"], self.HARD_LIMIT),
        )
        self._append_rule_lines(
            lines,
            "SOFT Rules",
            prompt_rules.soft(effective["soft"], prompt_rules.soft_limit(self.SOFT_LIMIT)),
        )
        self._append_preference_lines(
            lines,
            prompt_rules.preferences(
                effective["preference"],
                prompt_rules.preference_limit(self.PREFERENCE_LIMIT),
            ),
        )
        self._append_exception_lines(lines, effective["exceptions"])
        self._append_verification_lines(
            lines,
            prompt_rules.verification(effective["verification"], self.VERIFICATION_LIMIT),
        )
        return _sanitize_markdown("\n".join(lines).rstrip()) + "\n"

    def _append_rule_lines(
        self, lines: list[str], title: str, rules: list[dict[str, Any]]
    ) -> None:
        if not rules:
            return
        lines.extend(["", f"## {title}", ""])
        lines.extend(f"- {_sentence(rule['statement'])}" for rule in rules)

    def _append_preference_lines(
        self, lines: list[str], rules: list[dict[str, Any]]
    ) -> None:
        if not rules:
            return
        lines.extend(["", "## Preferences", ""])
        lines.extend(f"- {_preference_prompt_statement(rule)}" for rule in rules)

    def _append_exception_lines(
        self, lines: list[str], exceptions: list[dict[str, Any]]
    ) -> None:
        if not exceptions:
            return
        lines.extend(["", "## Exceptions", ""])
        for exception in exceptions:
            allowed = ", ".join(str(item) for item in exception.get("allow", []))
            condition = exception.get("condition")
            statement = f"{allowed} allowed"
            if condition:
                statement = f"When {condition}, {statement}"
            if exception.get("require"):
                statement += f"; requires: {', '.join(exception['require'])}"
            lines.append(f"- {statement}.")

    def _append_verification_lines(
        self, lines: list[str], verification: dict[str, list[dict[str, Any]]]
    ) -> None:
        required = verification.get("required", [])
        recommended = verification.get("recommended", [])
        if not required and not recommended:
            return
        lines.extend(["", "## Verification Requirements", ""])
        lines.extend(f"- {_sentence(item['statement'])}" for item in required)
        lines.extend(f"- Recommended: {_sentence(item['statement'])}" for item in recommended)


class PromptRuleSelector:
    """Select and collapse rules for the concise agent-facing prompt."""

    def __init__(self, context: dict[str, Any]) -> None:
        self.context = context
        self.refinement = bool(context.get("refinement_requested")) or context.get("task_type") == "refactor_code"
        self.generic_code_refinement = self.refinement and (
            context.get("domain") in {"general", "generic_code"}
            or context.get("language") == "generic_code"
        )
        self.git_workflow = context.get("domain") == "git" or context.get("language") == "git"
        self.cmake_workflow = context.get("domain") == "cmake" or context.get("language") == "cmake"

    def hard(self, rules: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        return self._limit(self._collapse(rules), limit, self._hard_score)

    def soft_limit(self, default: int) -> int:
        if self.git_workflow:
            return min(default, 8)
        if self.cmake_workflow:
            return min(default, 8)
        if self.context.get("unclear_hierarchy") and not self.context.get("duplicated_logic"):
            return min(default, 7)
        return min(default, 9) if self.generic_code_refinement else default

    def soft(self, rules: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        return self._limit(rules, limit, self._soft_score)

    def preference_limit(self, default: int) -> int:
        if self.git_workflow:
            return min(default, 2)
        if self.cmake_workflow:
            return min(default, 2)
        if self.context.get("unclear_hierarchy") and not self.context.get("duplicated_logic"):
            return min(default, 2)
        return min(default, 4) if self.generic_code_refinement else default

    def preferences(self, rules: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        return self._limit(rules, limit, self._preference_score)

    def verification(
        self,
        verification: dict[str, list[dict[str, Any]]],
        limit: int,
    ) -> dict[str, list[dict[str, Any]]]:
        items = [*verification.get("required", ()), *verification.get("recommended", ())]
        if self.refinement:
            return {"required": self._refinement_verification(items, limit), "recommended": []}
        collapsed = self._collapse_verification(items)
        selected = self._limit(collapsed, limit, self._verification_score)
        return {"required": selected, "recommended": []}

    def _refinement_verification(
        self,
        items: list[dict[str, Any]],
        limit: int,
    ) -> list[dict[str, Any]]:
        checks = [
            {
                "id": "verify.prompt.behavior_preservation",
                "type": "review_check",
                "statement": "Verify behavior preservation.",
            },
            {
                "id": "verify.prompt.combined_safety_regression",
                "type": "review_check",
                "statement": (
                    "Verify no new ownership, lifetime, resource, bounds, "
                    "or undefined-behavior risks were introduced."
                ),
            },
            {
                "id": "verify.prompt.complexity_reduction",
                "type": "review_check",
                "statement": (
                    "Verify the refactoring reduced accidental complexity "
                    "without introducing over-abstraction."
                ),
            },
        ]
        if _is_cpp_context(self.context):
            checks.insert(
                2,
                {
                    "id": "verify.prompt.standard_availability",
                    "type": "review_check",
                    "statement": (
                        "Verify recommendations use facilities available in the "
                        "selected C++ standard."
                    ),
                },
            )
        if self.context.get("user_facing_api") or any(
            "api" in _rule_text(item) or "user" in _rule_text(item) for item in items
        ):
            checks.append(
                {
                    "id": "verify.prompt.api_usability",
                    "type": "review_check",
                    "statement": (
                        "Verify the resulting API requires fewer or clearer "
                        "user steps where applicable."
                    ),
                }
            )
        if any(
            "verification entrypoints" in _rule_text(item)
            or "verification commands" in _rule_text(item)
            or "low-cost tests" in _rule_text(item)
            or "checks that were not run" in _rule_text(item)
            for item in items
        ):
            checks.append(
                {
                    "id": "verify.prompt.execution_verification",
                    "type": "review_check",
                    "statement": (
                        "Verify relevant local checks were run when practical, "
                        "and report commands, results, and skipped checks."
                    ),
                }
            )
        return checks[:limit]

    def _collapse(self, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        remaining: list[dict[str, Any]] = []
        for rule in rules:
            group = _collapse_group(rule)
            if group is None:
                remaining.append(rule)
                continue
            groups.setdefault(group, _collapsed_rule(group, rule))
        return [*groups.values(), *remaining]

    def _collapse_verification(
        self, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        remaining: list[dict[str, Any]] = []
        for item in items:
            group = _collapse_group({"target": _verification_target(item), "id": item.get("rule", "")})
            if group is None:
                remaining.append(item)
                continue
            groups.setdefault(group, _collapsed_verification(group, item))
        return [*groups.values(), *remaining]

    def _limit(
        self,
        rules: list[dict[str, Any]],
        limit: int,
        scorer: "Callable[[dict[str, Any]], int]",
    ) -> list[dict[str, Any]]:
        indexed = list(enumerate(rules))
        indexed.sort(key=lambda item: (scorer(item[1]), -item[0]), reverse=True)
        return [item for _, item in indexed[:limit]]

    def _hard_score(self, rule: dict[str, Any]) -> int:
        text = _rule_text(rule)
        target = str(rule.get("target", ""))
        score = 0
        if self.git_workflow:
            score += {
                "local_changes": 140,
                "shared_history": 135,
                "clean_safety": 130,
                "clean_scope": 125,
                "conflict_resolution": 120,
                "branch_target": 115,
                "protected_branch": 110,
                "sensitive_content": 105,
                "commit_message": 100,
                "commit_scope": 95,
                "undo_strategy": 90,
            }.get(target, 0)
        if self.cmake_workflow:
            score += {
                "target_model": 150,
                "usage_requirements": 145,
                "compiler_selection": 140,
                "build_tree": 135,
                "relocatable_package": 130,
                "quality_tooling": 125,
                "generated_files": 120,
                "dependency_targets": 115,
            }.get(target, 0)
        if "observable behavior" in text or target == "behavior_preservation":
            score += 120
        if target in {"undefined_behavior", "standard_availability", "ownership", "resource_lifetime", "type_safety"}:
            score += 90
        if self.refinement and target in {"ownership", "resource_lifetime", "undefined_behavior", "standard_availability"}:
            score += 20
        return score

    def _soft_score(self, rule: dict[str, Any]) -> int:
        text = _rule_text(rule)
        target = str(rule.get("target", ""))
        source = str(rule.get("source", {}).get("skill", ""))
        score = 0
        if self.git_workflow:
            score += {
                "stash_workflow": 130,
                "stash_scope": 120,
                "clean_safety": 115,
                "clean_scope": 110,
                "conflict_resolution": 125,
                "review_readiness": 120,
                "review_title": 115,
                "review_scope": 110,
                "commit_scope": 115,
                "commit_message": 110,
                "commit_message_format": 105,
                "staged_diff": 100,
                "commit_verification": 95,
                "branch_structure": 100,
                "branch_naming": 95,
                "synchronization": 85,
                "integration_strategy": 80,
                "release_branch": 75,
                "force_push": 90,
                "rewrite_scope": 85,
                "reset_semantics": 80,
                "working_tree": 70,
                "repository_state": 65,
                "staging": 60,
            }.get(target, 0)
            for needle in (
                "dry-run",
                "explicit user approval",
                "unfinished work",
                "staged diff",
                "only relevant commits",
                "pull request title",
                "blindly choosing ours or theirs",
                "force-with-lease",
                "published",
                "shared",
            ):
                if needle in text:
                    score += 20
        if self.cmake_workflow:
            score += {
                "target_model": 140,
                "usage_requirements": 135,
                "source_lists": 95,
                "generated_files": 75,
                "language_standard": 120,
                "compiler_options": 115,
                "warnings_policy": 105,
                "generator_compatibility": 100,
                "dependency_targets": 130,
                "dependency_reproducibility": 120,
                "dependency_strategy": 105,
                "package_discovery": 100,
                "relocatable_package": 125,
                "install_export": 120,
                "package_config": 115,
                "presets": 125,
                "workflow_reproducibility": 120,
                "toolchain": 115,
                "testing": 125,
                "test_discovery": 110,
                "quality_tooling": 125,
                "project_options": 95,
                "cmake_modules": 90,
                "custom_commands": 90,
                "target_naming": 85,
                "project_structure": 80,
                "global_state": 75,
            }.get(target, 0)
            if self.context.get("cmake_target_model_requested"):
                score += {
                    "target_model": 90,
                    "target_naming": 85,
                    "usage_requirements": 70,
                    "project_structure": 30,
                    "global_state": 25,
                }.get(target, 0)
            if self.context.get("cmake_usage_requirements_requested"):
                score += {
                    "usage_requirements": 105,
                    "target_naming": 75,
                    "dependency_targets": 55,
                    "target_model": 40,
                }.get(target, 0)
            if self.context.get("cmake_compiler_options_requested"):
                score += {
                    "language_standard": 110,
                    "compiler_options": 105,
                    "warnings_policy": 90,
                    "generator_compatibility": 80,
                }.get(target, 0)
            if self.context.get("cmake_source_management_requested"):
                score += {
                    "source_lists": 130,
                }.get(target, 0)
            if self.context.get("cmake_generated_files_requested"):
                score += {
                    "generated_files": 125,
                    "custom_commands": 65,
                    "source_lists": 35,
                }.get(target, 0)
            if self.context.get("cmake_options_modules_requested"):
                score += {
                    "project_options": 95,
                    "cmake_modules": 85,
                    "custom_commands": 75,
                    "generated_files": 35,
                }.get(target, 0)
            if self.context.get("cmake_dependency_requested"):
                score += {
                    "dependency_targets": 115,
                    "dependency_reproducibility": 100,
                    "dependency_strategy": 90,
                    "package_discovery": 80,
                }.get(target, 0)
            if self.context.get("cmake_distribution_requested"):
                score += {
                    "relocatable_package": 115,
                    "install_export": 105,
                    "package_config": 95,
                }.get(target, 0)
            if self.context.get("cmake_presets_requested"):
                score += {
                    "presets": 115,
                    "workflow_reproducibility": 95,
                    "toolchain": 45,
                }.get(target, 0)
            if self.context.get("cmake_toolchain_requested"):
                score += {"toolchain": 105, "presets": 45}.get(target, 0)
            if self.context.get("cmake_testing_requested"):
                score += {"testing": 115, "test_discovery": 95}.get(target, 0)
            if self.context.get("cmake_quality_requested"):
                score += {"quality_tooling": 115, "workflow_reproducibility": 45}.get(target, 0)
            for needle in (
                "target",
                "public",
                "private",
                "interface",
                "generator expressions",
                "out of source",
                "find_package",
                "imported targets",
                "fetchcontent",
                "ctest",
                "presets",
                "relocatable",
            ):
                if needle in text:
                    score += 15
        if self.refinement:
            target_bonus = {
                "complexity": 90,
                "component_structure": 80,
                "duplication": 75,
                "abstraction": 75,
                "parameterized_abstraction": 70,
                "api_usability": 65,
                "implementation_polish": 55,
                "implementation_expression": 50,
                "hierarchy": 45,
                "dependency_direction": 45,
                "source_structure": 35,
            }
            score += target_bonus.get(target, 0)
            if target == "parameterized_abstraction" and self.context.get(
                "similar_logic_with_small_variation"
            ):
                score += 90
            if target == "api_usability" and self.context.get("user_facing_api"):
                score += 45
            if target == "component_structure" and self.context.get(
                "scattered_related_logic"
            ):
                score += 45
            if target in {"hierarchy", "dependency_direction"} and self.context.get(
                "unclear_hierarchy"
            ):
                score += 45
                if "clarify component hierarchy" in text:
                    score += 160
                if "circular" in text or "cycle" in text:
                    score += 200
            for needle in (
                "accidental complexity",
                "effective complexity",
                "related variables",
                "responsibility clear",
                "overhead without improving",
                "dependency direction",
                "language-native",
                "headers self-contained",
                "unnecessary includes",
                "common case",
                "public contract",
                "boundary conditions",
                "duplicated",
            ):
                if needle in text:
                    score += 40
            if source.startswith("generic."):
                score += 35
            if (
                target == "parameterized_abstraction"
                and self.context.get("unclear_hierarchy")
                and not self.context.get("duplicated_logic")
            ):
                score -= 80
            if target in {"undefined_behavior", "ownership", "resource_lifetime", "type_safety", "bounds_safety"}:
                score += 15
        if source.startswith("cpp.source_structure"):
            score += 20
        if target == "verification":
            score += 70
            for needle in (
                "test",
                "warning",
                "static analysis",
                "sanitizer",
                "fuzz",
                "ci",
                "compiler",
                "build",
                "package",
            ):
                if needle in text:
                    score += 10
        return score

    def _preference_score(self, rule: dict[str, Any]) -> int:
        text = _rule_text(rule)
        target = str(rule.get("target", ""))
        score = 0
        if self.git_workflow:
            score += {
                "stash_workflow": 110,
                "review_scope": 105,
                "commit_scope": 100,
                "undo_strategy": 95,
                "branch_structure": 90,
                "staging": 80,
            }.get(target, 0)
        if self.cmake_workflow:
            score += {
                "target_model": 120,
                "usage_requirements": 115,
                "source_lists": 110,
                "compiler_options": 105,
                "dependency_targets": 105,
                "relocatable_package": 100,
                "presets": 100,
                "quality_tooling": 95,
            }.get(target, 0)
        if self.refinement:
            score += {
                "complexity": 90,
                "duplication": 80,
                "implementation_polish": 70,
                "api_usability": 65,
                "component_structure": 45,
                "hierarchy": 40,
                "implementation_expression": 35,
                "parameterized_abstraction": 30,
            }.get(target, 0)
            if target == "parameterized_abstraction" and self.context.get(
                "similar_logic_with_small_variation"
            ):
                score += 90
            if (
                target == "parameterized_abstraction"
                and self.context.get("unclear_hierarchy")
                and not self.context.get("duplicated_logic")
            ):
                score -= 80
        for needle in (
            "effective_complexity",
            "shared_responsibility",
            "finished_component",
            "simple_common_case",
            "cohesive_component",
            "clear_call_chain",
            "clarity",
            "safety",
            "standard_vocabulary_type",
        ):
            if needle in text:
                score += 50
        return score

    def _verification_score(self, item: dict[str, Any]) -> int:
        text = _rule_text(item)
        score = 0
        if "observable behavior" in text:
            score += 120
        for needle in (
            "ownership",
            "lifetime",
            "resource",
            "undefined",
            "standard",
            "abstraction",
            "api",
            "test",
            "warning",
            "static analysis",
            "sanitizer",
            "fuzz",
            "ci",
            "compiler",
            "build",
            "package",
        ):
            if needle in text:
                score += 30
        return score


class RuleEffectiveMapper:
    """Map internal Rule IR objects into effective-rules schema entries."""

    def rule(self, rule: Rule) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": rule.id,
            "target": rule.target,
            "action": rule.action.value.lower(),
            "statement": _statement(rule),
            "source": {"skill": rule.source, "rule": rule.id},
        }
        if rule.condition:
            data["condition"] = rule.condition
        if rule.requires:
            data["requirements"] = list(rule.requires)
        if rule.unless:
            data["exceptions"] = [rule.unless]
        return data

    def preference(self, rule: Rule) -> dict[str, Any]:
        data = self.rule(rule)
        data["action"] = "prefer"
        prefer, over = _split_preference(rule)
        if prefer:
            data["prefer"] = prefer
        if over:
            data["over"] = over
        return data

    def exception(self, rule: Rule) -> dict[str, Any]:
        return {
            "id": rule.id,
            "condition": rule.condition,
            "allow": [rule.value],
            "require": list(rule.requires),
            "source": {"skill": rule.source, "rule": rule.id},
        }

    def verification(
        self, rules: EffectiveRules
    ) -> dict[str, list[dict[str, Any]]]:
        required = [
            {
                "id": f"verify.{rule.id}",
                "type": "policy_check",
                "statement": f"Verify: {_statement(rule)}",
                "rule": rule.id,
            }
            for rule in rules.hard
        ]
        recommended = [
            {
                "id": f"verify.{rule.id}",
                "type": "review_check",
                "statement": f"Review: {_statement(rule)}",
                "rule": rule.id,
            }
            for rule in rules.soft
            if rule.verification
        ]
        return {"required": required, "recommended": recommended}


def _task_context(task: TaskContext) -> dict[str, Any]:
    return {
        **task.context,
        "domain": task.domain,
        "task_type": task.task_type,
        "capabilities": list(task.capabilities),
        "tags": list(task.tags),
    }


def _collapse_group(rule: dict[str, Any]) -> str | None:
    target = str(rule.get("target", ""))
    rule_id = str(rule.get("id", ""))
    text = _rule_text(rule)
    if target == "undefined_behavior" or "undefined behavior" in text:
        return "undefined_behavior"
    if target in {"ownership", "resource_lifetime"} and (
        "leak" in text or "resource" in text
    ):
        return "resource_safety"
    if target in {"resource_lifetime", "dangling_reference"} or any(
        needle in text for needle in ("dangling", "local object", "valid lifetime")
    ):
        return "lifetime_safety"
    if target == "type_safety" and any(
        needle in text for needle in ("cast", "type system", "aliasing")
    ):
        return "type_safety"
    if target == "standard_availability":
        return "standard_availability"
    if "no_unsafe_cast" in rule_id or "no_invalid_cast" in rule_id:
        return "type_safety"
    return None


def _collapsed_rule(group: str, rule: dict[str, Any]) -> dict[str, Any]:
    statements = {
        "undefined_behavior": "Avoid undefined behavior.",
        "resource_safety": "Do not introduce resource leaks.",
        "lifetime_safety": "Preserve ownership and lifetime safety.",
        "type_safety": "Avoid invalid or unsafe casts that bypass type and lifetime safety.",
        "standard_availability": "Do not use facilities unavailable in the selected C++ standard.",
    }
    data = dict(rule)
    data["id"] = f"prompt.{group}"
    data["target"] = group
    data["statement"] = statements[group]
    return data


def _collapsed_verification(group: str, item: dict[str, Any]) -> dict[str, Any]:
    statements = {
        "undefined_behavior": "Verify no undefined behavior was introduced.",
        "resource_safety": "Verify no new ownership, resource, or cleanup issues were introduced.",
        "lifetime_safety": "Verify no new lifetime or dangling-reference issues were introduced.",
        "type_safety": "Verify no invalid or unsafe casts were introduced.",
        "standard_availability": "Verify recommendations use facilities available in the selected C++ standard.",
    }
    data = dict(item)
    data["id"] = f"verify.prompt.{group}"
    data["statement"] = statements[group]
    return data


def _verification_target(item: dict[str, Any]) -> str:
    statement = _rule_text(item)
    if "undefined behavior" in statement:
        return "undefined_behavior"
    if any(needle in statement for needle in ("lifetime", "dangling", "local object")):
        return "resource_lifetime"
    if any(needle in statement for needle in ("resource", "leak", "ownership")):
        return "ownership"
    if "cast" in statement:
        return "type_safety"
    if "standard" in statement:
        return "standard_availability"
    return ""


def _is_cpp_context(context: dict[str, Any]) -> bool:
    return (
        context.get("domain") == "cpp"
        or context.get("language") == "cpp"
        or "standard" in context
    )


def _rule_text(rule: dict[str, Any]) -> str:
    return str(rule.get("statement", rule.get("id", ""))).strip().lower()


def _sentence(value: Any) -> str:
    text = " ".join(str(value).strip().split())
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _sanitize_markdown(text: str) -> str:
    # Defense against terminals or upstream text that accidentally collapse bullets.
    return text.replace(".- ", ".\n- ")


def _statement(rule: Rule) -> str:
    return rule.description or str(rule.value)


def _split_preference(rule: Rule) -> tuple[str | None, str | None]:
    if rule.over:
        return str(rule.value).split(" > ", 1)[0], str(rule.over[0])
    if isinstance(rule.value, str) and " > " in rule.value:
        prefer, over = rule.value.split(" > ", 1)
        return prefer, over
    return str(rule.value) if rule.value is not None else None, None


def _preference_prompt_statement(rule: dict[str, Any]) -> str:
    prefer = rule.get("prefer")
    over = rule.get("over")
    if prefer and over:
        return f"Prefer {_humanize_token(prefer)} over {_humanize_token(over)}."
    statement = str(rule.get("statement", "")).strip()
    if " > " in statement:
        prefer, over = statement.split(" > ", 1)
        return f"Prefer {_humanize_token(prefer)} over {_humanize_token(over)}."
    return statement if statement.endswith((".", "!", "?")) else f"{statement}."


def _humanize_token(value: Any) -> str:
    text = str(value).strip()
    return text.replace("_", " ").replace("-", " ")


def _label(key: str) -> str:
    return key.replace("_", " ").title()


def _format_context_value(key: str, value: Any) -> str:
    if key == "language" and value == "cpp":
        return "C++"
    if key == "standard" and value:
        return f"C++{value}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _to_simple_yaml(data: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(data, dict):
        return "\n".join(
            f"{prefix}{key}:\n{_to_simple_yaml(value, indent + 2)}"
            if isinstance(value, (dict, list))
            else f"{prefix}{key}: {_scalar(value)}"
            for key, value in data.items()
        )
    if isinstance(data, list):
        if not data:
            return f"{prefix}[]"
        return "\n".join(
            f"{prefix}-\n{_to_simple_yaml(item, indent + 2)}"
            if isinstance(item, (dict, list))
            else f"{prefix}- {_scalar(item)}"
            for item in data
        )
    return f"{prefix}{_scalar(data)}"


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)
