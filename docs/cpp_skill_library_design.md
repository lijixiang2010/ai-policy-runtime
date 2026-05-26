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
- verification tooling

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
- C++23: standard library modules, `std::print`/`std::println`, C++23 range
  views, `std::bind_back`, `std::unreachable`, and expanded constexpr use.
- Standard availability: hard guardrails prevent recommending or using
  unavailable facilities for the selected standard.

Important semantic distinction: `std::string_view` is for non-owning
string-like input; `std::span` is for non-owning contiguous ranges. `std::span`
is not the general replacement for `const char*` string parameters.

C++23 guidance remains limited to version-specific facilities. General lessons
from C++23-era practice, such as stronger API types, RAII, bounds safety,
allocation control, and template constraints, belong in their execution-semantic
skills rather than in the C++23 standard-version skill.

Verification tooling is split into two cross-cutting skills:

- `cpp.verification.tooling` owns the verification capability inventory: tests,
  compiler warnings, static analysis, sanitizers, fuzzing, CI matrices, multiple
  compilers, and build/package tooling.
- `cpp.verification.execution` owns agent execution behavior: discovering
  project verification entrypoints, running proportionate local checks after
  code changes, reporting commands and results, and explaining checks that were
  not run.

Semantic skills may still name specific verification hooks, but they do not own
the overall verification strategy or the agent's verification execution workflow.

## Concurrency Skill Shape

Concurrency guidance is grouped by decision level rather than copied from book
or guideline chapter order. The goal is an expert-shaped hierarchy: core safety
rules appear early; specialized mechanisms stay dormant until the task clearly
needs them.

Tier 1, core invariants:

- `data_race_safety` owns shared mutable state, the hard no-data-race rule, and
  the default preference for isolated state or message passing.
- `thread_lifetime` owns `std::thread`, `std::jthread`, join, detach, shutdown,
  and cancellation ownership.

Tier 2, normal synchronization mechanisms:

- `synchronization_and_locks` owns mutex discipline, RAII locks, critical-section
  size, multi-mutex locking, and deadlock-prone calls while locked.
- `condition_variables` owns predicated waits, guarded predicate state,
  notification ordering, and one-shot notification alternatives.
- `tasks_and_futures` owns task-based result delivery, `std::async`, futures,
  promises, launch semantics, result consumption, and standalone async task
  creation. Executor queue capacity belongs to `thread_pools_executors`.
- `thread_pools_executors` owns production executor boundaries: bounded
  submission, backpressure, shutdown, task outcome channels, cancellation,
  worker liveness, and capacity sizing. It does not own generic future result
  semantics or concurrent container interface design.

Tier 3, specialized design surfaces:

- `concurrent_data_structures` owns thread-safe container interface shape,
  invariant preservation, exposed internals, lock granularity, and library reuse.
- `atomics_memory_model` owns `std::atomic`, memory-order justification,
  volatile misuse, mixed atomic/non-atomic access, and custom lock-free risk.
- `lock_free_expert` owns post-core custom lock-free algorithms, including
  reclamation, ABA, progress guarantees, memory-order protocols, and expert
  verification. It should stay dormant unless those terms are explicit.

Tier 4, post-core advanced execution:

- `coroutines_and_execution` owns C++20 coroutine frame lifetime, await/resume
  behavior, cancellation, custom awaiter/promise risk, and parallel algorithm
  callback safety. It should activate only when coroutine or parallel execution
  semantics are explicit.

The common policy direction is: minimize shared mutable data, prefer immutable
or local state when practical, use task/message abstractions before raw shared
state, make ownership and shutdown explicit, keep synchronization reviewable,
and reserve custom atomics or lock-free algorithms for measured, justified
cases.

Use `cpp.concurrency_expert` when the task is primarily concurrency design,
implementation, or review. It extends the safe-generation baseline and includes
the full concurrency hierarchy, while target-specific triggers keep coroutine,
lock-free, executor, and condition-variable details from appearing unless the
task asks for them.

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
