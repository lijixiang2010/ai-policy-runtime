from __future__ import annotations

import os
import json
import argparse
import io
import shutil
import subprocess
import sys
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from ai_policy_runtime import PolicyEngine, Skill, SkillRegistry, TaskContext
from ai_policy_runtime.application.runtime import NonApplicableTaskError, PolicyRuntime
from ai_policy_runtime.domain.config import RuntimeConfig
from ai_policy_runtime.domain.pack import PackRegistry, SkillPack
from ai_policy_runtime.domain.rule import RuleAction
from ai_policy_runtime.task_analysis import TaskAnalyzer
from ai_policy_runtime.task_analysis.embeddings import (
    HashingTextEmbeddingProvider,
    OpenAICompatibleEmbeddingConfig,
    OpenAICompatibleEmbeddingProvider,
    cosine_similarity,
)
from ai_policy_runtime.task_analysis.lexicon import LexiconRule, TaskLexicon
from ai_policy_runtime.task_analysis.semantic_index import SemanticTaskIndex
from ai_policy_runtime.adapters.agent import build_post_refinement_task, merge_pack_ids
from ai_policy_runtime.adapters.codex.wrapper import _build_codex_command
from ai_policy_runtime.adapters.claude.wrapper import _build_claude_command
from ai_policy_runtime.interfaces.cli import CommandDispatcher
from ai_policy_runtime.services.project_context import (
    ProjectContextAnalyzer,
    merge_project_analysis,
)
from ai_policy_runtime.services.analyzer import analyze
from ai_policy_runtime.services.effective_rules import EffectiveRulesRenderer
from ai_policy_runtime.services.engine import PolicyConflictError
from ai_policy_runtime.services.injector import BEGIN, END, inject_current_prompt
from ai_policy_runtime.services.local_models import LocalModelManager
from ai_policy_runtime.services.validator import validate_effective_rules_mapping
from ai_policy_runtime.services.verification import FileVerifier, Violation, verify_rules
from hooks import stop_refinement, user_prompt_submit
from tools.configure_claude_desktop import (
    PLUGIN_ID,
    configure_claude_settings,
    DEFAULT_POST_REFINE_PACK,
    main as configure_claude_desktop_main,
    configure_policy,
    status as claude_desktop_status,
)
from tools.configure_codex import (
    configure_policy as configure_codex_policy,
    main as configure_codex_main,
    status as codex_status,
)


def _npm_test_env(**overrides: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.lower().startswith("npm_")
    }
    env.update(overrides)
    return env


def _load_fixture(name: str) -> dict[str, object]:
    import yaml  # type: ignore

    path = Path("tests") / "fixtures" / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _resolve_fixture(fixture: dict[str, object]) -> dict[str, object]:
    runtime = PolicyRuntime(RuntimeConfig.from_values(root=".", policy_root="."))
    result = runtime.resolve(
        str(fixture["task"]),
        tuple(str(item) for item in fixture.get("packs", ())),
    )
    return result.structured["effective_rules"]


def _statements(effective: dict[str, object]) -> set[str]:
    statements: set[str] = set()
    for group in ("hard", "soft", "preference"):
        for rule in effective.get(group, ()):
            statements.add(str(rule.get("statement", "")))
    return statements


def _sources(effective: dict[str, object]) -> set[str]:
    sources: set[str] = set()
    for group in ("hard", "soft", "preference"):
        for rule in effective.get(group, ()):
            source = rule.get("source", {})
            if isinstance(source, dict):
                sources.add(str(source.get("skill", "")))
    for item in effective.get("exceptions", ()):
        source = item.get("source", {})
        if isinstance(source, dict):
            sources.add(str(source.get("skill", "")))
    return sources


def _has_statement_containing(effective: dict[str, object], text: str) -> bool:
    return any(text in statement for statement in _statements(effective))


def _section_bullet_count(prompt: str, title: str) -> int:
    marker = f"## {title}"
    start = prompt.find(marker)
    if start < 0:
        return 0
    next_section = prompt.find("\n## ", start + len(marker))
    section = prompt[start:] if next_section < 0 else prompt[start:next_section]
    return sum(1 for line in section.splitlines() if line.startswith("- "))


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


class FakeHttpResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


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

    def test_cpp_refactor_does_not_infer_hot_path_without_latency_signal(self) -> None:
        task = analyze(
            "Refactor this C++20 code so it is not just working. "
            "Reduce complexity and preserve safety."
        ).task

        self.assertEqual(task.domain, "cpp")
        self.assertEqual(task.context["standard"], 20)
        self.assertNotIn("hot_path", task.context)
        self.assertNotIn("performance_critical", task.context)
        self.assertNotIn("allocation_sensitive", task.context)
        self.assertNotIn("low_latency", task.tags)

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
                    skill_id="cpp.performance.hot_path",
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

    def test_semantic_index_search_can_be_scoped_by_candidate_skill(self) -> None:
        lexicon = TaskLexicon(
            context_rules=(
                LexiconRule(
                    skill_id="cpp.performance.hot_path",
                    field="context.hot_path",
                    value=True,
                    phrases=(),
                    confidence=0.9,
                    source="hot",
                    semantic_texts=("tail latency must remain stable",),
                ),
                LexiconRule(
                    skill_id="python.web",
                    field="context.framework",
                    value="django",
                    phrases=(),
                    confidence=0.9,
                    source="web",
                    semantic_texts=("tail latency must remain stable",),
                ),
            )
        )
        index = SemanticTaskIndex(lexicon, KeywordConceptEmbeddingProvider(), threshold=0.1)

        matches = index.search_scoped(
            "尾延迟要稳定",
            scope=frozenset({"cpp.performance.hot_path"}),
        )

        self.assertEqual(
            [match.rule.skill_id for match in matches],
            ["cpp.performance.hot_path"],
        )

    def test_task_analysis_context_rules_use_text_match_authoring_form(self) -> None:
        lexicon = TaskLexicon.from_skills_dir("skills")

        template_rule = next(
            rule
            for rule in lexicon.context_rules
            if rule.source.endswith(":detect_template_constraints_required")
        )

        self.assertEqual(template_rule.field, "context.template_constraints_required")
        self.assertEqual(template_rule.value, True)
        self.assertIn("concept", template_rule.phrases)
        self.assertEqual(template_rule.set_context, {"template_constraints_required": True})

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

    def test_openai_compatible_embedding_provider_uses_batch_endpoint(self) -> None:
        provider = OpenAICompatibleEmbeddingProvider(
            OpenAICompatibleEmbeddingConfig(
                base_url="https://embedding.example.test/v1",
                model="embed-small",
                api_key="secret",
                timeout_seconds=3.0,
            )
        )
        response = FakeHttpResponse(
            {
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            }
        )

        with patch(
            "ai_policy_runtime.task_analysis.embeddings.urlopen",
            return_value=response,
        ) as urlopen_mock:
            vectors = provider.encode(("first", "second"))

        request = urlopen_mock.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://embedding.example.test/v1/embeddings")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(payload, {"model": "embed-small", "input": ["first", "second"]})
        self.assertEqual(vectors, [[1.0, 0.0], [0.0, 1.0]])

    def test_openai_compatible_embedding_config_can_be_loaded_from_env(self) -> None:
        env = {
            "AI_POLICY_EMBEDDING_PROVIDER": "openai-compatible",
            "AI_POLICY_EMBEDDING_BASE_URL": "https://gateway.example.test/v1",
            "AI_POLICY_EMBEDDING_API_KEY": "key",
            "AI_POLICY_EMBEDDING_MODEL": "embedding-model",
        }
        with patch.dict(os.environ, env, clear=True):
            provider = OpenAICompatibleEmbeddingProvider.from_env()

        self.assertIsNotNone(provider)
        assert provider is not None
        self.assertEqual(provider.config.base_url, "https://gateway.example.test/v1")
        self.assertEqual(provider.config.api_key, "key")
        self.assertEqual(provider.config.model, "embedding-model")

    def test_opaicompat_embedding_provider_alias_can_be_loaded_from_env(self) -> None:
        env = {
            "AI_POLICY_EMBEDDING_PROVIDER": "opaicompat",
            "AI_POLICY_EMBEDDING_BASE_URL": "https://gateway.example.test/v1",
            "AI_POLICY_EMBEDDING_API_KEY": "key",
        }
        with patch.dict(os.environ, env, clear=True):
            provider = OpenAICompatibleEmbeddingProvider.from_env()

        self.assertIsNotNone(provider)
        assert provider is not None
        self.assertEqual(provider.config.base_url, "https://gateway.example.test/v1")
        self.assertEqual(provider.config.api_key, "key")

    def test_openai_compatible_embedding_provider_requires_endpoint_configuration(self) -> None:
        with patch.dict(
            os.environ,
            {"AI_POLICY_EMBEDDING_PROVIDER": "openai-compatible"},
            clear=True,
        ):
            provider = OpenAICompatibleEmbeddingProvider.from_env()

        self.assertIsNone(provider)

    def test_local_model_manager_lists_and_installs_known_model(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = LocalModelManager(tmp)
            listed = manager.list()

            self.assertEqual(listed[0]["key"], "multilingual-mini")
            self.assertFalse(listed[0]["installed"])

            with patch(
                "ai_policy_runtime.services.local_models._snapshot_download"
            ) as download:
                installed = manager.install()

            download.assert_called_once()
            self.assertEqual(installed["key"], "multilingual-mini")
            self.assertTrue(installed["path"].endswith("paraphrase-multilingual-MiniLM-L12-v2"))

    def test_runtime_explain_returns_task_analysis_without_current_state(self) -> None:
        runtime = PolicyRuntime(RuntimeConfig.from_values(root="."))
        result = runtime.explain("帮我写一个 C++20 低延迟队列").to_dict()

        self.assertEqual(result["task"]["domain"], "cpp")
        self.assertEqual(result["task"]["context"]["standard"], 20)
        self.assertFalse(result["needs_review"])
        self.assertTrue(result["evidence"])
        self.assertIn("project_context", result)

    def test_runtime_does_not_override_openai_compatible_embedding_provider(self) -> None:
        with TemporaryDirectory() as tmp:
            policy_root = Path(tmp)
            local_model = policy_root / "models" / "paraphrase-multilingual-MiniLM-L12-v2"
            local_model.mkdir(parents=True)
            runtime = PolicyRuntime(
                RuntimeConfig.from_values(root=tmp, policy_root=policy_root)
            )
            env = {
                "AI_POLICY_EMBEDDING_PROVIDER": "openai-compatible",
                "AI_POLICY_EMBEDDING_API_KEY": "key",
                "AI_POLICY_EMBEDDING_MODEL": "text-embedding-3-small",
            }

            with patch.dict(os.environ, env, clear=True):
                self.assertIsNone(runtime._embedding_provider())

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

    def test_multiline_condition_expression_is_normalized(self) -> None:
        skill = Skill.from_mapping(
            {
                "skill": {
                    "id": "cpp.multiline.condition",
                    "name": "Multiline Condition",
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
                            "id": "allocation_condition",
                            "when": (
                                'language == "cpp" and\n'
                                "(hot_path == true or performance_critical == true)"
                            ),
                            "should": "Keep allocation policy explicit.",
                            "target": "allocation",
                            "action": "recommend",
                        }
                    ]
                },
            }
        )
        task = TaskContext(
            domain="cpp",
            task_type="write_code",
            capabilities=("code_generation",),
            context={"language": "cpp", "hot_path": True},
        )

        effective = PolicyEngine(SkillRegistry([skill])).evaluate(task)

        self.assertEqual([rule.id for rule in effective.soft], ["allocation_condition"])

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

    def test_codex_hook_reads_project_config_packs(self) -> None:
        config = {"packs": ["cpp.safe_generation", "cpp.low_latency"]}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                user_prompt_submit._configured_packs(config),
                ("cpp.safe_generation", "cpp.low_latency"),
            )

    def test_codex_hook_environment_packs_override_project_config(self) -> None:
        config = {"packs": ["cpp.safe_generation"]}
        with patch.dict(os.environ, {"AI_POLICY_PACKS": "cpp.low_latency"}, clear=True):
            self.assertEqual(
                user_prompt_submit._configured_packs(config),
                ("cpp.low_latency",),
            )

    def test_codex_hook_can_be_disabled_by_project_config(self) -> None:
        self.assertFalse(user_prompt_submit._enabled({"enabled": False}))
        self.assertFalse(user_prompt_submit._enabled({"enabled": "off"}))
        self.assertTrue(user_prompt_submit._enabled({}))

    def test_hook_defaults_to_codex_agent(self) -> None:
        self.assertTrue(user_prompt_submit._enabled_for({}, "codex"))
        self.assertFalse(user_prompt_submit._enabled_for({}, "claude"))

    def test_hook_config_filters_by_agent(self) -> None:
        config = {"enabled": True, "agents": ["claude"]}

        self.assertFalse(user_prompt_submit._enabled_for(config, "codex"))
        self.assertTrue(user_prompt_submit._enabled_for(config, "claude"))

    def test_codex_hook_config_reads_post_refinement_options(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = user_prompt_submit.ProjectHookConfig.from_mapping(
                {
                    "postRefine": "strict",
                    "postRefinePacks": ["cpp.production_refinement"],
                    "verifyTarget": "src",
                }
            )

        self.assertEqual(config.post_refine_mode, "strict")
        self.assertEqual(config.post_refine_pack_ids, ("cpp.production_refinement",))
        self.assertEqual(config.verify_target, "src")

    def test_stop_hook_allows_second_stop_to_prevent_loop(self) -> None:
        response = stop_refinement.build_stop_response({"stop_hook_active": True})

        self.assertEqual(response, {"continue": True})

    def test_stop_hook_blocks_once_for_configured_refinement(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / ".policy"
            policy.mkdir()
            (policy / "config.json").write_text(
                json.dumps({"postRefine": "standard"}),
                encoding="utf-8",
            )
            state_path = root / user_prompt_submit.HOOK_STATE_PATH
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "turn_id": "turn-1",
                        "session_id": "session-1",
                        "prompt": "Refactor this C++20 code.",
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(
                stop_refinement,
                "build_refinement_continuation_prompt",
                return_value="Refine once.",
            ):
                response = stop_refinement.build_stop_response(
                    {
                        "cwd": str(root),
                        "stop_hook_active": False,
                        "turn_id": "turn-1",
                        "session_id": "session-1",
                    }
                )

        self.assertEqual(response, {"decision": "block", "reason": "Refine once."})

    def test_stop_hook_does_not_reuse_stale_turn_state_without_matching_payload_id(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / ".policy"
            policy.mkdir()
            (policy / "config.json").write_text(
                json.dumps({"postRefine": "standard"}),
                encoding="utf-8",
            )
            state_path = root / user_prompt_submit.HOOK_STATE_PATH
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "turn_id": "old-turn",
                        "session_id": "old-session",
                        "prompt": "Refactor this C++20 code.",
                    }
                ),
                encoding="utf-8",
            )

            response = stop_refinement.build_stop_response(
                {"cwd": str(root), "stop_hook_active": False}
            )

        self.assertEqual(response, {"continue": True})

    def test_stop_hook_allows_legacy_turn_state_without_ids(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / ".policy"
            policy.mkdir()
            (policy / "config.json").write_text(
                json.dumps({"postRefine": "standard"}),
                encoding="utf-8",
            )
            state_path = root / user_prompt_submit.HOOK_STATE_PATH
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps({"prompt": "Refactor this C++20 code."}),
                encoding="utf-8",
            )

            with patch.object(
                stop_refinement,
                "build_refinement_continuation_prompt",
                return_value="Refine legacy turn.",
            ):
                response = stop_refinement.build_stop_response(
                    {"cwd": str(root), "stop_hook_active": False}
                )

        self.assertEqual(response, {"decision": "block", "reason": "Refine legacy turn."})

    def test_stop_hook_skips_refinement_without_applicable_turn_state(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / ".policy"
            policy.mkdir()
            (policy / "config.json").write_text(
                json.dumps({"postRefine": "standard"}),
                encoding="utf-8",
            )

            response = stop_refinement.build_stop_response(
                {"cwd": str(root), "stop_hook_active": False, "turn_id": "turn-1"}
            )

        self.assertEqual(response, {"continue": True})

    def test_stop_hook_respects_agent_filter(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / ".policy"
            policy.mkdir()
            (policy / "config.json").write_text(
                json.dumps({"agents": ["claude"], "postRefine": "standard"}),
                encoding="utf-8",
            )

            response = stop_refinement.build_stop_response(
                {"cwd": str(root), "stop_hook_active": False}
            )

        self.assertEqual(response, {"continue": True})

    def test_codex_hook_applies_openai_compatible_embedding_config(self) -> None:
        config = user_prompt_submit.ProjectHookConfig.from_mapping(
            {
                "embeddingProvider": "openai-compatible",
                "embeddingBaseUrl": "https://embedding.example.test/v1",
                "embeddingApiKey": "project-key",
                "embeddingModel": "embedding-model",
                "embeddingTimeout": "12.5",
            }
        )

        with patch.dict(os.environ, {}, clear=True):
            config.apply_environment()

            self.assertEqual(
                os.environ["AI_POLICY_EMBEDDING_PROVIDER"], "openai-compatible"
            )
            self.assertEqual(
                os.environ["AI_POLICY_EMBEDDING_BASE_URL"],
                "https://embedding.example.test/v1",
            )
            self.assertEqual(os.environ["AI_POLICY_EMBEDDING_API_KEY"], "project-key")
            self.assertEqual(os.environ["AI_POLICY_EMBEDDING_MODEL"], "embedding-model")
            self.assertEqual(os.environ["AI_POLICY_EMBEDDING_TIMEOUT"], "12.5")

    def test_codex_hook_keeps_environment_embedding_overrides(self) -> None:
        config = user_prompt_submit.ProjectHookConfig.from_mapping(
            {
                "embeddingProvider": "openai-compatible",
                "embeddingBaseUrl": "https://project.example.test/v1",
                "embeddingApiKey": "project-key",
                "embeddingModel": "project-model",
                "embeddingTimeout": "12.5",
            }
        )
        env = {
            "AI_POLICY_EMBEDDING_PROVIDER": "openai-compatible",
            "AI_POLICY_EMBEDDING_BASE_URL": "https://env.example.test/v1",
            "AI_POLICY_EMBEDDING_API_KEY": "env-key",
            "AI_POLICY_EMBEDDING_MODEL": "env-model",
            "AI_POLICY_EMBEDDING_TIMEOUT": "3",
        }

        with patch.dict(os.environ, env, clear=True):
            config.apply_environment()

            for key, value in env.items():
                self.assertEqual(os.environ[key], value)

    def test_codex_hook_loads_project_config(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / ".policy"
            policy.mkdir()
            (policy / "config.json").write_text(
                json.dumps({"enabled": True, "packs": ["cpp.safe_generation"]}),
                encoding="utf-8",
            )

            self.assertEqual(
                user_prompt_submit._load_project_config(root),
                {"enabled": True, "packs": ["cpp.safe_generation"]},
            )

    def test_resolve_if_applicable_skips_non_policy_input_without_writing_current(self) -> None:
        with TemporaryDirectory() as tmp:
            runtime = PolicyRuntime(RuntimeConfig.from_values(root=tmp, policy_root="."))

            result = runtime.resolve_if_applicable("hello", ("cpp.safe_generation",))

            self.assertFalse(result.applicable)
            self.assertFalse((Path(tmp) / ".policy" / "current").exists())

    def test_resolve_if_applicable_skips_status_query_without_writing_current(self) -> None:
        with TemporaryDirectory() as tmp:
            runtime = PolicyRuntime(RuntimeConfig.from_values(root=tmp, policy_root="."))

            with patch(
                "ai_policy_runtime.task_analysis.embeddings.urlopen",
                side_effect=AssertionError("status query should not request embeddings"),
            ):
                result = runtime.resolve_if_applicable(
                    "请检查当前项目，并说明 AI Policy Runtime 是否通过 Claude Code plugin 启用了。",
                    ("cpp.safe_generation",),
                )

            self.assertFalse(result.applicable)
            self.assertFalse((Path(tmp) / ".policy" / "current").exists())

    def test_resolve_if_applicable_requires_prompt_task_before_project_policy(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.24)\n"
                "project(docs LANGUAGES CXX)\n"
                "set(CMAKE_CXX_STANDARD 20)\n",
                encoding="utf-8",
            )
            runtime = PolicyRuntime(RuntimeConfig.from_values(root=root, policy_root="."))

            result = runtime.resolve_if_applicable(
                "阅读一下文档中的设计思想，看看有没有破坏原有的流程，流程是否还连贯。只分析，不改",
                ("cpp.safe_generation",),
            )

            self.assertFalse(result.applicable)
            self.assertFalse(result.task_analysis["activation_ready"])
            self.assertNotIn(
                "semantic_skill_matches",
                result.task_analysis["task"]["context"],
            )
            self.assertFalse((root / ".policy" / "current").exists())

    def test_resolve_rejects_non_applicable_task_without_writing_current(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CMakeLists.txt").write_text(
                "project(docs LANGUAGES CXX)\n"
                "set(CMAKE_CXX_STANDARD 20)\n",
                encoding="utf-8",
            )
            runtime = PolicyRuntime(RuntimeConfig.from_values(root=root, policy_root="."))

            with self.assertRaises(NonApplicableTaskError) as raised:
                runtime.resolve("阅读文档，只分析不改", ("cpp.safe_generation",))

            self.assertFalse(raised.exception.task_analysis["activation_ready"])
            self.assertFalse((root / ".policy" / "current").exists())

    def test_cli_resolve_reports_non_applicable_without_writing_current(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CMakeLists.txt").write_text(
                "project(docs LANGUAGES CXX)\n"
                "set(CMAKE_CXX_STANDARD 20)\n",
                encoding="utf-8",
            )

            output, exit_code = CommandDispatcher().dispatch(
                argparse.Namespace(
                    command="resolve",
                    root=str(root),
                    policy_root=".",
                    skills="skills",
                    packs="packs",
                    task="阅读文档，只分析不改",
                    pack=["cpp.safe_generation"],
                    format="json",
                )
            )

            self.assertEqual(exit_code, 0)
            self.assertFalse(output["applicable"])
            self.assertFalse((root / ".policy" / "current").exists())

    def test_pack_does_not_activate_unknown_task_from_project_context(self) -> None:
        base = Skill.from_mapping(
            {
                "skill": {
                    "id": "cpp.base",
                    "name": "Base",
                    "version": "1.0.0",
                    "level": "domain",
                    "domain": "cpp",
                    "priority": 10,
                    "activation": {
                        "when": {"language": "cpp"},
                        "triggers": ["write_code"],
                    },
                    "capabilities": ["code_generation"],
                },
                "rules": {
                    "hard": [
                        {"id": "base_rule", "must": "modern_cpp", "target": "base"}
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
                        "overrides": [
                            {
                                "id": "pack_preference",
                                "prefer": "safety",
                                "over": "speed",
                                "target": "tradeoff",
                            }
                        ],
                    }
                )
            ]
        )
        task = TaskContext(
            domain="cpp",
            task_type="unknown",
            capabilities=(),
            context={"language": "cpp", "standard": 20},
        )

        effective = PolicyEngine(SkillRegistry([base], packs)).evaluate(task, ("cpp.safe",))

        self.assertFalse(effective.hard)
        self.assertFalse(effective.preferences)

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

    def test_configure_claude_desktop_writes_policy_and_settings(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            plugin_root = Path(tmp) / "plugin"
            (plugin_root / ".claude-plugin").mkdir(parents=True)
            (plugin_root / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
            (plugin_root / ".claude-plugin" / "marketplace.json").write_text("{}", encoding="utf-8")
            (plugin_root / "hooks").mkdir()
            (plugin_root / "hooks" / "claude-hooks.json").write_text("{}", encoding="utf-8")

            policy_path = configure_policy(root, plugin_root)
            settings_path = configure_claude_settings(root, plugin_root, "local")

            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            settings = json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertTrue(policy["enabled"])
        self.assertIn("claude", policy["agents"])
        self.assertEqual(policy["policyRoot"], str(plugin_root))
        self.assertTrue(settings["enabledPlugins"][PLUGIN_ID])
        self.assertEqual(
            settings["extraKnownMarketplaces"]["ai-policy-runtime"]["source"]["path"],
            str(plugin_root),
        )

    def test_configure_claude_desktop_can_enable_post_refinement(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            plugin_root = Path(tmp) / "plugin"

            policy_path = configure_policy(
                root,
                plugin_root,
                post_refine="standard",
            )
            policy = json.loads(policy_path.read_text(encoding="utf-8"))

        self.assertEqual(policy["postRefine"], "standard")
        self.assertEqual(policy["postRefinePacks"], [DEFAULT_POST_REFINE_PACK])

    def test_configure_claude_desktop_uses_custom_post_refinement_packs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            plugin_root = Path(tmp) / "plugin"

            policy_path = configure_policy(
                root,
                plugin_root,
                post_refine="strict",
                post_refine_packs=("cpp.production_refinement", "project.refinement"),
            )
            policy = json.loads(policy_path.read_text(encoding="utf-8"))

        self.assertEqual(policy["postRefine"], "strict")
        self.assertEqual(
            policy["postRefinePacks"],
            ["cpp.production_refinement", "project.refinement"],
        )

    def test_configure_claude_desktop_can_disable_runtime_and_plugin(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            plugin_root = Path(tmp) / "plugin"

            policy_path = configure_policy(root, plugin_root, enabled=False)
            settings_path = configure_claude_settings(
                root,
                plugin_root,
                "local",
                enabled=False,
            )
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            settings = json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertFalse(policy["enabled"])
        self.assertFalse(settings["enabledPlugins"][PLUGIN_ID])

    def test_configure_claude_desktop_status_reports_current_features(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            plugin_root = Path(tmp) / "plugin"
            configure_policy(root, plugin_root, post_refine="standard")
            configure_claude_settings(root, plugin_root, "local")

            current = claude_desktop_status(root, plugin_root, "local")

        self.assertTrue(current["runtime_enabled"])
        self.assertTrue(current["claude_agent_enabled"])
        self.assertTrue(current["plugin_enabled"])
        self.assertTrue(current["marketplace_registered"])
        self.assertEqual(current["post_refine"], "standard")
        self.assertEqual(current["post_refine_packs"], [DEFAULT_POST_REFINE_PACK])

    def test_configure_claude_desktop_plugin_only_update_preserves_policy(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            plugin_root = Path(tmp) / "plugin"
            policy_path = configure_policy(root, plugin_root, post_refine="strict")

            configure_policy(
                root,
                plugin_root,
                enabled=False,
                configure_runtime=False,
            )
            policy = json.loads(policy_path.read_text(encoding="utf-8"))

        self.assertTrue(policy["enabled"])
        self.assertEqual(policy["postRefine"], "strict")

    def test_configure_claude_desktop_cli_plugin_only_does_not_create_policy(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"

            with patch("sys.stdout", new=io.StringIO()):
                exit_code = configure_claude_desktop_main(
                    ["--root", str(root), "--enable-plugin"]
                )

            settings = json.loads(
                (root / ".claude" / "settings.local.json").read_text(encoding="utf-8")
            )
            policy_exists = (root / ".policy" / "config.json").exists()

        self.assertEqual(exit_code, 0)
        self.assertFalse(policy_exists)
        self.assertTrue(settings["enabledPlugins"][PLUGIN_ID])

    def test_configure_claude_desktop_post_refine_only_preserves_disabled_runtime(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            plugin_root = Path(tmp) / "plugin"
            policy_path = configure_policy(root, plugin_root, enabled=False, post_refine="strict")

            configure_policy(
                root,
                plugin_root,
                post_refine="off",
                configure_runtime=False,
            )
            policy = json.loads(policy_path.read_text(encoding="utf-8"))

        self.assertFalse(policy["enabled"])
        self.assertEqual(policy["postRefine"], "off")
        self.assertEqual(policy["postRefinePacks"], [])

    def test_configure_claude_desktop_cli_post_refine_only_preserves_settings(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            plugin_root = Path(tmp) / "plugin"
            policy_path = configure_policy(root, plugin_root, enabled=False)
            settings_path = configure_claude_settings(root, plugin_root, "local", enabled=False)
            before_settings = settings_path.read_text(encoding="utf-8")

            with patch("sys.stdout", new=io.StringIO()):
                exit_code = configure_claude_desktop_main(
                    ["--root", str(root), "--post-refine", "standard"]
                )

            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            after_settings = settings_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertFalse(policy["enabled"])
        self.assertEqual(policy["postRefine"], "standard")
        self.assertEqual(after_settings, before_settings)

    def test_configure_claude_desktop_cli_post_refine_off_does_not_enable_new_project(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"

            with patch("sys.stdout", new=io.StringIO()):
                exit_code = configure_claude_desktop_main(
                    ["--root", str(root), "--post-refine", "off"]
                )

            policy = json.loads(
                (root / ".policy" / "config.json").read_text(encoding="utf-8")
            )
            settings_exists = (root / ".claude" / "settings.local.json").exists()

        self.assertEqual(exit_code, 0)
        self.assertEqual(policy, {"postRefine": "off", "postRefinePacks": []})
        self.assertFalse(settings_exists)

    def test_configure_claude_desktop_cli_reports_invalid_option_combinations(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"

            with patch("sys.stderr", new=io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as raised:
                    configure_claude_desktop_main(
                        [
                            "--root",
                            str(root),
                            "--post-refine-pack",
                            "cpp.production_refinement",
                        ]
                    )

            message = stderr.getvalue()

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--post-refine-pack requires --post-refine", message)

    def test_configure_codex_enables_policy_without_claude_settings(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            plugin_root = Path.cwd()

            policy_path = configure_codex_policy(root, plugin_root)
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            claude_settings_exists = (root / ".claude").exists()

        self.assertTrue(policy["enabled"])
        self.assertEqual(policy["agents"], ["codex"])
        self.assertEqual(policy["packs"], ["cpp.safe_generation"])
        self.assertEqual(policy["policyRoot"], str(Path.cwd()))
        self.assertFalse(claude_settings_exists)

    def test_configure_codex_disable_preserves_other_agents(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            policy = root / ".policy"
            policy.mkdir(parents=True)
            (policy / "config.json").write_text(
                json.dumps(
                    {
                        "enabled": True,
                        "agents": ["codex", "claude"],
                        "packs": ["cpp.safe_generation"],
                    }
                ),
                encoding="utf-8",
            )

            policy_path = configure_codex_policy(root, Path.cwd(), enabled=False)
            current = json.loads(policy_path.read_text(encoding="utf-8"))

        self.assertTrue(current["enabled"])
        self.assertEqual(current["agents"], ["claude"])

    def test_configure_codex_disable_turns_runtime_off_without_other_agents(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            policy = root / ".policy"
            policy.mkdir(parents=True)
            (policy / "config.json").write_text(
                json.dumps({"enabled": True, "agents": ["codex"]}),
                encoding="utf-8",
            )

            policy_path = configure_codex_policy(root, Path.cwd(), enabled=False)
            current = json.loads(policy_path.read_text(encoding="utf-8"))

        self.assertFalse(current["enabled"])
        self.assertEqual(current["agents"], [])

    def test_configure_codex_status_reports_current_features(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            plugin_root = Path.cwd()
            configure_codex_policy(root, plugin_root)

            current = codex_status(root, plugin_root)

        self.assertTrue(current["runtime_enabled"])
        self.assertTrue(current["codex_agent_enabled"])
        self.assertTrue(current["plugin_assets_present"])
        self.assertEqual(current["expected_plugin_root"], str(Path.cwd()))

    def test_configure_codex_cli_updates_policy(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"

            with patch("sys.stdout", new=io.StringIO()):
                exit_code = configure_codex_main(["--root", str(root)])

            policy = json.loads(
                (root / ".policy" / "config.json").read_text(encoding="utf-8")
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(policy["agents"], ["codex"])

    def test_npm_package_exposes_ai_policy_commands(self) -> None:
        package = json.loads(Path("package.json").read_text(encoding="utf-8"))

        self.assertEqual(package["bin"]["ai-policy"], "bin/ai-policy.js")
        self.assertEqual(package["bin"]["ai-policy-runtime"], "bin/ai-policy.js")
        self.assertIn(".claude-plugin/*.json", package["files"])
        self.assertIn("hooks/*.json", package["files"])
        self.assertIn("hooks/*.py", package["files"])
        self.assertIn("skills/**/*.yaml", package["files"])
        self.assertIn("packs/*.yaml", package["files"])

    def test_npm_pack_does_not_include_python_bytecode(self) -> None:
        npm = shutil.which("npm")
        if npm is None:
            self.skipTest("npm is not available")

        with TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [npm, "pack", "--dry-run"],
                check=True,
                capture_output=True,
                text=True,
                env=_npm_test_env(npm_config_cache=str(Path(tmp) / "npm-cache")),
            )
        output = completed.stdout + completed.stderr

        self.assertNotIn("__pycache__", output)
        self.assertNotRegex(output, r"\.pyc\b")

    def test_claude_hooks_use_packaged_node_wrapper(self) -> None:
        hooks = json.loads((Path("hooks") / "claude-hooks.json").read_text(encoding="utf-8"))

        user_prompt = hooks["hooks"]["UserPromptSubmit"][0]["hooks"][0]
        stop = hooks["hooks"]["Stop"][0]["hooks"][0]

        self.assertEqual(user_prompt["command"], "node")
        self.assertEqual(
            user_prompt["args"],
            ["${CLAUDE_PLUGIN_ROOT}/bin/ai-policy-hook.js", "claude-user-prompt-submit"],
        )
        self.assertEqual(stop["command"], "node")
        self.assertEqual(
            stop["args"],
            ["${CLAUDE_PLUGIN_ROOT}/bin/ai-policy-hook.js", "claude-stop-refinement"],
        )

    def test_ai_policy_status_command_uses_installed_package_root(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is not available")

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            env = {
                **os.environ,
                "AI_POLICY_PYTHON": sys.executable,
            }
            completed = subprocess.run(
                [
                    "node",
                    "bin/ai-policy.js",
                    "status",
                    "--root",
                    str(root),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            current = json.loads(completed.stdout)

        self.assertEqual(current["expected_plugin_root"], str(Path.cwd()))
        self.assertFalse(current["runtime_enabled"])
        self.assertFalse((root / ".policy" / "config.json").exists())

    def test_ai_policy_configure_codex_command_updates_policy_only(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is not available")

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            env = {
                **os.environ,
                "AI_POLICY_PYTHON": sys.executable,
            }
            subprocess.run(
                [
                    "node",
                    "bin/ai-policy.js",
                    "configure",
                    "codex",
                    "--root",
                    str(root),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            policy = json.loads(
                (root / ".policy" / "config.json").read_text(encoding="utf-8")
            )
            claude_settings_exists = (root / ".claude").exists()

        self.assertTrue(policy["enabled"])
        self.assertEqual(policy["agents"], ["codex"])
        self.assertFalse(claude_settings_exists)

    def test_ai_policy_status_codex_command_is_read_only(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is not available")

        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            env = {
                **os.environ,
                "AI_POLICY_PYTHON": sys.executable,
            }
            completed = subprocess.run(
                [
                    "node",
                    "bin/ai-policy.js",
                    "status",
                    "--agent",
                    "codex",
                    "--root",
                    str(root),
                ],
                check=True,
                capture_output=True,
                text=True,
                env=env,
            )
            current = json.loads(completed.stdout)
            policy_exists = (root / ".policy" / "config.json").exists()

        self.assertFalse(current["runtime_enabled"])
        self.assertFalse(current["codex_agent_enabled"])
        self.assertTrue(current["plugin_assets_present"])
        self.assertFalse(policy_exists)

    def test_ai_policy_doctor_reports_runtime_health(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is not available")

        env = {
            **os.environ,
            "AI_POLICY_PYTHON": sys.executable,
        }
        completed = subprocess.run(
            ["node", "bin/ai-policy.js", "doctor"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        current = json.loads(completed.stdout)

        self.assertTrue(current["ok"])
        self.assertEqual(current["packageRoot"], str(Path.cwd()))
        self.assertTrue(current["usingExplicitPython"])
        self.assertTrue(current["checks"]["claudePlugin"])
        self.assertTrue(current["checks"]["skills"])

    def test_npm_tarball_install_exposes_ai_policy_command(self) -> None:
        npm = shutil.which("npm")
        if npm is None:
            self.skipTest("npm is not available")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            npm_env = {
                **_npm_test_env(
                    AI_POLICY_PYTHON=sys.executable,
                    npm_config_cache=str(root / "npm-cache"),
                )
            }
            pack = subprocess.run(
                [npm, "pack", "--silent"],
                check=True,
                capture_output=True,
                text=True,
                env=npm_env,
            )
            tarball_name = pack.stdout.strip().splitlines()[-1]
            tarball = Path.cwd() / tarball_name
            self.addCleanup(lambda: tarball.exists() and tarball.unlink())
            prefix = root / "prefix"
            project = root / "project"
            subprocess.run(
                [npm, "install", "--prefix", str(prefix), "-g", str(tarball)],
                check=True,
                capture_output=True,
                text=True,
                env=npm_env,
            )
            command = (
                prefix / "ai-policy.cmd"
                if sys.platform.startswith("win")
                else prefix / "bin" / "ai-policy"
            )
            completed = subprocess.run(
                [str(command), "status", "--root", str(project)],
                check=True,
                capture_output=True,
                text=True,
                env=npm_env,
            )
            current = json.loads(completed.stdout)
            plugin_root_exists = Path(current["expected_plugin_root"]).exists()
            policy_exists = (project / ".policy" / "config.json").exists()

        self.assertTrue(plugin_root_exists)
        self.assertFalse(current["runtime_enabled"])
        self.assertFalse(policy_exists)

    def test_post_refinement_task_preserves_scope_and_behavior(self) -> None:
        task = build_post_refinement_task("Refactor the matching engine API.", "standard")

        self.assertIn("Preserve observable behavior", task)
        self.assertIn("remove accidental complexity", task)
        self.assertIn("Do not broaden scope", task)
        self.assertIn("Refactor the matching engine API.", task)

    def test_post_refinement_pack_merge_preserves_order_and_deduplicates(self) -> None:
        pack_ids = merge_pack_ids(
            ("cpp.low_latency", "cpp.production_refinement"),
            ("cpp.production_refinement", "cpp.safe_generation"),
        )

        self.assertEqual(
            pack_ids,
            ("cpp.low_latency", "cpp.production_refinement", "cpp.safe_generation"),
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

    def test_effective_prompt_keeps_bullets_on_separate_lines(self) -> None:
        runtime = PolicyRuntime(RuntimeConfig.from_values(root=".", policy_root="."))
        result = runtime.resolve(
            "Refactor this C++20 code so it is not just working. "
            "Reduce complexity and preserve safety.",
            ("cpp.production_refinement",),
        )
        prompt = (result.current / "effective-prompt.md").read_text(encoding="utf-8")

        self.assertNotIn(".- ", prompt)
        self.assertNotIn("Semantic Skill Matches", prompt)
        self.assertIn("Preserve the existing observable behavior", prompt)
        self.assertIn("Avoid undefined behavior.", prompt)
        self.assertIn("Group related state, helper functions, and behavior", prompt)
        self.assertIn("Verify behavior preservation.", prompt)
        self.assertIn(
            "Verify no new ownership, lifetime, resource, bounds, or "
            "undefined-behavior risks were introduced.",
            prompt,
        )
        self.assertIn(
            "Verify the refactoring reduced accidental complexity without "
            "introducing over-abstraction.",
            prompt,
        )
        self.assertNotIn("Verify: Do not use unchecked bounds access", prompt)
        self.assertLessEqual(_section_bullet_count(prompt, "Verification Requirements"), 5)
        self.assertLessEqual(_section_bullet_count(prompt, "HARD Rules"), 8)
        self.assertLessEqual(_section_bullet_count(prompt, "SOFT Rules"), 12)

        detailed_checks = [
            item["statement"]
            for item in result.structured["effective_rules"]["verification"]["required"]
        ]
        self.assertTrue(
            any("Do not use unchecked bounds access" in item for item in detailed_checks)
        )
        self.assertTrue(
            any("Preserve the existing observable behavior" in item for item in detailed_checks)
        )

    def test_effective_rules_schema_validator_reports_missing_field(self) -> None:
        diagnostics = validate_effective_rules_mapping(
            {"effective_rules": {"schema_version": 1}},
            "inline",
        )

        self.assertTrue(diagnostics)

    def test_cpp17_string_view_fixture_resolves_version_safe_rules(self) -> None:
        fixture = _load_fixture("cpp17_string_view_task.yaml")
        effective = _resolve_fixture(fixture)
        statements = _statements(effective)
        sources = _sources(effective)

        self.assertIn("cpp.standard.cpp17.best_practices", sources)
        self.assertIn("cpp.standard.standard_availability", sources)
        self.assertTrue(_has_statement_containing(effective, "std::string_view"))
        self.assertTrue(_has_statement_containing(effective, "C++20-only facilities"))
        self.assertFalse(_has_statement_containing(effective, "std::span"))
        self.assertFalse(_has_statement_containing(effective, "C++20 concepts"))
        self.assertFalse(_has_statement_containing(effective, "std::jthread"))

    def test_cpp20_span_fixture_resolves_contiguous_range_rules(self) -> None:
        fixture = _load_fixture("cpp20_span_task.yaml")
        effective = _resolve_fixture(fixture)
        statements = _statements(effective)
        sources = _sources(effective)

        self.assertIn("cpp.standard.cpp17.best_practices", sources)
        self.assertIn("cpp.standard.cpp20.best_practices", sources)
        self.assertIn("cpp.standard.standard_availability", sources)
        self.assertTrue(_has_statement_containing(effective, "std::span"))
        self.assertTrue(_has_statement_containing(effective, "unavailable in the selected C++ standard"))
        self.assertFalse(_has_statement_containing(effective, "std::string_view"))

    def test_cpp20_low_latency_fixture_keeps_safety_above_performance(self) -> None:
        fixture = _load_fixture("cpp20_low_latency_task.yaml")
        effective = _resolve_fixture(fixture)
        statements = _statements(effective)
        sources = _sources(effective)

        self.assertIn("cpp.safety.undefined_behavior", sources)
        self.assertIn("cpp.performance.hot_path", sources)
        self.assertIn("cpp.performance.allocation_control", sources)
        self.assertTrue(_has_statement_containing(effective, "std::span"))
        self.assertIn("safety > performance", statements)
        self.assertIn("performance > readability", statements)

    def test_cpp_api_design_fixture_resolves_interface_rules(self) -> None:
        fixture = _load_fixture("cpp_api_design_task.yaml")
        effective = _resolve_fixture(fixture)
        sources = _sources(effective)

        self.assertIn("cpp.api_design.interface_intent", sources)
        self.assertIn("cpp.api_design.parameter_passing", sources)
        self.assertIn("cpp.api_design.ownership_in_interfaces", sources)

    def test_cpp_review_lifetime_fixture_resolves_review_safety_rules(self) -> None:
        fixture = _load_fixture("cpp_review_lifetime_task.yaml")
        effective = _resolve_fixture(fixture)
        sources = _sources(effective)

        self.assertIn("cpp.safety.ownership_and_lifetime", sources)
        self.assertIn("cpp.resource_management.raii", sources)
        self.assertIn("cpp.safety.undefined_behavior", sources)
        self.assertTrue(effective["verification"]["required"])

    def test_cpp20_template_constraints_prefer_concepts(self) -> None:
        runtime = PolicyRuntime(RuntimeConfig.from_values(root=".", policy_root="."))
        result = runtime.resolve(
            "Write a C++20 generic template API with explicit template constraints.",
            ("cpp.modernization",),
        )
        effective = result.structured["effective_rules"]
        statements = _statements(effective)

        self.assertIn(
            "Prefer C++20 concepts and requires-clauses over SFINAE or std::enable_if "
            "when template constraints are part of the public interface.",
            statements,
        )
        self.assertIn(
            "Avoid exposing unconstrained template interfaces when the valid argument set "
            "has meaningful semantic requirements.",
            statements,
        )
        self.assertIn(
            "Structure generic constraints so invalid arguments fail with actionable "
            "diagnostics near the template interface.",
            statements,
        )
        self.assertIn("named_semantic_concept > repeated_ad_hoc_requires_expression", statements)

    def test_cpp17_template_constraints_use_readable_sfinae_fallback(self) -> None:
        runtime = PolicyRuntime(RuntimeConfig.from_values(root=".", policy_root="."))
        result = runtime.resolve(
            "Write a C++17 generic template API with explicit template constraints.",
            ("cpp.modernization",),
        )
        statements = _statements(result.structured["effective_rules"])

        self.assertIn(
            "Use readable SFINAE, std::enable_if, or type traits when template "
            "constraints are required in pre-C++20 code.",
            statements,
        )
        self.assertIn(
            "Avoid exposing unconstrained template interfaces when the valid argument set "
            "has meaningful semantic requirements.",
            statements,
        )
        self.assertIn(
            "Structure generic constraints so invalid arguments fail with actionable "
            "diagnostics near the template interface.",
            statements,
        )
        self.assertNotIn(
            "Prefer C++20 concepts and requires-clauses over SFINAE or std::enable_if "
            "when template constraints are part of the public interface.",
            statements,
        )

    def test_cpp_production_refinement_extracts_template_for_type_variation(self) -> None:
        runtime = PolicyRuntime(RuntimeConfig.from_values(root=".", policy_root="."))
        result = runtime.resolve(
            "Refactor these C++20 functions. They have shared C++ logic with small "
            "variations and similar C++ functions differ only by type, so extract "
            "a template function if it reduces duplication.",
            ("cpp.production_refinement",),
        )
        statements = _statements(result.structured["effective_rules"])

        self.assertIn(
            "Extract a template function, template class, constrained overload, or "
            "policy parameter when similar C++ implementations share most control or "
            "data flow and differ only by a small number of type or policy decisions.",
            statements,
        )
        self.assertIn(
            "Avoid introducing a template abstraction when the similarity is incidental, "
            "variation points are unclear, or the resulting API and diagnostics become "
            "harder to understand than the specialized implementations.",
            statements,
        )

    def test_resolve_cli_can_output_effective_prompt(self) -> None:
        from argparse import Namespace

        output, exit_code = CommandDispatcher().dispatch(
            Namespace(
                command="resolve",
                root=".",
                policy_root=".",
                skills="skills",
                packs="packs",
                task="Write a C++17 function that accepts a read-only string parameter.",
                pack=[],
                format="prompt",
            )
        )

        self.assertEqual(exit_code, 0)
        self.assertIsInstance(output, str)
        self.assertIn("# Effective Rules for Current Task", output)
        self.assertIn("Prefer std::string_view", output)
        self.assertNotIn('"effective_rules"', output)

    def test_resolve_cli_defaults_to_effective_prompt(self) -> None:
        from argparse import Namespace

        output, exit_code = CommandDispatcher().dispatch(
            Namespace(
                command="resolve",
                root=".",
                policy_root=".",
                skills="skills",
                packs="packs",
                task="Write a C++17 function that accepts a read-only string parameter.",
                pack=[],
                format="prompt",
            )
        )

        self.assertEqual(exit_code, 0)
        self.assertIsInstance(output, str)
        self.assertIn("Prefer available standard facility over unavailable or unapproved facility.", output)
        self.assertNotIn("available_standard_facility > unavailable_or_unapproved_facility", output)

    def test_generic_production_refinement_pack_outputs_refinement_rules(self) -> None:
        runtime = PolicyRuntime(RuntimeConfig.from_values(root=".", policy_root="."))
        result = runtime.resolve(
            "Refactor this code so it is not just working. Reduce complexity, "
            "group scattered logic, and make the API easier to use.",
            ("generic.production_refinement",),
        )
        effective = result.structured["effective_rules"]
        statements = _statements(effective)

        self.assertIn(
            "Preserve the existing observable behavior while reducing complexity "
            "unless the task explicitly asks for a behavior change.",
            statements,
        )
        self.assertIn(
            "Remove accidental complexity that does not contribute to correctness, "
            "extensibility, performance, or clarity.",
            statements,
        )
        self.assertTrue(_has_statement_containing(effective, "Group related variables"))
        self.assertTrue(_has_statement_containing(effective, "Minimize the number of steps"))
        self.assertFalse(any(item.startswith("Introduce abstractions") for item in statements))

    def test_cpp_production_refinement_pack_combines_generic_and_cpp_rules(self) -> None:
        runtime = PolicyRuntime(RuntimeConfig.from_values(root=".", policy_root="."))
        result = runtime.resolve(
            "Refactor this C++20 code so it is not just working. Reduce complexity "
            "and preserve safety.",
            ("cpp.production_refinement",),
        )
        effective = result.structured["effective_rules"]
        sources = _sources(effective)

        self.assertIn("generic.code_quality.complexity_reduction", sources)
        self.assertIn("cpp.safety.undefined_behavior", sources)
        self.assertTrue(_has_statement_containing(effective, "observable behavior"))
        self.assertTrue(_has_statement_containing(effective, "undefined behavior"))


if __name__ == "__main__":
    unittest.main()
