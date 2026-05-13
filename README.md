# AI Policy Runtime

![AI Policy Runtime logo](docs/assets/logo.png)

Created and maintained by Miles Li.

Working implementation of the Skill DSL / Policy Runtime described in
`docs/skill_policy_runtime.md`.

The current runtime focuses on the deterministic policy core plus optional
embedding based task analysis:

```text
User task -> TaskAnalysis -> TaskContext -> SkillRegistry -> PolicyEngine -> EffectiveRules
```

The implementation is grouped into explicit source layers:

```text
domain/          -> TaskContext, Skill, Rule, SkillPack, diagnostics, config
infrastructure/  -> YAML/JSON loading, condition evaluation, schema loading
services/        -> registry, engine, validation, rendering, verification, state writing
application/     -> PolicyRuntime orchestration
interfaces/      -> CLI adapter
task_analysis/   -> exact task analysis plus optional embedding semantic recall
```

For programmatic use, prefer the service facade:

```python
from ai_policy_runtime import PolicyRuntime, RuntimeConfig

runtime = PolicyRuntime(RuntimeConfig.from_values(root="."))
result = runtime.resolve("帮我写一个 C++20 低延迟队列", ("cpp.low_latency",))
```

When the runtime is used to enhance another repository, keep the target project
root separate from the policy asset root:

```python
runtime = PolicyRuntime(
    RuntimeConfig.from_values(
        root=r"D:\work\target-project",
        policy_root=r"D:\MilesLi\ai-policy-runtime",
    )
)
result = runtime.resolve("帮我写一个低延迟队列", ("cpp.low_latency",))
```

In this mode the target project is scanned and receives `.policy/current/`,
`AGENTS.md`, or `CLAUDE.md`, while Skills and Packs are loaded from
`policy_root`.

## Skill Library

Skills now follow the documented DSL shape and directory layout:

```text
skills/
├── domain/
│   └── cpp/
│       ├── base/
│       │   └── language_baseline.skill.yaml
│       ├── safety/
│       │   ├── undefined_behavior.skill.yaml
│       │   ├── ownership_and_lifetime.skill.yaml
│       │   ├── bounds_safety.skill.yaml
│       │   └── type_safety.skill.yaml
│       ├── resource_management/
│       │   └── raii.skill.yaml
│       ├── api_design/
│       │   ├── interface_intent.skill.yaml
│       │   ├── parameter_passing.skill.yaml
│       │   └── ownership_in_interfaces.skill.yaml
│       ├── error_handling/
│       │   └── error_model.skill.yaml
│       ├── concurrency/
│       │   ├── data_race_safety.skill.yaml
│       │   └── thread_lifetime.skill.yaml
│       ├── performance/
│       │   ├── hot_path.skill.yaml
│       │   └── allocation_control.skill.yaml
│       ├── templates/
│       │   └── generic_constraints.skill.yaml
│       ├── standard/
│       │   ├── cpp17_best_practices.skill.yaml
│       │   ├── cpp20_best_practices.skill.yaml
│       │   └── standard_availability.skill.yaml
│       └── source_structure/
│           └── source_file_organization.skill.yaml
└── generic/
    ├── code_quality/
    ├── refactoring/
    └── architecture/

packs/
├── cpp_safe_generation.pack.yaml
├── cpp_code_review.pack.yaml
├── cpp_modernization.pack.yaml
├── cpp_low_latency.pack.yaml
├── cpp_library_api_design.pack.yaml
├── generic_production_refinement.pack.yaml
└── cpp_production_refinement.pack.yaml
```

The runtime recursively loads `*.skill.yaml`, `*.yaml`, `*.yml`, and `*.json`
files from the configured skill directory. Skill files use the documented
Object Form with top-level `skill`, `rules`, `exceptions`, and `verification`
sections.

## Run the Example

```powershell
python examples/cpp_low_latency.py
```

## Run Tests

```powershell
python -m unittest discover -s tests
```

## Task Analysis

Task analysis uses:

```text
exact matching for precise facts
deterministic project-context scanning for omitted repository facts
deterministic evidence resolution for final TaskContext
optional embedding semantic recall for rephrased intent
```

