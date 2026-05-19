![AI Policy Runtime banner](docs/assets/banner.png)

# AI Policy Runtime

Generate better AI code with task-aware policies.

AI Policy Runtime helps Codex, Claude Code, and other AI coding workflows apply
the right engineering guidance for each task. Instead of relying on one static
prompt for every situation, it activates focused policies for the work at hand:
implementation, review, refactoring, API design, performance-sensitive code,
and post-task refinement.

It is designed for general AI coding workflows. C++ currently has the deepest
policy coverage, including ownership, lifetime, bounds safety, modern C++,
low-latency constraints, and library API design.

## Why Use It

- Improve AI-generated code quality without rewriting prompts by hand.
- Keep agent behavior consistent across a workspace.
- Apply different policy packs for generation, review, modernization, API
  design, and performance-sensitive work.
- Add an optional refinement pass before an agent finishes.
- Inspect the active policy when you need to understand what guided a response.

## Install

For command-line and agent integration workflows:

```powershell
npm install -g ai-policy-runtime
ai-policy doctor
```

For VS Code, install the **AI Policy Runtime** extension alongside the Codex or
Claude Code extension you already use.

## Use It Three Ways

| Entry point | Best for | Configuration |
| --- | --- | --- |
| VS Code Extension | Codex or Claude Code inside VS Code | Use the side bar. It saves VS Code workspace settings and syncs `.policy/config.json`. |
| Command-Line Agent Hooks | Codex CLI, Claude Code CLI, or Claude Desktop Code sessions | Use `ai-policy configure ...`; hooks read `.policy/config.json`, with environment variables for CI or temporary overrides. |
| Python Runtime | Custom tools, CI, or embedded workflows | Construct `PolicyRuntime(RuntimeConfig(...))`; embedding uses environment variables or the default local model under `policy_root/models`. |

### 1. VS Code Extension

Use this when you run Codex or Claude Code from VS Code.

1. Install the Codex or Claude Code extension you want to use.
2. Install **AI Policy Runtime**.
3. Open the AI Policy Runtime side bar.
4. Enable the runtime for the workspace.
5. Select Codex, Claude Code, or both.
6. Choose the policy packs for your project.

Your selected AI coding agents will use the workspace policy automatically.

### 2. Command-Line Agent Hooks

Use this when you run the original Codex CLI, Claude Code CLI, or Claude
Desktop Code sessions.

Configure a project for Codex CLI:

```powershell
ai-policy configure codex --root D:\work\target-project
```

Then run Codex normally from that project. AI Policy Runtime hooks will apply
the workspace policy automatically.

Configure embeddings for command-line hooks:

```powershell
ai-policy embedding configure --root D:\work\target-project --provider local
ai-policy embedding status --root D:\work\target-project
```

Configure a project for Claude Code or Claude Desktop Code sessions:

```powershell
ai-policy configure claude --root D:\work\target-project
```

Enable a post-task refinement pass when you want the agent to review and polish
its own work before finishing:

```powershell
ai-policy post-refine standard --root D:\work\target-project
```

Check the active configuration:

```powershell
ai-policy status --root D:\work\target-project
ai-policy status --agent codex --root D:\work\target-project
```

### 3. Python Runtime

Use this when you want to embed policy resolution in a custom tool, CI flow, or
agent workflow.

```python
from ai_policy_runtime import PolicyRuntime, RuntimeConfig

runtime = PolicyRuntime(RuntimeConfig.from_values(root="."))
result = runtime.resolve(
    "Implement a C++20 matching-engine API.",
    ("cpp.low_latency",),
)
```

Configure embeddings directly in Python when you do not want to rely on process
environment variables:

```python
runtime = PolicyRuntime(RuntimeConfig.from_values(
    root=".",
    policy_root="D:/MilesLi/ai-policy-runtime",
    embedding_provider="openai-compatible",
    embedding_api_key="<key>",
    embedding_model="text-embedding-3-small",
))
```

## Policy Packs

Bundled packs include:

- `cpp.safe_generation`
- `cpp.low_latency`
- `cpp.code_review`
- `cpp.library_api_design`
- `cpp.modernization`
- `cpp.production_refinement`
- `generic.production_refinement`
- `git.best_practices`
- `cmake.best_practices`

C++ has the most complete code-generation coverage today. Generic refinement
packs are available for broader coding workflows. Git workflow policies cover
commit hygiene, staging, stashing, cleaning, branching, pull request readiness,
conflict resolution, and history rewrite safety. CMake policies cover
target-based project structure, usage requirements, source lists, compiler
options, dependencies, packaging, presets, toolchains, testing, and quality tooling.

## Useful Commands

Resolve a prompt into task-aware rules:

```powershell
ai-policy resolve --pack cpp.low_latency "Implement a C++20 matching-engine API."
```

Explain how a task was classified:

```powershell
ai-policy explain "Review this API for ownership and lifetime risks."
```

Validate the bundled policies:

```powershell
ai-policy validate
```

Show generated rules for the current workspace:

```powershell
ai-policy inspect
```

## Agent Wrappers

Hooks are the recommended path for normal Codex and Claude Code usage. Wrapper
commands are also available when you want to run an agent through an explicit
policy-aware command:

```powershell
policy-codex --pack cpp.low_latency "Implement a C++20 matching-engine API."
policy-claude --pack cpp.production_refinement "Refactor this module safely."
```

## Documentation

- [Usage Guide](docs/usage.md): command-line workflows, agent integrations,
  embeddings, cache, and verification.
- [NPM Install Guide](docs/npm-install.md): end-user installation and
  troubleshooting.
- [Post-Task Refinement](docs/post_task_refinement_workflow.md): refinement
  modes and verification flow.
- [Git Best Practices](docs/git_best_practices.md): Git workflow policies for
  commits, branches, conflict resolution, and history safety.
- [CMake Best Practices](docs/cmake_best_practices.md): CMake policies for
  targets, dependencies, packaging, presets, toolchains, and quality tooling.
- [Skill Policy Runtime](docs/skill_policy_runtime.md): runtime model and core
  concepts.
- [Skill DSL Syntax](docs/skill_dsl_syntax_specification.md): Skill file format.
- [Effective Rules Output](docs/effective_rules_output_specification.md):
  generated rule contract.
- [C++ Skill Library Design](docs/cpp_skill_library_design.md): current C++
  policy library structure.
- [Reference Assets](docs/reference/): ontology and verification mapping
  references used by the design documents.
- [Release Guide](docs/release.md): release checks and publishing workflow.

## Notes

- The runtime produces task-aware policy context for AI agents; it is not itself
  an LLM.
- The default installation does not download models.
- Optional semantic matching can use OpenAI-compatible embeddings or a local
  sentence-transformers model.
