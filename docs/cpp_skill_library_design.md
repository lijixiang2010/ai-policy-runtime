# C++ Skill Library Design

This C++ Skill Library is a reconstructed policy library, not a mechanical YAML
copy of the C++ Core Guidelines. The guidelines are treated as source material:
useful for concepts, risks, exceptions, and verification hints, but not as the
runtime structure.

The Policy Runtime consumes `skills/domain/cpp`, packs under `packs/`, and the
generated Effective Rules. It does not send raw source documents or the full
Skill Library to an agent. Skills are activated by task context, packs, and
conditions, then reduced into short task-specific Effective Rules.

## Reconstruction Method

The library was authored by:

1. Extracting useful C++ Core Guidelines ideas.
2. Removing duplicated, broad, obsolete, or low-signal wording.
3. Regrouping by AI execution semantics rather than document order.
4. Grading rules by enforceability and risk.
5. Compressing overlapping guidance into self-owned Skill rules.
6. Preserving source traces only for auditability.
7. Writing Object Form YAML that the runtime can validate and reduce.

## Skill Groups

The reconstructed structure is organized around execution semantics:

- safety
- ownership and lifetime
- resource management
- API design
- bounds safety
- type safety
- undefined behavior
- error handling
- concurrency
- performance
- templates
- standard-version idioms
- source structure

This grouping matches how an AI coding agent needs guidance: what context
activates a skill, what behavior is required or recommended, what exceptions are
valid, and how the output can be reviewed.

## Rule Strengths

`HARD` rules are used for mandatory safety constraints, clear undefined behavior
risks, resource leaks, and standard-availability violations that should block
output or trigger repair.

`SOFT` rules are used for design recommendations, modernization guidance,
idioms with common exceptions, and review-focused improvements.

`PREFERENCE` rules rank valid alternatives, such as safety over performance by
default, or performance over readability only inside hot paths when safety is
preserved.

## Version-Aware Idioms

C++17 and C++20 guidance is separated from hard standard availability:

- C++17: `std::string_view`, `std::optional`, `std::variant`,
  `std::filesystem`, and if/switch initializers.
- C++20: `std::span`, concepts, `std::jthread`, `starts_with`/`ends_with`, and
  constexpr-capable facilities.
- Standard availability: hard guardrails prevent recommending or using
  unavailable facilities for the selected standard.

Important semantic distinction: `std::string_view` is for non-owning
string-like input; `std::span` is for non-owning contiguous ranges. `std::span`
is not the general replacement for `const char*` string parameters.

## Effective Rules

The agent should receive only the reduced Effective Rules for the current task.
For example, a C++17 read-only string API task should receive the string_view
recommendation and the standard-availability guardrail, not the whole standard
skill library. A C++20 low-latency matching engine task should receive safety
rules, hot-path tradeoff rules, allocation guidance, and span guidance only when
the task context supports them.

Task analysis metadata generates context from task text using `when_text_matches`
and `set`. Skill rules consume context through `when` conditions. These are kept
separate so context extraction does not get mixed with rule activation.

## Verification

Verification mappings are intentionally partial. `clang-tidy`, compiler
warnings, and sanitizers can check some risks, while LLM review checks cover
intent, tradeoffs, and exception justifications. The library does not pretend
every rule is tool-checkable.

## Source Traceability

Each skill includes short `sources` identifiers where relevant. These are audit
traces, not copied guideline text. The final rule wording is normalized for this
runtime and should remain concise, enforceable, and task-specific.