The default installation has no model dependency and does not download models.
It uses deterministic task analysis, project-context scanning, and the best
configured semantic provider:

```text
OpenAI-compatible /v1/embeddings endpoint
local sentence-transformers model
dependency-free hashing n-gram matcher
```

Use an OpenAI-compatible embedding endpoint when you want strong multilingual
semantic matching without asking users to download a local model:

```powershell
$env:AI_POLICY_EMBEDDING_API_KEY="<key>"
$env:AI_POLICY_EMBEDDING_MODEL="text-embedding-3-small"
```

`AI_POLICY_EMBEDDING_PROVIDER` is optional for the common case. The runtime
automatically uses the OpenAI-compatible provider when
`AI_POLICY_EMBEDDING_API_KEY`, `OPENAI_API_KEY`, or
`AI_POLICY_EMBEDDING_BASE_URL` is set. Keep the provider variable for explicit
advanced overrides:

```powershell
$env:AI_POLICY_EMBEDDING_PROVIDER="openai-compatible" # force remote embeddings
$env:AI_POLICY_EMBEDDING_PROVIDER="local"             # force sentence-transformers
$env:AI_POLICY_EMBEDDING_PROVIDER="hashing"           # force lightweight local matcher
$env:AI_POLICY_EMBEDDING_PROVIDER="disabled"          # disable semantic matching
```

For OpenAI-compatible gateways, set the endpoint explicitly:

```powershell
$env:AI_POLICY_EMBEDDING_BASE_URL="https://gateway.example.com/v1"
```

If `AI_POLICY_EMBEDDING_MODEL` is omitted for a remote endpoint, the runtime
uses `text-embedding-3-small`.

If no remote provider is configured, the runtime tries the bundled local model
path shown below, then falls back to the lightweight hashing matcher. The
dependency-free matcher is less powerful than real embedding models, but works
well for task-intent recall when Skills provide representative semantic
phrases.

To verify which semantic path works in your environment, run:

```powershell
python -m ai_policy_runtime.cli explain "帮我写一个 C++20 低延迟队列"
```

The output should include structured context such as `hot_path: true`,
`scenario: low_latency_queue`, and semantic evidence whose source contains an
English skill phrase such as `semantic:low latency queue implementation`.

You can force each provider while testing:

```powershell
$env:AI_POLICY_EMBEDDING_PROVIDER="openai-compatible"
python -m ai_policy_runtime.cli explain "帮我写一个 C++20 低延迟队列"

$env:AI_POLICY_EMBEDDING_PROVIDER="local"
python -m ai_policy_runtime.cli explain "帮我写一个 C++20 低延迟队列"

$env:AI_POLICY_EMBEDDING_PROVIDER="hashing"
python -m ai_policy_runtime.cli explain "帮我写一个 C++20 低延迟队列"

$env:AI_POLICY_EMBEDDING_PROVIDER="disabled"
python -m ai_policy_runtime.cli explain "帮我写一个 C++20 低延迟队列"
```

In automatic mode, leave `AI_POLICY_EMBEDDING_PROVIDER` unset. Automatic mode
uses the remote OpenAI-compatible endpoint when endpoint credentials are
configured, otherwise the local model, otherwise the hashing matcher. When a
provider is forced explicitly, configuration or endpoint errors are reported
instead of silently falling back to a weaker provider.

Transformer-based semantic recall is optional. Install the optional extra when
you want it:

```powershell
pip install "ai-policy-runtime[semantic]"
```

Then install the recommended local model into the policy asset root:

```powershell
python -m ai_policy_runtime.cli model install
```

Inspect local model status with:

```powershell
python -m ai_policy_runtime.cli model list
```

The default local model path is:

```text
models/paraphrase-multilingual-MiniLM-L12-v2
```

You can also point the runtime at another local sentence-transformers model:

```powershell
$env:AI_POLICY_EMBEDDING_MODEL="D:\path\to\model"
```

