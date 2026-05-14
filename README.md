![AI Policy Runtime banner](docs/assets/banner.png)

AI Policy Runtime helps AI coding agents generate higher-quality code by giving
each task the right engineering policies before code is written. It resolves the
developer request into task context, activates relevant Skill packs, produces
Effective Rules, and injects those rules into tools such as Codex, Claude Code,
or a custom agent workflow.

## Why It Exists

AI coding agents work better when the rules are specific to the task instead of
stored as one large static instruction file. A C++20 low-latency API design task
needs different constraints than a general refactor, a review, or a frontend
change.

This runtime makes those rules explicit, reproducible, and inspectable:

- resolve the current task into structured context
- activate the matching Skills and policy packs
- reduce them into task-scoped Effective Rules
- inject the result into an agent-facing prompt or project instruction file
- optionally verify generated output against deterministic rules

## Install

```powershell
pip install -e .
```

For optional transformer-based semantic recall:

```powershell
pip install -e ".[semantic]"
```

The default runtime does not call an LLM and does not download models. It uses
deterministic analysis first, then the best configured semantic matcher when
available.

## Quick Start

Resolve a task into agent-facing Effective Rules:

```powershell
python -m ai_policy_runtime.cli resolve `
  --pack cpp.production_refinement `
  "Refactor this C++20 code so it is not just working. Reduce complexity and preserve safety."
```

Example output:

```text
# Effective Rules for Current Task

## Task Context

- Language: C++
- Standard: C++20
- Refinement Requested: true
- Behavior Preservation Required: true
- Task Type: refactor_code
- Tags: code-quality, complexity, cpp, cpp20, refactoring, safety

## HARD Rules

- Preserve the existing observable behavior while reducing complexity unless the task explicitly asks for a behavior change.
- Avoid undefined behavior.
- Preserve ownership and lifetime safety.

## Verification Requirements

- Verify behavior preservation.
- Verify the refactoring reduced accidental complexity without introducing over-abstraction.
```

Explain the detected task context:

```powershell
python -m ai_policy_runtime.cli explain `
  "Refactor this C++20 code so it is not just working. Reduce complexity and preserve safety."
```

Validate Skills and packs:

```powershell
python -m ai_policy_runtime.cli validate
```

Run the bundled example:

```powershell
python examples/cpp_low_latency.py
```

Run tests:

```powershell
python -m unittest discover -s tests
```

## Use With Agents

Inject Effective Rules into a generated prompt, Codex instructions, or Claude
instructions:

```powershell
python -m ai_policy_runtime.cli inject --target custom
python -m ai_policy_runtime.cli inject --target codex
python -m ai_policy_runtime.cli inject --target claude
```

Run Codex through the policy wrapper:

```powershell
policy-codex `
  --pack cpp.production_refinement `
  "Refactor this C++20 code so it is not just working. Reduce complexity and preserve safety."
```

Run Claude Code through the policy wrapper:

```powershell
policy-claude `
  --pack cpp.production_refinement `
  "Refactor this C++20 code so it is not just working. Reduce complexity and preserve safety."
```

Use this repository as a Codex plugin to resolve each submitted prompt through
the runtime hook. The plugin files live in:

```text
.codex-plugin/plugin.json
hooks/hooks.json
hooks/user_prompt_submit.py
```

A VS Code extension is also included in `vscode-extension/`. It writes
workspace configuration to `.policy/config.json` so the Codex hook can enable
or disable packs without hand-editing environment variables.

## Programmatic Use

```python
from ai_policy_runtime import PolicyRuntime, RuntimeConfig

runtime = PolicyRuntime(RuntimeConfig.from_values(root="."))
result = runtime.resolve(
    "Refactor this C++20 code so it is not just working. "
    "Reduce complexity and preserve safety.",
    ("cpp.production_refinement",),
)
```

To apply this policy repository to another project, keep the target project root
separate from the policy asset root:

```python
runtime = PolicyRuntime(
    RuntimeConfig.from_values(
        root=r"D:\work\target-project",
        policy_root=r"D:\MilesLi\ai-policy-runtime",
    )
)
result = runtime.resolve(
    "Refactor this C++20 code so it is not just working. "
    "Reduce complexity and preserve safety.",
    ("cpp.production_refinement",),
)
```

In this mode, the target project receives `.policy/current/`, `AGENTS.md`, or
`CLAUDE.md`, while Skills and packs are loaded from `policy_root`.

## Outputs

`resolve` writes the current task state to `.policy/current/`:

```text
task-context.json
effective-rules.json
effective-rules.yaml
effective-prompt.md
trace.json
```

Verification writes:

```text
.policy/current/violations.json
```

Run verification against generated output:

```powershell
python -m ai_policy_runtime.cli verify --target path\to\output.cpp
```

## Repository Map

```text
ai_policy_runtime/
  domain/          TaskContext, Skill, Rule, SkillPack, diagnostics, config
  infrastructure/  YAML/JSON loading, condition evaluation, schema loading
  services/        registry, engine, validation, rendering, verification
  application/     PolicyRuntime orchestration
  interfaces/      CLI and agent adapters
  task_analysis/   exact analysis, project scanning, semantic recall
skills/            Skill DSL files
packs/             reusable policy packs
schemas/           JSON Schemas for Skills, packs, and Effective Rules
hooks/             Codex plugin hook
vscode-extension/  VS Code configuration surface
docs/              design and usage documentation
```

## Documentation

- [Usage Guide](docs/usage.md): CLI commands, wrappers, plugin setup, VS Code,
  embeddings, cache, and verification details.
- [Skill Policy Runtime](docs/skill_policy_runtime.md): runtime model and core
  concepts.
- [Automation Strategy](docs/policy_runtime_automation_strategy.md): agent
  integration lifecycle and injection strategy.
- [Skill DSL Syntax](docs/skill_dsl_syntax_specification.md): Skill file format.
- [Effective Rules Output](docs/effective_rules_output_specification.md):
  generated rule output contract.
- [C++ Skill Library Design](docs/cpp_skill_library_design.md): current C++
  policy library structure.

## Notes

- JSON skill files work with the Python standard library.
- YAML skill files are supported through `PyYAML`.
- The runtime produces Effective Rules for AI agents; it is not itself an LLM.
