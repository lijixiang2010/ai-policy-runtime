# Skill DSL Design Specification

## Abstract

This document defines a Skill DSL for AI Policy Runtime systems. The DSL is designed to express constraints, recommendations, preferences, activation conditions, exceptions, and verification mappings in a form that is readable by humans, parseable by machines, and compilable into a normalized Rule IR.

The Skill DSL is not a prompt template. It is a structured policy definition format. Its purpose is to make AI behavior controllable through explicit rules that can be selected, normalized, resolved, reduced, injected into an agent context, and verified during or after execution.

The DSL supports two equivalent authoring representations:

1. **Clause Form**: a human-readable rule notation using keywords such as `WHEN`, `MUST`, `SHOULD`, `ALLOW`, `PREFER`, `UNLESS`, and `REQUIRE`.
2. **Object Form**: a structured YAML/JSON representation intended for real `.skill.yaml` files and Policy Runtime parsing.

The runtime should treat Object Form as the canonical persistent format. Clause Form may be used in documentation, design review, editor assistance, or as syntactic sugar that compiles into Object Form or directly into Rule IR.

---

## Table of Contents

1. Problem Definition
2. Design Positioning
3. Core Concepts
4. Design Goals
5. Non-Goals
6. DSL Layering Model
7. Clause Form, Object Form, and Rule IR
8. Clause Form Syntax
9. Object Form Syntax
10. Clause Form to Object Form Mapping
11. Object Form to Rule IR Mapping
12. Skill File Structure
13. Metadata Model
14. Scope and Activation Model
15. Rule Model
16. Rule Strengths
17. Rule Semantics
18. Condition Expression Syntax
19. Priority and Conflict Policy
20. Exceptions
21. Dependencies and Incompatibilities
22. Verification Mapping
23. Normalized Rule IR
24. Effective Rule Set
25. Skill Composition
26. Skill Packs
27. Domain Skill Library Design
28. C++ Standard-Aware Skill Example
29. Parsing and Compilation Pipeline
30. Validation and Diagnostics
31. Integration with Policy Runtime
32. Practical Implementation Notes
33. Limitations
34. Conclusion

---

## 1. Problem Definition

Existing AI skill systems are often written as free-form natural language. This makes them easy to write but difficult to parse, compare, verify, compose, and scale.

A production-grade AI system requires more than prompt instructions. It requires a policy layer that can answer:

- Which skills apply to the current task?
- Which rules are active in the current context?
- Which rules conflict?
- Which rules override or constrain others?
- Which rules should be injected into the agent?
- Which rules can be verified by tools?
- Which violations require repair?

The Skill DSL addresses these problems by turning skills into structured rule modules.

---

## 2. Design Positioning

The Skill DSL sits between natural language and formal logic.

It is not pure natural language, because unrestricted text cannot be reliably parsed or merged.

It is not pure mathematical logic, because many useful AI constraints are heuristic, contextual, preference-based, or not fully decidable.

The DSL is therefore a semi-formal rule language:

```text
Natural language intent
    ↓
Skill DSL
    ↓
Object Form
    ↓
Rule IR
    ↓
Effective Rules
    ↓
AI Runtime
```

---

## 3. Core Concepts

### 3.1 Skill

A Skill is a reusable policy module. It contains metadata, activation conditions, rules, exceptions, dependencies, and verification mappings.

### 3.2 Rule

A Rule is a single policy statement with a strength, target, action, condition, and optional exception.

### 3.3 Rule Strength

The DSL distinguishes rule strengths:

| Strength | Meaning | Typical Runtime Behavior |
|---|---|---|
| `HARD` | Mandatory constraint | Must be enforced or reported as an error |
| `SOFT` | Recommendation | Should guide generation and review |
| `PREFERENCE` | Ranking preference | Used to choose among valid alternatives |

### 3.4 Effective Rules

Effective Rules are the final rules produced for a specific task after activation, normalization, conflict resolution, and rule reduction.

### 3.5 Rule IR

Rule IR is the normalized internal representation used by the Policy Runtime. It is the execution-level representation, not the human authoring format.

---

## 4. Design Goals

The DSL is designed to satisfy the following goals:

1. Human-readable rule authoring.
2. Stable machine parsing.
3. Explicit activation.
4. Explicit rule strength.
5. Explicit conditions and exceptions.
6. Support for conflict detection.
7. Support for rule reduction.
8. Support for verification mapping.
9. Support for large domain skill libraries.
10. Compatibility with existing AI agents through Effective Rules injection.

---

## 5. Non-Goals

The DSL does not attempt to:

- Replace the LLM.
- Encode all human judgment as formal logic.
- Prove global optimality of an AI output.
- Eliminate all ambiguity.
- Replace static analyzers, linters, or compilers.
- Guarantee that the AI always obeys rules without verification.

The DSL is a policy specification layer, not a complete correctness proof system.

---

## 6. DSL Layering Model

The Skill DSL uses a layered model:

```text
Clause Form        Human-facing rule expression
Object Form        Canonical persisted skill file representation
Rule IR            Normalized runtime representation
Effective Rules    Reduced task-specific rules injected into the AI
```

Each layer has a different purpose:

| Layer | Primary User | Purpose |
|---|---|---|
| Clause Form | Humans | Discuss and document rules clearly |
| Object Form | Skill authors and tools | Store and parse real skill files |
| Rule IR | Runtime | Normalize, compare, resolve, and reduce rules |
| Effective Rules | Agent | Constrain AI behavior for the current task |

---

## 7. Clause Form, Object Form, and Rule IR

This section is essential.

The Skill DSL supports two equivalent syntax forms:

1. **Clause Form**
2. **Object Form**

They are not two different DSLs. They are two representations of the same rule model.

### 7.1 Clause Form

Clause Form is designed for human reading and discussion.

Example:

```text
WHEN language == "cpp" AND standard >= 17
SHOULD prefer std::string_view over const char*
UNLESS abi_boundary == true OR c_api_boundary == true
REQUIRE justification if const char* is used
```

Clause Form is useful in:

- Design documents
- Human review
- Rule discussions
- Documentation
- Editor previews
- LLM-facing explanations

Clause Form is not recommended as the canonical storage format because it is harder to validate, patch, diff, and compile reliably.

### 7.1.1 Authoring Language Boundary

Persistent Skill DSL files under `skills/` must be authored in English only,
including `domain_aliases`, `trigger_aliases`, `trigger_semantics`,
`when_text_matches`, `semantic_match`, rule statements, rationale, and
authoring notes.

Do not add translated keyword lists or non-English trigger phrases to Skill DSL
files to fix multilingual recall. Multilingual user input is handled by the
embedding provider and semantic task analysis. If a non-English daily request
does not recall the right skill, improve the English semantic anchor phrases so
they describe realistic user intent more directly, then add multilingual test
fixtures that prove the embedding path maps that request to the English DSL.

This rule exists to keep the DSL canonical, reviewable, and deduplicated. A past
recall bug for a daily request equivalent to "commit code changes" was fixed by
adding English semantic anchors and semantic bootstrap logic, not by adding the
user's language to the Git skill.

### 7.2 Object Form

Object Form is designed for real skill files.

Example:

```yaml
rules:
  soft:
    - id: cpp17.prefer_string_view
      when: >
        language == "cpp"
        and standard >= 17
        and parameter_kind == "read_only_string"
        and ownership_required == false
      should: >
        Prefer std::string_view over const char* for read-only string parameters.
      unless: >
        abi_boundary == true
        or c_api_boundary == true
      require:
        - Justify if const char* is used.
      target: string_parameter
      action: prefer
      prefer: std::string_view
      over:
        - const char*
```

Object Form is useful in:

- `.skill.yaml` files
- Runtime parsing
- Validation
- Conflict resolution
- Rule reduction
- Version control
- Tooling and schema validation

### 7.3 Rule IR

Rule IR is the normalized runtime representation.

Example:

```json
{
  "rule_id": "cpp17.prefer_string_view",
  "strength": "SOFT",
  "target": "string_parameter",
  "action": "PREFER",
  "value": "std::string_view",
  "over": ["const char*"],
  "condition": {
    "language": "cpp",
    "standard": {">=": 17},
    "parameter_kind": "read_only_string",
    "ownership_required": false
  },
  "exception_condition": {
    "or": [
      {"abi_boundary": true},
      {"c_api_boundary": true}
    ]
  },
  "requirements": [
    "Justify if const char* is used."
  ]
}
```

Rule IR is used by:

- Activation Engine
- Conflict Resolver
- Rule Reduction Engine
- Verification Engine
- Renderer

### 7.4 Canonical Flow

The recommended flow is:

```text
Clause Form
    ↓ optional parsing
Object Form
    ↓ validation
Rule IR
    ↓ conflict resolution and reduction
Effective Rules
    ↓ injection into AI agent
```

For production systems, the canonical source of truth should be Object Form.

### 7.5 Summary

| Representation | Purpose | Recommended Use |
|---|---|---|
| Clause Form | Human-readable expression | Documentation and rule discussion |
| Object Form | Stable structured storage | Real skill files |
| Rule IR | Runtime execution | Internal policy engine |
| Effective Rules | Agent context | AI-facing final rules |

The accurate rule is:

> Clause Form is the expression layer. Object Form is the storage layer. Rule IR is the execution layer.

---

## 8. Clause Form Syntax

Clause Form is a semi-formal rule notation based on structured keywords.

### 8.1 Core Keywords

| Keyword | Meaning |
|---|---|
| `WHEN` | Defines activation condition for the rule |
| `IF` | Alias of `WHEN` in explanatory text |
| `UNLESS` | Defines exception condition |
| `MUST` | Defines mandatory required behavior |
| `MUST NOT` | Defines mandatory forbidden behavior |
| `SHOULD` | Defines recommended behavior |
| `SHOULD NOT` | Defines discouraged behavior |
| `MAY` | Defines permitted behavior |
| `ALLOW` | Defines an allowed exception or permitted behavior |
| `PREFER` | Defines a preference ranking |
| `OVER` | Separates preferred option from less preferred option |
| `REQUIRE` | Defines an additional requirement when a rule or exception applies |

