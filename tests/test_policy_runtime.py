from __future__ import annotations

import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from ai_policy_runtime import PolicyEngine, Skill, SkillRegistry, TaskContext
from ai_policy_runtime.application.runtime import PolicyRuntime
from ai_policy_runtime.domain.config import RuntimeConfig
from ai_policy_runtime.domain.pack import PackRegistry, SkillPack
from ai_policy_runtime.domain.rule import RuleAction
from ai_policy_runtime.task_analysis import TaskAnalyzer
from ai_policy_runtime.task_analysis.embeddings import HashingTextEmbeddingProvider, cosine_similarity
from ai_policy_runtime.task_analysis.lexicon import LexiconRule, TaskLexicon
from ai_policy_runtime.task_analysis.semantic_index import SemanticTaskIndex
from ai_policy_runtime.adapters.codex.wrapper import _build_codex_command
from ai_policy_runtime.adapters.claude.wrapper import _build_claude_command
from ai_policy_runtime.services.project_context import (
    ProjectContextAnalyzer,
    merge_project_analysis,
)
from ai_policy_runtime.services.analyzer import analyze
from ai_policy_runtime.services.effective_rules import EffectiveRulesRenderer
from ai_policy_runtime.services.engine import PolicyConflictError
from ai_policy_runtime.services.injector import BEGIN, END, inject_current_prompt
from ai_policy_runtime.services.validator import validate_effective_rules_mapping
from ai_policy_runtime.services.verification import FileVerifier, Violation, verify_rules