When `policy_root/models/paraphrase-multilingual-MiniLM-L12-v2` exists, the
high-level runtime uses it automatically. If no local transformer model is
configured, the runtime falls back to the built-in hashing n-gram matcher rather
than downloading anything.

Semantic index vectors are cached under:

```text
.policy/cache/semantic-index/
```

Explain Task Analysis without resolving rules:

```powershell
python -m ai_policy_runtime.cli explain "写一个 C++20 数据通道，主循环里不能有分配和阻塞，尾延迟要稳"
```

The runtime scans project files before resolving a task. High-confidence facts
from build metadata can fill in details the user did not repeat in the prompt,
such as C++ standard, build system, and primary language. Supported sources
include:

```text
.policy/project.yaml
compile_commands.json
CMakeLists.txt
CMakePresets.json-compatible CMake files through CMakeLists scanning
pyproject.toml, Cargo.toml, package.json, go.mod
vcpkg.json, conanfile.txt, conanfile.py
source/header file layout
README.md weak tags
```

Facts are written with provenance to:

```text
.policy/current/project-context.json
.policy/current/trace.json
```

Manual project overrides can be declared in `.policy/project.yaml`:

```yaml
domain: cpp
build_system: cmake
context:
  standard: 20
  selected_standard_is_known: true
  hot_path: true
tags:
  - low_latency
```

Inspect the current resolved state:

```powershell
python -m ai_policy_runtime.cli inspect
```

Print bundled schemas:

```powershell
python -m ai_policy_runtime.cli schema skill
python -m ai_policy_runtime.cli schema pack
python -m ai_policy_runtime.cli schema effective-rules
```

List or clear semantic-index cache entries:

```powershell
python -m ai_policy_runtime.cli cache list
python -m ai_policy_runtime.cli cache clear
```

## Resolve a Task

```powershell
python -m ai_policy_runtime.cli resolve "帮我写一个 C++20 低延迟队列"
python -m ai_policy_runtime.cli resolve --pack cpp.low_latency "帮我写一个 C++20 低延迟队列"
```

`resolve` prints the final agent-facing prompt by default. For explicitness in
test scripts, you can also pass `--format prompt`:

```powershell
python -m ai_policy_runtime.cli resolve --format prompt "帮我写一个 C++20 低延迟队列"
python -m ai_policy_runtime.cli resolve --format prompt --pack cpp.low_latency "帮我写一个 C++20 低延迟队列"
```

Use `--format json` only when a tool needs structured command output:

```powershell
python -m ai_policy_runtime.cli resolve --format json "帮我写一个 C++20 低延迟队列"
```

This writes the current task state to `.policy/current/`:

- `task-context.json`
- `effective-rules.json`
- `effective-rules.yaml`
- `effective-prompt.md`
- `trace.json`

## Validate Skills

```powershell
python -m ai_policy_runtime.cli validate
```

Validation combines bundled JSON Schema checks from `schemas/` with semantic
runtime checks such as dependency and pack-reference validation.

## Inject Effective Rules

```powershell
python -m ai_policy_runtime.cli inject --target custom
python -m ai_policy_runtime.cli inject --target codex
python -m ai_policy_runtime.cli inject --target claude
```

`codex` updates the generated block in `AGENTS.md`; `claude` updates
`CLAUDE.md`; `custom` writes `.policy/current/injected-prompt.md`.

## Run Codex with Effective Rules

Use `policy-codex` when installed as a package:

```powershell
policy-codex --pack cpp.low_latency "帮我写一个 C++20 低延迟队列"
```

The wrapper performs:

```text
resolve -> inject AGENTS.md -> codex "<task>"
```

For dry runs that only refresh `AGENTS.md`:

```powershell
policy-codex --pack cpp.low_latency --no-exec "帮我写一个 C++20 低延迟队列"
```

To enhance a different project with this policy repository:

```powershell
policy-codex --root D:\work\target-project --policy-root D:\MilesLi\ai-policy-runtime --pack cpp.low_latency "帮我写一个低延迟队列"
```

Pass Codex CLI options before the task with repeated `--codex-arg`:

```powershell
policy-codex --pack cpp.low_latency --codex-arg "--approval-mode" --codex-arg "never" "帮我写一个 C++20 低延迟队列"
```

## Use as a Codex Plugin

This repository is also shaped as a Codex plugin. The plugin registers a
`UserPromptSubmit` hook that resolves the current user prompt into Effective
Rules and injects the rendered rules as Codex `additionalContext`.

Plugin files:

```text
.codex-plugin/plugin.json
hooks/hooks.json
hooks/user_prompt_submit.py
```

The hook bootstraps the Python package from this repository on first use:

```text
python -m pip install -e <plugin-root>
```

That installs the runtime dependencies declared in `pyproject.toml`, including
`PyYAML` and `jsonschema`. Set `AI_POLICY_AUTO_INSTALL=0` to disable this
automatic bootstrap and manage dependencies yourself.

Useful environment variables:

```text
AI_POLICY_ROOT=<path-to-policy-runtime>
AI_POLICY_PACKS=cpp.low_latency,cpp.safe_generation
AI_POLICY_AUTO_INSTALL=0
```

The hook also reads project-local configuration from:

```text
.policy/config.json
```

This is the preferred control surface for editor integrations:

```json
{
  "enabled": true,
  "packs": ["cpp.safe_generation", "cpp.low_latency"],
  "autoInstall": true,
  "embeddingProvider": "hashing"
}
```

Environment variables still override `.policy/config.json` when both are set.

## Configure Codex from VS Code

A Codex-focused VS Code extension is included under:

```text
vscode-extension/
```

The extension does not reimplement the runtime. It writes `.policy/config.json`
for the current workspace and lets the Codex plugin hook inject Effective Rules
on each prompt.

Available commands:

```text
AI Policy: Enable
AI Policy: Disable
AI Policy: Configure Packs
AI Policy: Show Status
AI Policy: Show Effective Rules
AI Policy: Validate Runtime
```

During development, build the extension with:

```powershell
cd vscode-extension
npm install
npm run compile
```

For local development in this repository, `.codex/config.toml` points Codex at
the same hook implementation used by the plugin.

After publishing this repository to GitHub, users can add it as a Codex plugin
marketplace:

```powershell
codex plugin marketplace add lkimuk/ai-policy-runtime
```

Then install **AI Policy Runtime** from Codex:

```text
/plugins
```

The marketplace entry is declared in:

```text
.agents/plugins/marketplace.json
```

## Run Claude Code with Effective Rules

Use `policy-claude` when installed as a package:

```powershell
policy-claude --pack cpp.low_latency "帮我写一个 C++20 低延迟队列"
```

The wrapper performs:

```text
resolve -> inject CLAUDE.md -> claude "<task>"
```

For dry runs that only refresh `CLAUDE.md`:

```powershell
policy-claude --pack cpp.low_latency --no-exec "帮我写一个 C++20 低延迟队列"
```

To enhance a different project with this policy repository:

```powershell
policy-claude --root D:\work\target-project --policy-root D:\MilesLi\ai-policy-runtime --pack cpp.low_latency "帮我写一个低延迟队列"
```

Pass Claude Code CLI options before the task with repeated `--claude-arg`:

```powershell
policy-claude --pack cpp.low_latency --claude-arg "--dangerously-skip-permissions" "帮我写一个 C++20 低延迟队列"
```

## Verify Outputs

```powershell
python -m ai_policy_runtime.cli verify --target path\to\output.cpp
```

The verifier writes `.policy/current/violations.json` and exits non-zero when
violations are found.

Verification is pluggable. The default verifier checks text-searchable
`forbid` rules, and additional deterministic verifiers can implement the
`RuleVerifier` protocol.

## Run the MVP Workflow

```powershell
python -m ai_policy_runtime.cli run --pack cpp.low_latency --agent custom "帮我写一个 C++20 低延迟队列"
```

This performs:

```text
resolve -> inject -> optional verify
```

## Notes

- JSON skill files work with the Python standard library.
- YAML skill files are supported when `PyYAML` is installed.
- This version does not call an LLM. It produces Effective Rules that can be
  injected into an LLM/Agent runtime later.