### 8.2 Basic Clause Forms

#### HARD Requirement

```text
WHEN <condition>
MUST <required behavior>
```

#### HARD Prohibition

```text
WHEN <condition>
MUST NOT <forbidden behavior>
```

#### SOFT Recommendation

```text
WHEN <condition>
SHOULD <recommended behavior>
```

#### SOFT Discouragement

```text
WHEN <condition>
SHOULD NOT <discouraged behavior>
```

#### Allowed Exception

```text
WHEN <condition>
ALLOW <behavior>
REQUIRE <requirement>
```

#### Preference

```text
WHEN <condition>
PREFER <A> OVER <B>
```

#### Exception

```text
WHEN <condition>
SHOULD <behavior>
UNLESS <exception condition>
REQUIRE <requirement if exception is used>
```

### 8.3 Clause Form Examples

#### C++17 string view rule

```text
WHEN language == "cpp" AND standard >= 17 AND parameter_kind == "read_only_string"
SHOULD prefer std::string_view over const char*
UNLESS abi_boundary == true OR c_api_boundary == true OR null_terminated_required == true
REQUIRE justification if const char* is used
```

#### C++20 span rule

```text
WHEN language == "cpp" AND standard >= 20 AND parameter_kind == "contiguous_range"
SHOULD prefer std::span<T> over pointer-and-size parameters
UNLESS abi_boundary == true OR c_api_boundary == true
REQUIRE justification if raw pointer and size are used
```

#### Safety rule

```text
WHEN language == "cpp"
MUST avoid undefined behavior
```

#### API prohibition

```text
WHEN language == "cpp"
MUST NOT use gets or strcpy
```

#### Hot path exception

```text
WHEN hot_path == true
ALLOW raw pointer usage
REQUIRE performance justification and explicit ownership explanation
```

### 8.4 Clause Form Grammar

A simplified grammar:

```ebnf
rule_clause       ::= when_clause? main_clause unless_clause? require_clause*
when_clause       ::= "WHEN" condition
main_clause       ::= must_clause
                    | must_not_clause
                    | should_clause
                    | should_not_clause
                    | allow_clause
                    | prefer_clause
must_clause       ::= "MUST" statement
must_not_clause   ::= "MUST NOT" statement
should_clause     ::= "SHOULD" statement
should_not_clause ::= "SHOULD NOT" statement
allow_clause      ::= "ALLOW" statement
prefer_clause     ::= "PREFER" value "OVER" value
unless_clause     ::= "UNLESS" condition
require_clause    ::= "REQUIRE" statement
condition         ::= expression
statement         ::= free_text_with_structured_terms
value             ::= identifier | string | free_text
```

Clause Form intentionally permits natural-language statements after the keyword. The structured meaning comes from the keyword and surrounding fields.

---

## 9. Object Form Syntax

Object Form is the recommended format for real skill files.

### 9.1 Minimal Rule Object

```yaml
rules:
  soft:
    - id: rule.id
      when: condition expression
      should: recommendation statement
      target: semantic_target
      action: prefer
```

### 9.2 Complete Rule Object

```yaml
rules:
  soft:
    - id: rule.id
      title: Human-readable title
      when: condition expression
      should: recommendation statement
      unless: exception condition
      require:
        - additional requirement
      target: semantic_target
      action: prefer
      prefer: preferred_value
      over:
        - less_preferred_value
      rationale: >
        Explanation of why this rule exists.
```

### 9.3 Rule Groups

Rules are grouped by strength:

```yaml
rules:
  hard:
    - id: ...
      must: ...

  soft:
    - id: ...
      should: ...

  preference:
    - id: ...
      prefer: ...
      over: ...
```

### 9.4 HARD Rule Object

```yaml
rules:
  hard:
    - id: cpp.safety.no_undefined_behavior
      when: language == "cpp"
      must: Avoid undefined behavior.
      target: undefined_behavior
      action: require
```

### 9.5 HARD Prohibition Object

```yaml
rules:
  hard:
    - id: cpp.api.no_gets
      when: language == "cpp"
      must_not: Use gets.
      target: api_usage
      action: forbid
      value: gets
```

### 9.6 SOFT Recommendation Object

```yaml
rules:
  soft:
    - id: cpp17.prefer_string_view
      when: language == "cpp" and standard >= 17
      should: Prefer std::string_view over const char*.
      target: string_parameter
      action: prefer
      prefer: std::string_view
      over:
        - const char*
```

### 9.7 SOFT Discouragement Object

```yaml
rules:
  soft:
    - id: cpp.api.discourage_raw_owning_pointer
      when: language == "cpp"
      should_not: Use raw owning pointers for resource ownership.
      target: ownership
      action: discourage
```

