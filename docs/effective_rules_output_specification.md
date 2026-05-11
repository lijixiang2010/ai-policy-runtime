# Effective Rules Output Specification

## Abstract

This document defines the output format of Effective Rules in a Skill DSL and Policy Runtime system.

Effective Rules are the task-specific policy output produced after Skill activation, Rule IR normalization, conflict resolution, and rule reduction. They are not raw Skills, not the full Skill Registry, and not the internal Rule IR. They are the final reduced rules that should guide the AI agent for the current task.

A production Policy Runtime should generate two standard outputs:

1. **`effective-rules.yaml`** — structured output for machines, tools, verification, caching, tracing, and replay.
2. **`effective-prompt.md`** — rendered output for AI agents, system prompts, `AGENTS.md`, `CLAUDE.md`, or other agent context injection mechanisms.

The two outputs serve different purposes and should not be collapsed into one format.

---

## Table of Contents

1. Problem Definition
2. Position in the Policy Runtime
3. Output Design Principles
4. Required Output Artifacts
5. `effective-rules.yaml`
6. `effective-prompt.md`
7. Recommended Filesystem Layout
8. Agent Injection Methods
9. Trace and Reproducibility
10. Verification and Repair Usage
11. Lifecycle of Effective Rules
12. Complete Example
13. Implementation Guidance
14. Validation Requirements
15. Conclusion

---

## 1. Problem Definition

Skills are reusable rule modules. A project may contain many Skills across platform, domain, project, task, and user levels.

However, an AI agent should not receive the entire Skill library. The agent only needs the rules that are relevant to the current task.

Therefore, the Policy Runtime must compute a task-specific output:

```text
Current Task
    ↓
Task Context
    ↓
Active Skills
    ↓
Rule IR
    ↓
Conflict Resolution
    ↓
Rule Reduction
    ↓
Effective Rules
```

The final output must answer:

- What rules apply to this task?
- Which rules are mandatory?
- Which rules are recommendations?
- Which preferences should guide tradeoffs?
- Which exceptions are allowed?
- Which verification checks are required?
- Where did each rule come from?
- How should this be injected into the agent?

---

## 2. Position in the Policy Runtime

Effective Rules are generated after the following steps:

```text
User Input
    ↓
Task Analyzer
    ↓
Task Context
    ↓
Skill Registry
    ↓
Skill Activation
    ↓
Object Form Rules
    ↓
Rule IR Normalization
    ↓
Conflict Resolution
    ↓
Rule Reduction
    ↓
Effective Rules
    ↓
Agent Injection
```

Effective Rules are downstream of Skill DSL and Rule IR.

They should not contain inactive Skills, unresolved conflicts, redundant rules, shadowed rules, or internal registry metadata that the agent does not need.

They should contain concise task context, final active rules, exceptions, verification requirements, and trace metadata sufficient for debugging and replay.

---

## 3. Output Design Principles

### 3.1 Separate Machine Format from Agent Format

The Policy Runtime should output both:

```text
effective-rules.yaml   # machine-readable
effective-prompt.md    # agent-readable
```

The machine-readable format is used by the system. The rendered Markdown format is used by the AI agent.

### 3.2 Do Not Give the Agent Raw Skills

The agent should not receive the complete Skill library. Large Skill libraries create unnecessary context pressure and increase the probability of conflict, ambiguity, and irrelevant behavior.

The agent should receive only the reduced rules for the current task.

### 3.3 Preserve Traceability

Each Effective Rule should retain a source reference:

```yaml
source:
  skill: cpp.standard.cpp20.best_practices
  rule: cpp20.prefer_span_for_contiguous_ranges
```

This allows debugging, auditing, and rule tuning.

### 3.4 Keep Agent-Facing Rules Concise

The agent-facing Markdown should be short, direct, and actionable.

Long rationales, full Skill metadata, and internal conflict history should stay in structured trace files.

### 3.5 Support Verification

Effective Rules should identify which checks are required or recommended after the agent acts.

This allows the Policy Runtime to close the loop:

```text
Generate
    ↓
Verify
    ↓
Repair
    ↓
Re-verify
```

---

## 4. Required Output Artifacts

A complete runtime output should include:

```text
.policy/
└── current/
    ├── task-context.json
    ├── effective-rules.yaml
    ├── effective-prompt.md
    ├── trace.json
    └── violations.json
```

| File | Purpose |
|---|---|
| `task-context.json` | Structured task analysis result |
| `effective-rules.yaml` | Canonical machine-readable Effective Rules |
| `effective-prompt.md` | Agent-facing rendered policy |
| `trace.json` | Activation, resolution, and reduction trace |
| `violations.json` | Verification and repair results |