class KeywordConceptEmbeddingProvider:
    """Small deterministic embedding provider for semantic-index tests."""

    _CONCEPTS = (
        ("cpp", ("c++", "cpp", "native code")),
        ("write", ("写", "create", "generate", "implementation", "build")),
        ("latency", ("尾延迟", "latency", "延迟", "hot path", "critical path")),
        ("allocation", ("分配", "allocation", "blocking", "阻塞", "unbounded")),
        ("queue", ("队列", "queue", "data channel", "buffer", "producer consumer")),
    )

    def encode(self, texts: list[str] | tuple[str, ...]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            vectors.append(
                [
                    1.0 if any(token in lowered for token in tokens) else 0.0
                    for _, tokens in self._CONCEPTS
                ]
            )
        return vectors


class CountingEmbeddingProvider(KeywordConceptEmbeddingProvider):
    def __init__(self) -> None:
        self.calls = 0

    def encode(self, texts: list[str] | tuple[str, ...]) -> list[list[float]]:
        self.calls += 1
        return super().encode(texts)


class AlwaysViolationVerifier:
    def supports(self, rule: dict[str, object]) -> bool:
        return True

    def verify(self, rule: dict[str, object], path: Path) -> list[Violation]:
        return [
            Violation(
                rule_id=str(rule.get("id", "")),
                severity="error",
                path=str(path),
                line=1,
                message="custom verifier violation",
            )
        ]


class PolicyRuntimeTests(unittest.TestCase):
    def test_task_analyzer_understands_cpp20_low_latency_queue(self) -> None:
        analysis = analyze("帮我写一个 C++20 低延迟队列")
        task = analysis.task

        self.assertGreaterEqual(analysis.confidence, 0.72)
        self.assertFalse(analysis.needs_review)
        self.assertEqual(task.domain, "cpp")
        self.assertEqual(task.task_type, "write_code")
        self.assertEqual(task.context["language"], "cpp")
        self.assertEqual(task.context["standard"], 20)
        self.assertTrue(task.context["hot_path"])
        self.assertTrue(task.context["performance_critical"])
        self.assertEqual(task.context["data_structure"], "queue")
        self.assertEqual(task.context["scenario"], "low_latency_queue")
        self.assertIn("cpp20", task.tags)
        self.assertIn("low_latency", task.tags)
        self.assertIn("code_generation", task.capabilities)

    def test_task_analyzer_extracts_matching_engine_scenario(self) -> None:
        task = analyze("为低延迟撮合引擎写一段 C++20 代码").task

        self.assertEqual(task.domain, "cpp")
        self.assertEqual(task.context["standard"], 20)
        self.assertEqual(task.context["scenario"], "matching_engine")
        self.assertIn("trading", task.tags)
        self.assertIn("systems_programming", task.tags)

    def test_task_analyzer_extracts_cpp20_api_span_intent(self) -> None:
        task = analyze("设计一个 C++20 API，参数是连续范围，优先使用 span").task

        self.assertEqual(task.task_type, "design_api")
        self.assertEqual(task.context["standard"], 20)
        self.assertTrue(task.context["designing_api"])
        self.assertEqual(task.context["parameter_kind"], "contiguous_range")
        self.assertFalse(task.context["ownership_required"])
        self.assertIn("api_design", task.capabilities)

    def test_task_analyzer_marks_ambiguous_input_for_review(self) -> None:
        analysis = analyze("帮我处理一下这个问题")

        self.assertEqual(analysis.task.domain, "general")
        self.assertEqual(analysis.task.task_type, "unknown")
        self.assertTrue(analysis.needs_review)
        self.assertLess(analysis.confidence, 0.72)

    def test_task_analyzer_uses_embedding_semantics_for_rephrased_intent(self) -> None:
        analyzer = TaskAnalyzer.from_skills_dir(
            "skills",
            embeddings=KeywordConceptEmbeddingProvider(),
        )

        analysis = analyzer.analyze("写一个 C++20 数据通道，主循环里不能有分配和阻塞，尾延迟要稳")
        task = analysis.task

        self.assertEqual(task.domain, "cpp")
        self.assertEqual(task.task_type, "write_code")
        self.assertTrue(task.context["hot_path"])
        self.assertTrue(task.context["performance_critical"])
        self.assertIn("low_latency", task.tags)
        self.assertTrue(
            any(":semantic:" in item.source for item in analysis.evidence),
            [item.source for item in analysis.evidence],
        )

    def test_semantic_index_reuses_cached_vectors(self) -> None:
        lexicon = TaskLexicon(
            context_rules=(
                LexiconRule(
                    field="context.hot_path",
                    value=True,
                    phrases=(),
                    confidence=0.9,
                    source="test",
                    set_context={"hot_path": True},
                    semantic_texts=("tail latency must remain stable",),
                ),
            )
        )
        provider = CountingEmbeddingProvider()
        with TemporaryDirectory() as tmp:
            SemanticTaskIndex(lexicon, provider, cache_dir=tmp)
            SemanticTaskIndex(lexicon, provider, cache_dir=tmp)

        self.assertEqual(provider.calls, 1)

    def test_hashing_embedding_provider_supports_lightweight_semantic_similarity(self) -> None:
        provider = HashingTextEmbeddingProvider()
        stable_tail_latency, unrelated = provider.encode(
            (
                "尾延迟保持稳定",
                "write a formal markdown document",
            )
        )
        query = provider.encode(("尾延迟要稳定",))[0]

        self.assertGreater(
            cosine_similarity(query, stable_tail_latency),
            cosine_similarity(query, unrelated),
        )

    def test_runtime_explain_returns_task_analysis_without_current_state(self) -> None:
        runtime = PolicyRuntime(RuntimeConfig.from_values(root="."))
        result = runtime.explain("帮我写一个 C++20 低延迟队列").to_dict()

        self.assertEqual(result["task"]["domain"], "cpp")
        self.assertEqual(result["task"]["context"]["standard"], 20)
        self.assertFalse(result["needs_review"])
        self.assertTrue(result["evidence"])
        self.assertIn("project_context", result)

    def test_project_context_reads_cmake_standard(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.24)\n"
                "project(demo LANGUAGES CXX)\n"
                "target_compile_features(demo PRIVATE cxx_std_20)\n",
                encoding="utf-8",
            )

            analysis = ProjectContextAnalyzer(root).analyze()

        self.assertEqual(analysis.fact("domain").value, "cpp")
        self.assertEqual(analysis.context()["language"], "cpp")
        self.assertEqual(analysis.context()["standard"], 20)
        self.assertTrue(analysis.context()["selected_standard_is_known"])

    def test_project_context_prefers_compile_commands_over_cmake_default(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CMakeLists.txt").write_text(
                "set(CMAKE_CXX_STANDARD 17)\n",
                encoding="utf-8",
            )
            (root / "compile_commands.json").write_text(
                json.dumps(
                    [
                        {
                            "directory": str(root),
                            "file": "main.cpp",
                            "command": "clang++ -std=c++20 -c main.cpp",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            analysis = ProjectContextAnalyzer(root).analyze()

        self.assertEqual(analysis.context()["standard"], 20)
        self.assertIn("compile_commands.json", analysis.fact("context.standard").source)

    def test_project_context_detects_generic_project_tooling(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".clang-format").write_text("BasedOnStyle: LLVM\n", encoding="utf-8")
            (root / "pyproject.toml").write_text(
                '[project]\n'
                'requires-python = ">=3.10"\n'
                "\n"
                "[tool.ruff]\n"
                "line-length = 100\n",
                encoding="utf-8",
            )

            analysis = ProjectContextAnalyzer(root).analyze()
            context = analysis.context()

        self.assertEqual(analysis.primary_language, "python")
        self.assertTrue(context["has_clang_format"])
        self.assertTrue(context["has_ruff"])
        self.assertEqual(context["python_requires"], ">=3.10")

    def test_project_context_yaml_overrides_detected_facts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".policy").mkdir()
            (root / ".policy" / "project.yaml").write_text(
                "domain: cpp\n"
                "context:\n"
                "  standard: 23\n"
                "  hot_path: true\n"
                "tags:\n"
                "  - low_latency\n",
                encoding="utf-8",
            )
            (root / "CMakeLists.txt").write_text(
                "set(CMAKE_CXX_STANDARD 17)\n",
                encoding="utf-8",
            )

            analysis = ProjectContextAnalyzer(root).analyze()

        self.assertEqual(analysis.context()["standard"], 23)
        self.assertTrue(analysis.context()["hot_path"])
        self.assertIn("low_latency", analysis.tags())

    def test_project_context_merges_missing_standard_without_overriding_prompt(self) -> None:
        task_analysis = analyze("帮我写一个 C++17 队列")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "compile_commands.json").write_text(
                json.dumps(
                    [
                        {
                            "directory": str(root),
                            "file": "main.cpp",
                            "command": "clang++ -std=c++20 -c main.cpp",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            project = ProjectContextAnalyzer(root).analyze()
            merged = merge_project_analysis(task_analysis, project)

        self.assertEqual(merged.task.context["standard"], 17)
        self.assertEqual(merged.task.domain, "cpp")

    def test_runtime_uses_target_project_root_separate_from_policy_root(self) -> None:
        with TemporaryDirectory() as tmp:
            target = Path(tmp)
            (target / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.24)\n"
                "project(external LANGUAGES CXX)\n"
                "set(CMAKE_CXX_STANDARD 20)\n",
                encoding="utf-8",
            )
            runtime = PolicyRuntime(
                RuntimeConfig.from_values(root=target, policy_root=".")
            )

            result = runtime.resolve("帮我写一个低延迟队列", ("cpp.low_latency",))

            self.assertEqual(result.current, target / ".policy" / "current")
            context = result.structured["effective_rules"]["task"]["context"]
            self.assertEqual(context["domain"], "cpp")
            self.assertEqual(context["standard"], 20)
            self.assertTrue((target / ".policy" / "current" / "project-context.json").exists())

    def test_activates_dependencies_and_keeps_conditional_exception(self) -> None:
        registry = SkillRegistry(
            [
                Skill.from_mapping(
                    {
                        "skill_id": "cpp.safe",
                        "name": "C++ Safe",
                        "domains": ["cpp"],
                        "triggers": ["write_code"],
                        "capabilities": ["code_generation"],
                        "rules": {
                            "soft": [
                                {
                                    "id": "avoid_raw",
                                    "target": "raw_pointer",
                                    "action": "FORBID",
                                    "value": "raw_pointer",
                                    "description": "Avoid raw pointers.",
                                }
                            ]
                        },
                    }
                ),
                Skill.from_mapping(
                    {
                        "skill_id": "cpp.hot_path",
                        "name": "C++ Hot Path",
                        "domains": ["cpp"],
                        "triggers": ["write_code"],
                        "capabilities": ["code_generation"],
                        "tags": ["hot_path"],
                        "dependencies": ["cpp.safe"],
                        "exceptions": [
                            {
                                "when": "hot_path == true",
                                "allow": [
                                    {
                                        "id": "allow_raw_hot_path",
                                        "target": "raw_pointer",
                                        "action": "ALLOW",
                                        "value": "raw_pointer",
                                        "description": "Allow raw pointers in hot paths.",
                                    }
                                ],
                                "require": ["justification"],
                            }
                        ],
                    }
                ),
            ]
        )
        task = TaskContext(
            domain="cpp",
            task_type="write_code",
            capabilities=("code_generation",),
            tags=("hot_path",),
            context={"hot_path": True},
        )

        effective = PolicyEngine(registry).evaluate(task)

        self.assertEqual([rule.id for rule in effective.soft], ["avoid_raw"])
        self.assertEqual([rule.id for rule in effective.exceptions], ["allow_raw_hot_path"])
        self.assertEqual(effective.exceptions[0].requires, ("justification",))

    def test_hard_conflict_fails(self) -> None:
        registry = SkillRegistry(
            [
                Skill.from_mapping(
                    {
                        "skill_id": "a",
                        "name": "A",
                        "domains": ["cpp"],
                        "triggers": ["write_code"],
                        "rules": {
                            "hard": [
                                {
                                    "id": "must_x",
                                    "target": "api",
                                    "action": "REQUIRE",
                                    "value": "x",
                                }
                            ]
                        },
                    }
                ),
                Skill.from_mapping(
                    {
                        "skill_id": "b",
                        "name": "B",
                        "domains": ["cpp"],
                        "triggers": ["write_code"],
                        "rules": {
                            "hard": [
                                {
                                    "id": "forbid_x",
                                    "target": "api",
                                    "action": "FORBID",
                                    "value": "x",
                                }
                            ]
                        },
                    }
                ),
            ]
        )
        task = TaskContext(domain="cpp", task_type="write_code")

        with self.assertRaises(PolicyConflictError):
            PolicyEngine(registry).evaluate(task)

    def test_canonical_skill_dsl_shape_and_activation_condition(self) -> None:
        skill = Skill.from_mapping(
            {
                "kind": "skill",
                "api_version": "policy.skill/v1",
                "skill": {
                    "id": "cpp.dsl.canonical",
                    "name": "Canonical C++ DSL",
                    "version": "1.0.0",
                    "level": "DOMAIN",
                    "priority": 70,
                    "status": "stable",
                },
                "scope": {
                    "domains": ["cpp"],
                    "triggers": ["write_code"],
                    "capabilities": ["code_generation"],
                },
                "activation": {"when": 'language == "cpp" and standard >= 20'},
                "rules": {
                    "hard": [
                        {
                            "id": "no_ub",
                            "must_not": "undefined_behavior",
                            "target": "behavior.undefined",
                            "reason": "Undefined behavior is not acceptable.",
                        }
                    ],
                    "soft": [
                        {
                            "id": "prefer_raii",
                            "should": "raii",
                            "target": "resource_management",
                        }
                    ],
                    "preference": [
                        {
                            "id": "prefer_safety",
                            "prefer": {"higher": "safety", "lower": "performance"},
                            "target": "decision.optimization",
                        }
                    ],
                },
            }
        )
        registry = SkillRegistry([skill])
        task = TaskContext(
            domain="cpp",
            task_type="write_code",
            capabilities=("code_generation",),
            context={"language": "cpp", "standard": 20},
        )

        effective = PolicyEngine(registry).evaluate(task)

        self.assertEqual(effective.hard[0].action, RuleAction.FORBID)
        self.assertEqual(effective.soft[0].action, RuleAction.RECOMMEND)
        self.assertEqual(effective.preferences[0].value, "safety > performance")

    def test_activation_condition_filters_skill(self) -> None:
        skill = Skill.from_mapping(
            {
                "kind": "skill",
                "api_version": "policy.skill/v1",
                "skill": {
                    "id": "cpp20.only",
                    "name": "C++20 Only",
                    "version": "1.0.0",
                    "level": "DOMAIN",
                    "priority": 10,
                },
                "scope": {"domains": ["cpp"], "triggers": ["write_code"]},
                "activation": {"when": "standard >= 20"},
                "rules": {
                    "hard": [
                        {
                            "id": "requires_cpp20",
                            "must": "cpp20",
                            "target": "language_standard",
                        }
                    ],
                    "soft": [],
                    "preference": [],
                },
            }
        )
        registry = SkillRegistry([skill])

        effective = PolicyEngine(registry).evaluate(
            TaskContext(
                domain="cpp",
                task_type="write_code",
                context={"language": "cpp", "standard": 17},
            )
        )

        self.assertEqual(effective.hard, [])

    def test_pack_expansion_includes_parent_and_overrides(self) -> None:
        base = Skill.from_mapping(
            {
                "skill": {
                    "id": "cpp.base",
                    "name": "Base",
                    "version": "1.0.0",
                    "level": "domain",
                    "domain": "cpp",
                    "priority": 10,
                    "activation": {"when": {"language": "cpp"}},
                    "capabilities": ["code_generation"],
                },
                "rules": {
                    "hard": [
                        {"id": "base_rule", "must": "modern_cpp", "target": "base"}
                    ]
                },
            }
        )
        hot = Skill.from_mapping(
            {
                "skill": {
                    "id": "cpp.hot",
                    "name": "Hot",
                    "version": "1.0.0",
                    "level": "domain",
                    "domain": "cpp",
                    "priority": 10,
                    "activation": {"when": {"language": "cpp"}},
                    "capabilities": ["code_generation"],
                },
                "rules": {
                    "soft": [
                        {"id": "hot_rule", "should": "avoid_alloc", "target": "alloc"}
                    ]
                },
            }
        )
        packs = PackRegistry(
            [
                SkillPack.from_mapping(
                    {
                        "pack": {"id": "cpp.safe", "name": "Safe"},
                        "includes": ["cpp.base"],
                    }
                ),
                SkillPack.from_mapping(
                    {
                        "pack": {"id": "cpp.low", "name": "Low"},
                        "extends": ["cpp.safe"],
                        "includes": ["cpp.hot"],
                        "overrides": [
                            {
                                "id": "hot_preference",
                                "when": "hot_path == true",
                                "prefer": "performance",
                                "over": "readability",
                                "target": "tradeoff",
                            }
                        ],
                    }
                ),
            ]
        )
        registry = SkillRegistry([base, hot], packs)
        task = TaskContext(
            domain="cpp",
            task_type="write_code",
            capabilities=("code_generation",),
            context={"language": "cpp", "hot_path": True},
        )

        effective = PolicyEngine(registry).evaluate(task, ("cpp.low",))

        self.assertEqual([rule.id for rule in effective.hard], ["base_rule"])
        self.assertIn("hot_rule", [rule.id for rule in effective.soft])
        self.assertIn("hot_preference", [rule.id for rule in effective.preferences])

    def test_rule_unless_filters_and_ir_metadata_is_preserved(self) -> None:
        skill = Skill.from_mapping(
            {
                "skill": {
                    "id": "cpp.metadata",
                    "name": "Metadata",
                    "version": "1.0.0",
                    "level": "domain",
                    "domain": "cpp",
                    "priority": 10,
                    "activation": {"when": {"language": "cpp"}},
                    "capabilities": ["code_generation"],
                },
                "rules": {
                    "soft": [
                        {
                            "id": "prefer_span",
                            "when": "standard >= 20",
                            "unless": "abi_boundary == true",
                            "should": "Prefer std::span.",
                            "target": "range",
                            "prefer": "std::span",
                            "over": ["pointer_and_size"],
                            "rationale": "std::span expresses bounds.",
                            "examples": ["span<const int>"],
                        }
                    ]
                },
            }
        )
        registry = SkillRegistry([skill])
        blocked = PolicyEngine(registry).evaluate(
            TaskContext(
                domain="cpp",
                task_type="write_code",
                capabilities=("code_generation",),
                context={"language": "cpp", "standard": 20, "abi_boundary": True},
            )
        )
        allowed = PolicyEngine(registry).evaluate(
            TaskContext(
                domain="cpp",
                task_type="write_code",
                capabilities=("code_generation",),
                context={"language": "cpp", "standard": 20, "abi_boundary": False},
            )
        )

        self.assertEqual(blocked.soft, [])
        self.assertEqual(allowed.soft[0].over, ("pointer_and_size",))
        self.assertIn("rationale", allowed.soft[0].to_dict())

    def test_verify_rules_reports_forbidden_text(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.cpp"
            path.write_text("int undefined_behavior = 0;\n", encoding="utf-8")

            violations = verify_rules(
                [
                    {
                        "id": "no_ub",
                        "action": "FORBID",
                        "value": "undefined_behavior",
                    }
                ],
                path,
            )

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "no_ub")

    def test_file_verifier_accepts_custom_verifier_plugins(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.cpp"
            path.write_text("int main() {}\n", encoding="utf-8")
            violations = FileVerifier([AlwaysViolationVerifier()]).verify_rules(
                [{"id": "custom"}],
                path,
            )

        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].message, "custom verifier violation")

    def test_file_verifier_supports_regex_and_required_text(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.cpp"
            path.write_text("int * raw = nullptr;\n", encoding="utf-8")
            violations = FileVerifier().verify_rules(
                [
                    {"id": "no_raw_ptr", "action": "forbid", "pattern": r"\w+\s*\*"},
                    {"id": "require_raii", "action": "require", "value": "RAII"},
                ],
                path,
            )

        self.assertEqual({item.rule_id for item in violations}, {"no_raw_ptr", "require_raii"})

    def test_inject_preserves_manual_content_and_replaces_block(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            current = root / ".policy" / "current"
            current.mkdir(parents=True)
            (current / "effective-prompt.md").write_text("HARD:\n- A\n", encoding="utf-8")
            agents = root / "AGENTS.md"
            agents.write_text("# Manual\n\nKeep me.\n", encoding="utf-8")

            inject_current_prompt(root, "codex")
            (current / "effective-prompt.md").write_text("HARD:\n- B\n", encoding="utf-8")
            inject_current_prompt(root, "codex")

            text = agents.read_text(encoding="utf-8")

        self.assertIn("Keep me.", text)
        self.assertIn("- B", text)
        self.assertNotIn("- A", text)
        self.assertEqual(text.count(BEGIN), 1)
        self.assertEqual(text.count(END), 1)

    def test_codex_wrapper_builds_command_with_task_last(self) -> None:
        command = _build_codex_command(
            ("codex",),
            ("--approval-mode", "never"),
            "帮我写一个 C++20 低延迟队列",
        )

        self.assertEqual(
            command,
            (
                "codex",
                "--approval-mode",
                "never",
                "帮我写一个 C++20 低延迟队列",
            ),
        )

    def test_claude_wrapper_builds_command_with_task_last(self) -> None:
        command = _build_claude_command(
            ("claude",),
            ("--dangerously-skip-permissions",),
            "帮我写一个 C++20 低延迟队列",
        )

        self.assertEqual(
            command,
            (
                "claude",
                "--dangerously-skip-permissions",
                "帮我写一个 C++20 低延迟队列",
            ),
        )

    def test_effective_rules_renderer_matches_output_spec(self) -> None:
        skill = Skill.from_mapping(
            {
                "skill": {
                    "id": "cpp.render",
                    "name": "Render",
                    "version": "1.0.0",
                    "level": "domain",
                    "domain": "cpp",
                    "priority": 10,
                    "activation": {"when": {"language": "cpp"}},
                    "capabilities": ["code_generation"],
                },
                "rules": {
                    "hard": [
                        {
                            "id": "no_ub",
                            "must_not": "undefined_behavior",
                            "target": "undefined_behavior",
                            "reason": "Avoid undefined behavior.",
                        }
                    ],
                    "preference": [
                        {
                            "id": "prefer_safety",
                            "prefer": "safety",
                            "over": "performance",
                            "target": "decision_priority",
                        }
                    ],
                },
            }
        )
        task = TaskContext(
            domain="cpp",
            task_type="write_code",
            capabilities=("code_generation",),
            context={"language": "cpp", "standard": 20},
        )
        rules = PolicyEngine(SkillRegistry([skill])).evaluate(task)
        rendered = EffectiveRulesRenderer().to_mapping(
            task=task,
            task_id="task_test",
            summary="Render test",
            rules=rules,
            trace={"active_skills": ["cpp.render"]},
        )
        effective = rendered["effective_rules"]

        self.assertEqual(effective["schema_version"], 1)
        self.assertIn("task", effective)
        self.assertIn("preference", effective)
        self.assertEqual(effective["hard"][0]["statement"], "Avoid undefined behavior.")
        self.assertEqual(effective["hard"][0]["source"]["skill"], "cpp.render")
        self.assertEqual(effective["preference"][0]["prefer"], "safety")

    def test_effective_rules_schema_validator_reports_missing_field(self) -> None:
        diagnostics = validate_effective_rules_mapping(
            {"effective_rules": {"schema_version": 1}},
            "inline",
        )

        self.assertTrue(diagnostics)


if __name__ == "__main__":
    unittest.main()