### 9.8 Preference Object

```yaml
rules:
  preference:
    - id: cpp.preference.safety_over_performance
      when: language == "cpp" and hot_path != true
      prefer: safety
      over: performance
      target: decision_priority
```

### 9.9 Exception Object

```yaml
exceptions:
  - id: cpp.exception.c_api_boundary
    when: c_api_boundary == true
    allow:
      - const_char_pointer
      - raw_pointer
      - pointer_and_size
    require:
      - Keep C-compatible types at the boundary.
      - Convert to modern C++ types internally when practical.
```

---

## 10. Clause Form to Object Form Mapping

This section defines the complete correspondence between Clause Form and Object Form.

### 10.1 Keyword Mapping

| Clause Form | Object Form | Rule Group | Rule IR Meaning |
|---|---|---|---|
| `WHEN <condition>` | `when:` | any | `condition` |
| `IF <condition>` | `when:` | any | `condition` |
| `UNLESS <condition>` | `unless:` | any | `exception_condition` |
| `MUST <statement>` | `must:` | `rules.hard` | `strength=HARD`, `action=REQUIRE` |
| `MUST NOT <statement>` | `must_not:` | `rules.hard` | `strength=HARD`, `action=FORBID` |
| `SHOULD <statement>` | `should:` | `rules.soft` | `strength=SOFT`, `action=RECOMMEND` or `PREFER` |
| `SHOULD NOT <statement>` | `should_not:` | `rules.soft` | `strength=SOFT`, `action=DISCOURAGE` |
| `MAY <statement>` | `may:` | `rules.soft` or `exceptions` | `action=ALLOW` |
| `ALLOW <statement>` | `allow:` | `rules.soft` or `exceptions` | `action=ALLOW` |
| `PREFER <A> OVER <B>` | `prefer:` + `over:` | `rules.preference` or `rules.soft` | `action=PREFER` |
| `REQUIRE <statement>` | `require:` | any | `requirements` |

### 10.2 Strength Mapping

| Clause Keyword | Object Group | Strength |
|---|---|---|
| `MUST` | `rules.hard` | `HARD` |
| `MUST NOT` | `rules.hard` | `HARD` |
| `SHOULD` | `rules.soft` | `SOFT` |
| `SHOULD NOT` | `rules.soft` | `SOFT` |
| `ALLOW` | `rules.soft` or `exceptions` | `SOFT` or exception |
| `PREFER` | `rules.preference` | `PREFERENCE` |
| `REQUIRE` | same rule or exception | requirement, not a standalone strength |

### 10.3 Action Mapping

| Clause Keyword | Object Action | Rule IR Action |
|---|---|---|
| `MUST` | `require` | `REQUIRE` |
| `MUST NOT` | `forbid` | `FORBID` |
| `SHOULD` | `recommend` or `prefer` | `RECOMMEND` or `PREFER` |
| `SHOULD NOT` | `discourage` | `DISCOURAGE` |
| `ALLOW` | `allow` | `ALLOW` |
| `PREFER` | `prefer` | `PREFER` |
| `REQUIRE` | `require` | additional requirement |

### 10.4 Example: Clause Form to Object Form

Clause Form:

```text
WHEN language == "cpp" AND standard >= 17 AND parameter_kind == "read_only_string"
SHOULD prefer std::string_view over const char*
UNLESS abi_boundary == true OR c_api_boundary == true
REQUIRE justification if const char* is used
```

Object Form:

```yaml
rules:
  soft:
    - id: cpp17.prefer_string_view
      when: >
        language == "cpp"
        and standard >= 17
        and parameter_kind == "read_only_string"
      should: >
        Prefer std::string_view over const char*.
      unless: >
        abi_boundary == true
        or c_api_boundary == true
      require:
        - Justify if const char* is used.
      target: string_parameter
      action: prefer
      prefer: std::string_view
      over:
        - const char*
```

Rule IR:

```json
{
  "rule_id": "cpp17.prefer_string_view",
  "strength": "SOFT",
  "target": "string_parameter",
  "action": "PREFER",
  "value": "std::string_view",
  "over": ["const char*"],
  "condition": {
    "language": "cpp",
    "standard": {">=": 17},
    "parameter_kind": "read_only_string"
  },
  "exception_condition": {
    "or": [
      {"abi_boundary": true},
      {"c_api_boundary": true}
    ]
  },
  "requirements": [
    "Justify if const char* is used."
  ]
}
```

### 10.5 Recommended Usage

The recommended usage model is:

| Usage Context | Preferred Form |
|---|---|
| Design discussion | Clause Form |
| Documentation | Clause Form plus Object Form example |
| Real `.skill.yaml` file | Object Form |
| Runtime normalization | Rule IR |
| Agent context injection | Effective Rules rendered as concise text or structured JSON |

---

## 11. Object Form to Rule IR Mapping

The Policy Runtime must compile Object Form into Rule IR.