For task history, the runtime may also use:

```text
.policy/
└── tasks/
    └── <task_id>/
        ├── task-context.json
        ├── effective-rules.yaml
        ├── effective-prompt.md
        ├── trace.json
        └── violations.json
```

---

## 5. `effective-rules.yaml`

### 5.1 Purpose

`effective-rules.yaml` is the canonical structured output of the Policy Runtime.

It is used by runtime components, verification tools, repair loops, trace systems, wrappers, adapters, tests, replay, and debugging.

It should be deterministic and stable.

### 5.2 Top-Level Structure

```yaml
effective_rules:
  schema_version: 1

  task:
    id: task_id
    summary: task summary
    context: {}

  hard: []
  soft: []
  preference: []
  exceptions: []
  verification: {}
  trace: {}
```

### 5.3 Field Definitions

| Field | Required | Meaning |
|---|---:|---|
| `schema_version` | Yes | Effective Rules schema version |
| `task` | Yes | Task metadata and context |
| `hard` | Yes | Mandatory rules |
| `soft` | Yes | Recommended rules |
| `preference` | Yes | Preference and ranking rules |
| `exceptions` | No | Allowed exceptions |
| `verification` | No | Verification requirements |
| `trace` | No | Source and runtime trace metadata |

### 5.4 Task Section

```yaml
task:
  id: task_2026_05_11_001
  summary: "Generate C++20 API for a low-latency matching engine"
  context:
    language: cpp
    standard: 20
    task_type: write_code
    hot_path: true
```

The task section should capture the structured context used to generate the rules.

### 5.5 HARD Rules

HARD rules define mandatory constraints.

```yaml
hard:
  - id: cpp.safety.no_undefined_behavior
    target: undefined_behavior
    action: forbid
    statement: "Avoid undefined behavior."
    source:
      skill: cpp.safety.undefined_behavior
      rule: cpp.safety.no_undefined_behavior
```

A HARD rule violation should either block the result or trigger repair.

### 5.6 SOFT Rules

SOFT rules define recommendations.

```yaml
soft:
  - id: cpp20.prefer_span_for_contiguous_ranges
    target: contiguous_range_parameter
    action: prefer
    statement: "Prefer std::span over pointer-and-size parameters for non-owning contiguous ranges."
    condition: "parameter_kind == 'contiguous_range'"
    exceptions:
      - "ABI boundary"
      - "C API boundary"
    requirements:
      - "If pointer and size are used, justify ABI, C API, or performance constraints."
    source:
      skill: cpp.standard.cpp20.best_practices
      rule: cpp20.prefer_span_for_contiguous_ranges
```

A SOFT rule violation should normally produce a warning, justification request, or repair suggestion.

### 5.7 Preference Rules

Preference rules guide choices among valid alternatives.

```yaml
preference:
  - id: cpp.preference.performance_over_readability_in_hot_path
    target: decision_priority
    action: prefer
    prefer: performance
    over: readability
    condition: "hot_path == true"
    statement: "Prefer performance over readability in hot paths, without violating safety rules."
```

Preferences must not override HARD rules.

### 5.8 Exceptions

Exceptions define allowed deviations.

```yaml
exceptions:
  - id: cpp.exception.c_api_boundary
    condition: "c_api_boundary == true"
    allow:
      - const_char_pointer
      - raw_pointer
      - pointer_and_size
    require:
      - "Keep C-compatible types at the boundary."
      - "Convert to modern C++ types internally when practical."
```

Exceptions should include requirements whenever they allow lower-level, legacy, or riskier idioms.

### 5.9 Verification Section

Verification requirements specify what should be checked after the agent acts.

```yaml
verification:
  required:
    - id: cpp.verify.standard_availability
      type: compiler_check
      statement: "Do not use facilities unavailable in the selected C++ standard."

    - id: cpp.verify.no_undefined_behavior
      type: static_analysis
      statement: "Check for obvious undefined behavior."

  recommended:
    - id: cpp.verify.api_intent
      type: llm_self_check
      statement: "Check whether parameter types express ownership and lifetime intent."
```

### 5.10 Trace Section

Trace metadata supports debugging and replay.

```yaml
trace:
  activated_skills:
    - cpp.safety.undefined_behavior
    - cpp.standard.cpp17.best_practices
    - cpp.standard.cpp20.best_practices
    - cpp.performance.hot_path
  reduced_rules:
    - source: cpp17.prefer_string_view
      status: active
    - source: cpp20.prefer_span
      status: active
  generated_at: "2026-05-11T00:00:00Z"
```

