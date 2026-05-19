# Python Best Practices Skill Pack

`python.best_practices` gives agents task-aware guidance for production Python
work. The pack is intentionally tiered: common Python tasks get compact core
rules, while heavier product-engineering rules appear only when the task names
that concern.

## Structure

### Core

Core rules are low-noise defaults for ordinary Python generation, review, and
refactoring.

- Pythonic baseline: prefer explicit, readable code; inspect project
  conventions before non-trivial edits; keep import-time behavior light; do not
  weaken validation to make changes appear to pass.
- Style and naming: follow project style and PEP 8 where sensible, avoid
  wildcard imports, group imports, document public contracts when useful, and
  use comments for reasons and constraints.
- Data and control flow: use truthiness intentionally, prefer simple
  comprehensions and iteration protocols, choose standard collections by
  semantics, and stream large data where appropriate.
- Resources and errors: use context managers, avoid silent broad exception
  handling, keep cleanup paths visible, and make failure behavior explicit.

### Design

Design rules are secondary. They activate when the task mentions API design,
typing, tests, functions, classes, protocols, or related concepts.

- Function contracts: avoid mutable defaults, keep functions coherent, use
  keyword-only options for ambiguous values, and preserve decorator metadata.
- Classes and protocols: prefer functions for simple interfaces, dataclasses for
  compact data schemas, composition over inheritance, and protocols for
  structural behavior.
- Typing: type public and external boundaries first, contain `Any`, model
  external dictionary data explicitly, and avoid unexplained type ignores.
- Testing: keep tests behavior-focused, isolated, deterministic, and honest
  about unfinished work.

### Professional

Professional rules are deliberately behind precise task context so they do not
crowd ordinary Python prompts.

- Packaging: preserve the existing package manager and build backend, keep
  dependency scopes separate, declare package metadata, and smoke-test builds.
- Security: validate untrusted input, avoid unsafe dynamic execution and
  deserialization, use safe subprocess APIs, prevent path traversal, parameterize
  queries, and redact secrets.
- CLI: use import-safe modules, `parse_args(argv)`, `main(argv)`, explicit exit
  codes, and separate parsing from business logic.
- Concurrency: choose asyncio, threads, processes, subprocesses, or queues by
  workload; bound concurrency; protect shared state; handle cancellation and
  timeouts.
- Performance: measure before optimizing, fix algorithms and I/O before
  micro-optimizing, stream large data, and report before/after evidence when
  available.

## Prompt Budget

Python prompts are compressed separately from other domains:

- HARD rules: at most 6
- SOFT rules: at most 8
- Preferences: at most 3
- Verification requirements: at most 4

Rules that remain useful but are not central to the current task stay in the
structured effective-rules output rather than the agent-facing prompt.

## Deferred Topics

The pack intentionally keeps framework-specific rules out of the core prompt:
Django, FastAPI, Flask, SQLAlchemy, Pydantic, pandas/NumPy, notebooks, plugins,
and cloud runtimes should be added as separate task-specific skills if needed.

## Sources

The pack is synthesized from:

- Steve Sloria, The Best of the Best Practices Guide for Python:
  https://gist.github.com/sloria/7001839
- Rui Maranhão, A Guide of Best Practices for Python:
  https://gist.github.com/ruimaranhao/4e18cbe3dad6f68040c32ed6709090a3
- Brett Slatkin, Effective Python, 3rd Edition
- Luciano Ramalho, Fluent Python, 2nd Edition
- Local `python-skills-professional` operating-procedure documents