### 11.1 Required Rule IR Fields

| IR Field | Source |
|---|---|
| `rule_id` | `id` |
| `strength` | parent group: `hard`, `soft`, `preference` |
| `target` | `target` |
| `action` | `action` or inferred from `must`, `must_not`, `should`, `should_not`, `prefer`, `allow` |
| `condition` | `when` |
| `exception_condition` | `unless` |
| `requirements` | `require` |
| `value` | `value`, `prefer`, `allow`, or parsed statement |
| `over` | `over` |
| `source_skill` | containing skill id |
| `priority` | skill priority and optional rule priority |

### 11.2 Inference Rules

If `action` is omitted, it may be inferred:

| Object Field | Inferred Action |
|---|---|
| `must` | `REQUIRE` |
| `must_not` | `FORBID` |
| `should` | `RECOMMEND` |
| `should_not` | `DISCOURAGE` |
| `allow` | `ALLOW` |
| `prefer` + `over` | `PREFER` |

For production systems, explicit `target` and `action` are recommended to reduce ambiguity.

---

## 12. Skill File Structure

A complete Skill file contains:

```yaml
skill:
  id: ...
  name: ...
  version: ...
  status: ...
  description: ...
  level: ...
  domain: ...
  category: ...
  priority: ...
  tags: [...]
  capabilities: [...]
  activation:
    when: ...
    triggers: [...]
  dependencies: [...]
  incompatibilities: [...]

rules:
  hard: [...]
  soft: [...]
  preference: [...]

exceptions: [...]

verification: [...]

normalization_examples: [...]

effective_rule_examples: [...]

authoring_notes: [...]
```

The top-level sections are:

| Section | Purpose |
|---|---|
| `skill` | Metadata and activation |
| `rules` | Policy rules |
| `exceptions` | Reusable exception definitions |
| `verification` | Tool and evaluator mappings |
| `normalization_examples` | Documentation of expected IR |
| `effective_rule_examples` | Expected task-specific outputs |
| `authoring_notes` | Guidance for maintainers |

---

## 13. Metadata Model

Recommended metadata fields:

```yaml
skill:
  id: cpp.standard.cpp17.best_practices
  name: C++17 Best Practices
  version: 1.0.0
  status: stable
  level: domain
  domain: cpp
  category: standard
  priority: 80
  tags:
    - cpp
    - cpp17
  capabilities:
    - code_generation
    - code_review
```

### 13.1 Required Metadata Fields

| Field | Required | Meaning |
|---|---:|---|
| `id` | Yes | Stable skill identifier |
| `name` | Yes | Human-readable name |
| `version` | Yes | Skill version |
| `level` | Yes | Platform, domain, project, or task |
| `domain` | Yes | Main domain |
| `priority` | Yes | Ordering within level |
| `activation` | Yes | Conditions for activation |

### 13.2 Skill Levels

| Level | Meaning |
|---|---|
| `platform` | Global safety or platform policy |
| `domain` | Domain-level rules such as C++, Rust, UI design |
| `project` | Project-specific rules |
| `task` | Temporary task-specific rules |
| `user` | User-level preferences |

---

## 14. Scope and Activation Model

Skills must not all be activated at once.

Activation is based on task context:

```text
Task Context
    ↓
Domain Match
    ↓
Trigger Match
    ↓
Context Match
    ↓
Dependency Check
    ↓
Active Skill Set
```

Example activation:

```yaml
activation:
  when:
    language: cpp
    standard: ">=20"

  triggers:
    - write_code
    - refactor_code
    - review_code
```

A task context such as:

```json
{
  "language": "cpp",
  "standard": 20,
  "task_type": "write_code"
}
```

activates the skill if domain, trigger, and context conditions match.

---

## 15. Rule Model

A rule consists of:

| Field | Meaning |
|---|---|
| `id` | Stable rule identifier |
| `when` | Condition under which the rule applies |
| `must`, `must_not`, `should`, `should_not`, `allow`, `prefer` | Rule statement |
| `unless` | Exception condition |
| `require` | Additional requirements |
| `target` | Semantic target of the rule |
| `action` | Normalized action |
| `rationale` | Reason for the rule |

Example:

```yaml
- id: cpp20.prefer_span
  when: standard >= 20 and parameter_kind == "contiguous_range"
  should: Prefer std::span over pointer-and-size parameters.
  unless: abi_boundary == true or c_api_boundary == true
  require:
    - Justify if pointer and size are used.
  target: contiguous_range_parameter
  action: prefer
  prefer: std::span
  over:
    - pointer_and_size
```

---

## 16. Rule Strengths

### 16.1 HARD

Use `HARD` for mandatory constraints.

Examples:

```yaml
rules:
  hard:
    - id: cpp.safety.no_ub
      must: Avoid undefined behavior.
      target: undefined_behavior
      action: require
```

```yaml
rules:
  hard:
    - id: cpp.api.no_gets
      must_not: Use gets.
      target: api_usage
      action: forbid
      value: gets
```