The trace section should be concise in `effective-rules.yaml`. A full trace can be stored in `trace.json`.

---

## 6. `effective-prompt.md`

### 6.1 Purpose

`effective-prompt.md` is the rendered, agent-facing policy document.

It is used by Codex via `AGENTS.md` injection, Claude Code via `CLAUDE.md` injection, direct system prompt insertion, custom agent wrappers, and IDE-side agent context.

It should be clear, short, and actionable.

### 6.2 Recommended Structure

```md
# Effective Rules for Current Task

## Task Context

- Language: C++
- Standard: C++20
- Task Type: Code generation
- Hot Path: true

## HARD Rules

- Avoid undefined behavior.
- Do not use facilities unavailable in C++20.
- Ownership and lifetime must be explicit.

## SOFT Rules

- Prefer `std::string_view` over `const char*` for read-only string parameters.
- Prefer `std::span` over pointer-and-size parameters for non-owning contiguous ranges.
- Prefer RAII for resource management.
- Minimize unnecessary allocation in hot paths.

## Preferences

- Safety has higher priority than performance.
- In hot paths, prefer performance over readability only when safety is not weakened.
- Prefer explicit interface intent over implicit convention.

## Exceptions

- At ABI or C API boundaries, `const char*`, raw pointers, or pointer-and-size pairs are allowed.
- If an exception is used, explain the reason clearly.

## Verification Requirements

- Check that the code is valid under C++20.
- Check that no unavailable standard-library facility is used.
- Check for obvious ownership, lifetime, and undefined-behavior risks.
```

### 6.3 Rendering Rules

The renderer should remove internal metadata unless useful to the agent, merge duplicate statements, group rules by strength, keep ordering stable, include only active exceptions, include only relevant verification requirements, and avoid long rationale text unless the task requires explanation.

### 6.4 Agent-Facing Wording

Use imperative, direct wording.

Preferred:

```text
Prefer `std::span` over pointer-and-size parameters for non-owning contiguous ranges.
```

Avoid:

```text
The system has activated a C++20 rule from cpp.standard.cpp20.best_practices indicating that std::span is often useful.
```

The agent-facing file should communicate what to do, not how the runtime derived it.

---

## 7. Recommended Filesystem Layout

### 7.1 Current Task Layout

```text
.policy/
└── current/
    ├── task-context.json
    ├── effective-rules.yaml
    ├── effective-prompt.md
    ├── trace.json
    └── violations.json
```

This layout supports the latest active task.

### 7.2 Task History Layout

```text
.policy/
└── tasks/
    └── task_2026_05_11_001/
        ├── task-context.json
        ├── effective-rules.yaml
        ├── effective-prompt.md
        ├── trace.json
        ├── agent-output.patch
        └── violations.json
```

This layout supports auditing and replay.

### 7.3 Step-Level Layout

For multi-step agents:

```text
.policy/
└── tasks/
    └── task_2026_05_11_001/
        └── steps/
            ├── step_001/
            │   ├── effective-rules.yaml
            │   └── effective-prompt.md
            └── step_002/
                ├── effective-rules.yaml
                └── effective-prompt.md
```

Step-level Effective Rules are useful when the agent switches from code generation to testing, documentation, build configuration, or review.

---

## 8. Agent Injection Methods

### 8.1 Direct Prompt Injection

For custom agent runtimes:

```python
rules = load(".policy/current/effective-rules.yaml")
prompt = render(".policy/current/effective-prompt.md")

agent.run(
    task=user_task,
    policy_prompt=prompt,
    structured_rules=rules
)
```

### 8.2 `AGENTS.md` Injection

For Codex-like workflows, the runtime may update a generated block:

```md
<!-- POLICY_RUNTIME_BEGIN -->
# Effective Rules for Current Task

...
<!-- POLICY_RUNTIME_END -->
```

The rest of the file remains manually maintained.

### 8.3 `CLAUDE.md` Injection

For Claude Code-like workflows, the same generated-block strategy can be used:

```md
<!-- POLICY_RUNTIME_BEGIN -->
...
<!-- POLICY_RUNTIME_END -->
```

### 8.4 Wrapper Command

A wrapper can automate the full sequence:

```bash
policy-codex "Implement a C++20 low-latency queue"
```

Equivalent flow:

```text
policy resolve
    ↓
policy render
    ↓
policy inject --target codex
    ↓
codex run
    ↓
policy verify
```

### 8.5 Hook-Based Injection

For agents that support hooks:

```text
BeforeAgentRun
    → generate Effective Rules

BeforeEdit
    → optionally generate file-level Effective Rules

AfterEdit
    → verify against Effective Rules

Stop
    → summarize violations
```