HARD rules should be enforceable or at least verifiable in review.

### 16.2 SOFT

Use `SOFT` for best practices and recommendations.

Example:

```yaml
rules:
  soft:
    - id: cpp17.prefer_string_view
      should: Prefer std::string_view over const char*.
      target: string_parameter
      action: prefer
```

Most engineering guidelines belong here.

### 16.3 PREFERENCE

Use `PREFERENCE` for ranking valid alternatives.

Example:

```yaml
rules:
  preference:
    - id: cpp.preference.safety_over_performance
      prefer: safety
      over: performance
      target: decision_priority
```

Preferences should not override HARD rules.

---

## 17. Rule Semantics

### 17.1 MUST

`MUST` means the rule is mandatory.

Equivalent Object Form:

```yaml
rules:
  hard:
    - must: ...
```

### 17.2 MUST NOT

`MUST NOT` means the behavior is forbidden.

Equivalent Object Form:

```yaml
rules:
  hard:
    - must_not: ...
```

### 17.3 SHOULD

`SHOULD` means the behavior is recommended but may be violated with justification.

Equivalent Object Form:

```yaml
rules:
  soft:
    - should: ...
```

### 17.4 SHOULD NOT

`SHOULD NOT` means the behavior is discouraged but may be used with justification.

Equivalent Object Form:

```yaml
rules:
  soft:
    - should_not: ...
```

### 17.5 ALLOW

`ALLOW` means a behavior is permitted under a condition or exception.

Equivalent Object Form:

```yaml
exceptions:
  - allow:
      - ...
```

### 17.6 PREFER

`PREFER` means one option should be selected over another when both are valid.

Equivalent Object Form:

```yaml
rules:
  preference:
    - prefer: A
      over: B
```

### 17.7 REQUIRE

`REQUIRE` attaches an additional obligation to a rule or exception.

Equivalent Object Form:

```yaml
require:
  - ...
```

---

## 18. Condition Expression Syntax

Conditions are used in `when` and `unless`.

### 18.1 Supported Operators

| Operator | Meaning |
|---|---|
| `==` | equality |
| `!=` | inequality |
| `>` | greater than |
| `>=` | greater than or equal |
| `<` | less than |
| `<=` | less than or equal |
| `and` | conjunction |
| `or` | disjunction |
| `not` | negation |
| `in` | membership |

### 18.2 Examples

```text
language == "cpp"
standard >= 20
hot_path == true
parameter_kind in ["read_only_string", "contiguous_range"]
abi_boundary == true or c_api_boundary == true
```

### 18.3 Structured Map Form

For simple activation conditions, Object Form may use map syntax:

```yaml
activation:
  when:
    language: cpp
    standard: ">=20"
```

This is equivalent to:

```text
language == "cpp" and standard >= 20
```

### 18.4 Expression Form

For rule-level conditions, expression syntax is recommended:

```yaml
when: >
  language == "cpp"
  and standard >= 20
  and parameter_kind == "contiguous_range"
```

---

## 19. Priority and Conflict Policy

Rules may conflict. The runtime must not leave conflicts for the agent to guess.

### 19.1 Priority Sources

Priority is derived from:

1. Skill level.
2. Skill priority.
3. Rule strength.
4. Rule priority, if present.
5. Condition specificity.

### 19.2 Default Ordering

```text
platform > domain > project > task
HARD > SOFT > PREFERENCE
higher priority > lower priority
specific condition > broad condition
```

### 19.3 Conflict Types

| Conflict Type | Example | Result |
|---|---|---|
| HARD vs HARD | `MUST A` and `MUST NOT A` | Error |
| HARD vs SOFT | `MUST NOT A` and `SHOULD A` | HARD wins |
| SOFT vs SOFT | `SHOULD A` and `SHOULD B` | Priority or condition resolves |
| Preference cycle | `A > B`, `B > A` | Resolve by priority or report |

---

## 20. Exceptions

Exceptions must be explicit.

Example:

```yaml
exceptions:
  - id: cpp.exception.c_api_boundary
    when: c_api_boundary == true
    allow:
      - const_char_pointer
      - raw_pointer
      - pointer_and_size
    require:
      - Keep C-compatible types at the boundary.
      - Convert to modern C++ types internally when practical.
```

Rule-level exceptions may use `unless`:

```yaml
unless: abi_boundary == true or c_api_boundary == true
```

Exception rules should include requirements whenever they permit a lower-level or riskier idiom.

---

## 21. Dependencies and Incompatibilities

Skills can depend on other skills:

```yaml
dependencies:
  - cpp.core.baseline
  - cpp.safety.lifetime
```

Skills can declare incompatibilities:

```yaml
incompatibilities:
  - cpp.legacy.cpp98_only
```

Dependencies must be resolved before activation. Incompatibilities must be checked before rule extraction.

---

## 22. Verification Mapping

Rules may map to verification tools.

Example:

```yaml
verification:
  static_checks:
    - id: cpp.check.unavailable_facility
      description: Detect use of unavailable C++ standard-library facilities.
      applies_to:
        - standard_availability
      tool: compiler_configuration
      severity: error

  llm_self_check:
    - id: cpp.self_check.version_aware_guidance
      prompt: >
        Check whether the proposed code uses facilities available in the selected C++ standard.
```

Verification mappings do not define rules. They define how rules can be checked.

---

## 23. Normalized Rule IR

Rule IR is a normalized object.

Example:

```json
{
  "rule_id": "cpp20.prefer_span",
  "strength": "SOFT",
  "target": "contiguous_range_parameter",
  "action": "PREFER",
  "value": "std::span",
  "over": ["pointer_and_size"],
  "condition": {
    "language": "cpp",
    "standard": {">=": 20},
    "parameter_kind": "contiguous_range",
    "ownership_required": false
  },
  "exception_condition": {
    "or": [
      {"abi_boundary": true},
      {"c_api_boundary": true}
    ]
  },
  "requirements": [
    "Justify if pointer and size are used."
  ],
  "source_skill": "cpp.standard.cpp20.best_practices"
}
```

The runtime should compare and resolve rules using Rule IR, not raw YAML text.

---

## 24. Effective Rule Set

Effective Rules are task-specific.

Example:

```yaml
effective_rules:
  hard:
    - Avoid undefined behavior.

  soft:
    - Prefer std::string_view over const char* for read-only string parameters.
    - Prefer std::span over pointer-and-size parameters for contiguous ranges.

  preference:
    - Prefer explicit interface intent over implicit convention.

  exceptions:
    - At ABI or C API boundaries, legacy parameter types are allowed with justification.
```

Effective Rules should be concise. The agent should not receive the full skill library.

---

## 25. Skill Composition

Skills are composed through:

- Activation
- Dependencies
- Packs
- Priority
- Conflict resolution
- Rule reduction

The runtime should not concatenate all skill files into a prompt.

Correct flow:

```text
All Skills
    ↓
Candidate Skills
    ↓
Active Skills
    ↓
Rule IR
    ↓
Conflict Resolution
    ↓
Reduction
    ↓
Effective Rules
```

---

## 26. Skill Packs

A Skill Pack is a reusable grouping of skills.

Example:

```yaml
pack:
  id: cpp.safe_generation
  name: C++ Safe Code Generation
  includes:
    - cpp.core.baseline
    - cpp.safety.ownership
    - cpp.safety.lifetime
    - cpp.standard.cpp17.best_practices
```

C++20 pack:

```yaml
pack:
  id: cpp20.safe_generation
  extends:
    - cpp.safe_generation
  includes:
    - cpp.standard.cpp20.best_practices
```

Packs should not replace individual skills. They should define common activation bundles.

---

## 27. Domain Skill Library Design

A domain should not be represented by one large skill. It should be a library of small skills.

Example:

```text
skills/
└── domain/
    └── cpp/
        ├── core/
        ├── safety/
        ├── standard/
        │   ├── cpp17_best_practices.skill.yaml
        │   ├── cpp20_best_practices.skill.yaml
        │   └── cpp23_best_practices.skill.yaml
        ├── concurrency/
        ├── performance/
        ├── api_design/
        └── build_system/
```

The runtime should activate only the relevant subset.

---

## 28. C++ Standard-Aware Skill Example

### 28.1 C++17 Rule

Clause Form:

```text
WHEN language == "cpp" AND standard >= 17 AND parameter_kind == "read_only_string"
SHOULD prefer std::string_view over const char*
UNLESS abi_boundary == true OR c_api_boundary == true OR null_terminated_required == true
REQUIRE justification if const char* is used
```

Object Form:

```yaml
rules:
  soft:
    - id: cpp17.prefer_string_view_for_read_only_string_parameters
      when: >
        language == "cpp"
        and standard >= 17
        and parameter_kind == "read_only_string"
        and ownership_required == false
      should: >
        Prefer std::string_view over const char* for read-only string parameters.
      unless: >
        abi_boundary == true
        or c_api_boundary == true
        or null_terminated_required == true
      require:
        - If const char* is used, justify whether null-termination or C API compatibility is required.
      target: string_parameter
      action: prefer
      prefer: std::string_view
      over:
        - const char*
```

### 28.2 C++20 Rule

Clause Form:

```text
WHEN language == "cpp" AND standard >= 20 AND parameter_kind == "contiguous_range"
SHOULD prefer std::span<T> over pointer-and-size parameters
UNLESS abi_boundary == true OR c_api_boundary == true
REQUIRE justification if pointer and size are used
```

Object Form:

```yaml
rules:
  soft:
    - id: cpp20.prefer_span_for_contiguous_ranges
      when: >
        language == "cpp"
        and standard >= 20
        and parameter_kind == "contiguous_range"
        and ownership_required == false
      should: >
        Prefer std::span<T> over raw pointer and size pairs.
      unless: >
        abi_boundary == true
        or c_api_boundary == true
      require:
        - If pointer and size are used, justify ABI, C API, or performance constraints.
      target: contiguous_range_parameter
      action: prefer
      prefer: std::span
      over:
        - pointer_and_size
```