---

## 9. Trace and Reproducibility

Effective Rules should be reproducible.

The runtime should store input task, task context, active skills, rule versions, conflict resolution decisions, reduced rules, rendered prompt, and verification results.

A full trace may look like:

```json
{
  "task_id": "task_2026_05_11_001",
  "input": "Implement a C++20 low-latency queue",
  "task_context": {
    "language": "cpp",
    "standard": 20,
    "hot_path": true
  },
  "activated_skills": [
    "cpp.core.baseline",
    "cpp.safety.lifetime",
    "cpp.standard.cpp20.best_practices"
  ],
  "conflicts": [],
  "reduced_rules": [
    {
      "source_rule": "cpp20.prefer_span_for_contiguous_ranges",
      "status": "active"
    }
  ]
}
```

Trace data should not normally be injected into the agent. It is for humans and tooling.

---

## 10. Verification and Repair Usage

The same Effective Rules should be used after generation.

### 10.1 Verification Flow

```text
Agent Output
    ↓
Load effective-rules.yaml
    ↓
Run verification checks
    ↓
Write violations.json
```

### 10.2 Example Violation

```json
{
  "violations": [
    {
      "rule_id": "cpp20.prefer_span_for_contiguous_ranges",
      "severity": "warning",
      "message": "Function uses pointer and size for a non-owning contiguous range.",
      "requirement": "Justify ABI, C API, or performance constraint."
    }
  ]
}
```

### 10.3 Repair Prompt

The repair prompt should be derived from violations and Effective Rules:

```md
The previous output violates the current Effective Rules.

Violations:

- `cpp20.prefer_span_for_contiguous_ranges`:
  Function uses pointer and size for a non-owning contiguous range.

Repair requirements:

- Prefer `std::span` unless ABI or C API compatibility requires pointer and size.
- If pointer and size remain, provide a clear justification.
```

---

## 11. Lifecycle of Effective Rules

Effective Rules can be generated at multiple levels.

### 11.1 Task-Level

Generated once per user task.

```text
User task → Effective Rules
```

### 11.2 Step-Level

Generated for each agent subtask.

```text
write code → C++ rules
write tests → testing rules
write docs → documentation rules
edit CMakeLists.txt → build-system rules
```

### 11.3 File-Level

Generated when the agent modifies a specific file type.

```text
*.cpp           → C++ rules
CMakeLists.txt → CMake rules
README.md      → documentation rules
*.qml          → QML/UI rules
```

### 11.4 Session-Level

Generated for long-running agent sessions. Session-level rules should remain stable but may be refined by task-level rules.

---

## 12. Complete Example

### 12.1 Input Task

```text
Implement a C++20 API for a low-latency matching engine. The API should accept a non-owning range of orders.
```

### 12.2 Task Context

`task-context.json`:

```json
{
  "task": {
    "id": "task_2026_05_11_001",
    "summary": "Implement a C++20 API for a low-latency matching engine.",
    "context": {
      "language": "cpp",
      "standard": 20,
      "task_type": "write_code",
      "hot_path": true,
      "parameter_kind": "contiguous_range",
      "ownership_required": false
    }
  }
}
```

### 12.3 Structured Output

`effective-rules.yaml`:

```yaml
effective_rules:
  schema_version: 1

  task:
    id: task_2026_05_11_001
    summary: "Implement a C++20 API for a low-latency matching engine."
    context:
      language: cpp
      standard: 20
      task_type: write_code
      hot_path: true
      parameter_kind: contiguous_range
      ownership_required: false

  hard:
    - id: cpp.safety.no_undefined_behavior
      target: undefined_behavior
      action: forbid
      statement: "Avoid undefined behavior."
      source:
        skill: cpp.safety.undefined_behavior
        rule: cpp.safety.no_undefined_behavior

    - id: cpp.standard.no_unavailable_facility
      target: standard_availability
      action: forbid
      statement: "Do not use facilities unavailable in C++20."
      source:
        skill: cpp.standard.cpp20.best_practices
        rule: cpp20.do_not_use_newer_facility_when_standard_too_old

  soft:
    - id: cpp20.prefer_span_for_contiguous_ranges
      target: contiguous_range_parameter
      action: prefer
      statement: "Prefer std::span over pointer-and-size parameters for non-owning contiguous ranges."
      condition: "parameter_kind == 'contiguous_range' and ownership_required == false"
      exceptions:
        - "ABI boundary"
        - "C API boundary"
      requirements:
        - "If pointer and size are used, justify ABI, C API, or performance constraints."
      source:
        skill: cpp.standard.cpp20.best_practices
        rule: cpp20.prefer_span_for_contiguous_ranges

    - id: cpp.performance.minimize_hot_path_allocation
      target: allocation
      action: recommend
      statement: "Minimize unnecessary allocation in hot paths."
      condition: "hot_path == true"
      source:
        skill: cpp.performance.hot_path
        rule: cpp.performance.minimize_hot_path_allocation

  preference:
    - id: cpp.preference.performance_in_hot_path
      target: decision_priority
      action: prefer
      prefer: performance
      over: readability
      condition: "hot_path == true"
      statement: "Prefer performance over readability in hot paths, without weakening safety."

    - id: cpp.preference.safety_over_performance
      target: decision_priority
      action: prefer
      prefer: safety
      over: performance
      statement: "Safety remains higher priority than performance."

  exceptions:
    - id: cpp.exception.c_api_boundary
      condition: "c_api_boundary == true"
      allow:
        - raw_pointer
        - pointer_and_size
      require:
        - "Keep C-compatible types at the boundary."
        - "Convert to modern C++ types internally when practical."

  verification:
    required:
      - id: cpp.verify.standard_availability
        type: compiler_check
        statement: "Compile as C++20 and reject unavailable facilities."

      - id: cpp.verify.no_undefined_behavior
        type: static_analysis
        statement: "Check for obvious undefined behavior and lifetime risks."

  trace:
    activated_skills:
      - cpp.safety.undefined_behavior
      - cpp.safety.lifetime
      - cpp.standard.cpp20.best_practices
      - cpp.performance.hot_path
    generated_at: "2026-05-11T00:00:00Z"
```

### 12.4 Rendered Agent Output

`effective-prompt.md`:

```md
# Effective Rules for Current Task

## Task Context

- Language: C++
- Standard: C++20
- Task Type: Code generation
- Hot Path: true
- Parameter Kind: non-owning contiguous range

## HARD Rules

- Avoid undefined behavior.
- Do not use facilities unavailable in C++20.

## SOFT Rules

- Prefer `std::span` over pointer-and-size parameters for non-owning contiguous ranges.
- Minimize unnecessary allocation in hot paths.

## Preferences

- Safety remains higher priority than performance.
- In hot paths, prefer performance over readability only when safety is not weakened.

## Exceptions

- At ABI or C API boundaries, raw pointers and pointer-and-size pairs are allowed.
- If an exception is used, explain the reason clearly.

## Verification Requirements

- Compile as C++20.
- Check for obvious undefined behavior and lifetime risks.
```

---

## 13. Implementation Guidance

### 13.1 Renderer Inputs

The renderer should take Task Context, reduced Rule IR, active exceptions, verification requirements, and optional trace metadata.

### 13.2 Renderer Outputs

The renderer should produce:

- `effective-rules.yaml`
- `effective-prompt.md`
- optionally `effective-rules.json`

### 13.3 Stable Ordering

Rules should be rendered in stable order:

1. HARD
2. SOFT
3. PREFERENCE
4. Exceptions
5. Verification

Within each group:

1. higher priority first
2. more specific conditions first
3. deterministic rule id ordering as fallback

### 13.4 Redaction

The agent-facing prompt should omit internal conflict logs, inactive skills, rule version details unless necessary, long rationale text, and irrelevant trace metadata.

### 13.5 Source Retention

The structured output should keep `source` fields. The Markdown output usually should not.

---

## 14. Validation Requirements

A valid `effective-rules.yaml` must satisfy:

- `schema_version` exists.
- `task.context` exists.
- Each rule has `id`, `target`, `action`, `statement`, and `source`.
- HARD rules do not conflict with each other.
- SOFT rules are already reduced.
- Preference cycles are resolved or reported.
- Exceptions are active or explicitly referenced by active rules.
- Verification requirements are linked to active rules where possible.
- The rendered Markdown corresponds to the structured YAML.

The runtime should support a validation command:

```bash
policy validate-effective .policy/current/effective-rules.yaml
```

---

## 15. Conclusion

Effective Rules are the final task-specific policy output of the Policy Runtime.

The correct output model is:

```text
Skill Object Form
    ↓
Rule IR
    ↓
Effective Rules YAML
    ↓
Effective Prompt Markdown
    ↓
Agent
```

Use:

```text
effective-rules.yaml
```

for systems, verification, tracing, and replay.

Use:

```text
effective-prompt.md
```

for AI agents, system prompts, `AGENTS.md`, `CLAUDE.md`, and wrapper-based injection.

The core rule is:

> The Policy Runtime should generate Effective Rules dynamically for each task and inject only the reduced, task-relevant policy into the agent.