### 28.3 Effective Rules for C++17

Task context:

```json
{
  "language": "cpp",
  "standard": 17,
  "parameter_kind": "read_only_string"
}
```

Effective Rules:

```yaml
effective_rules:
  soft:
    - Prefer std::string_view over const char* for read-only string parameters.
  exceptions:
    - const char* is allowed at ABI or C API boundaries with justification.
```

### 28.4 Effective Rules for C++20

Task context:

```json
{
  "language": "cpp",
  "standard": 20,
  "parameter_kind": "contiguous_range"
}
```

Effective Rules:

```yaml
effective_rules:
  soft:
    - Prefer std::span over pointer-and-size parameters for non-owning contiguous ranges.
  exceptions:
    - pointer and size are allowed at ABI or C API boundaries with justification.
```

---

## 29. Parsing and Compilation Pipeline

The recommended pipeline is:

```text
Skill file loading
    ↓
Schema validation
    ↓
Object Form parsing
    ↓
Condition parsing
    ↓
Rule IR normalization
    ↓
Activation filtering
    ↓
Dependency and incompatibility checks
    ↓
Conflict resolution
    ↓
Rule reduction
    ↓
Effective Rule rendering
    ↓
Agent injection
```

If Clause Form is supported by tooling, an additional front-end step is used:

```text
Clause Form
    ↓
Clause parser
    ↓
Object Form or Rule IR
```

Production systems should not rely on free-form Clause Form as the only persisted representation.

---

## 30. Validation and Diagnostics

The DSL should support strong diagnostics.

### 30.1 Required Checks

- Missing skill id.
- Missing activation.
- Missing rule id.
- Missing target.
- Missing action or rule keyword.
- Invalid condition expression.
- Invalid strength/action combination.
- Unknown dependency.
- Incompatible skills activated together.
- HARD/HARD conflict.
- Preference cycle.
- Rule references unknown exception id.
- C++ standard rule recommends unavailable facility.

### 30.2 Example Diagnostic

```text
error[DSL001]: rule cpp20.prefer_span has activation standard >= 20,
but appears in a skill activated for standard >= 17.
```

```text
error[DSL002]: HARD conflict on target api_usage:
- MUST NOT use raw_pointer
- MUST use raw_pointer
```

```text
warning[DSL101]: rule cpp17.prefer_string_view has no target field.
Runtime inference may be unstable.
```

---

## 31. Integration with Policy Runtime

The Policy Runtime uses the DSL as input.

Runtime flow:

```text
User Task
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
Agent Context Injection
    ↓
Verification
    ↓
Repair Loop
```

The runtime should not give all skills to the agent. It should give only the task-specific Effective Rules.

---

## 32. Practical Implementation Notes

### 32.1 Recommended Storage

Use Object Form in YAML files:

```text
skills/domain/cpp/standard/cpp17_best_practices.skill.yaml
skills/domain/cpp/standard/cpp20_best_practices.skill.yaml
```

### 32.2 Recommended Documentation Style

Use Clause Form in documentation to show the rule meaning, followed by Object Form to show the implementation.

### 32.3 Recommended Agent Injection

Render Effective Rules into one of:

- Structured JSON context.
- Markdown policy block.
- `AGENTS.md` generated block.
- `CLAUDE.md` generated block.
- Agent wrapper prompt.

### 32.4 Recommended Verification

Map HARD rules to tools whenever possible:

- compiler checks
- clang-tidy
- custom AST checks
- tests
- sanitizer
- LLM self-check for non-decidable rules

---

## 33. Limitations

The DSL cannot guarantee:

- Full semantic correctness.
- Complete compliance without verification.
- Elimination of all ambiguity.
- Correct task analysis in all cases.
- Proper use of rules by agents that ignore context.
- Complete formal decidability for all engineering recommendations.

The DSL manages uncertainty. It does not eliminate it.

---

## 34. Conclusion

The Skill DSL is a structured policy language for AI systems.

Its key design principle is separation of layers:

```text
Clause Form      Human-readable expression
Object Form      Canonical skill file format
Rule IR          Runtime execution model
Effective Rules  Agent-facing task policy
```

The most important clarification is that `WHEN`, `MUST`, `SHOULD`, `ALLOW`, `PREFER`, `UNLESS`, and `REQUIRE` are not merely documentation words. They define the semantics of the DSL.

However, real `.skill.yaml` files should normally use Object Form because it is more stable, parseable, and suitable for validation. Clause Form remains valuable for documentation and rule discussion.

A production Policy Runtime should compile Object Form into Rule IR, resolve conflicts, reduce rules, and inject only Effective Rules into the AI agent.

The final result is a system where skills are not static prompts but structured policy modules that can be automatically activated, composed, reduced, and verified.
