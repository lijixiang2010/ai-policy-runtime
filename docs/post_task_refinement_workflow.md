# Post-Task Refinement Workflow

The post-task refinement workflow automates the extra quality pass that often
follows a working implementation. Its purpose is to keep effective complexity
and remove accidental complexity after the agent has already completed the
requested change.

This workflow belongs in the agent wrapper layer because only the wrapper knows
whether the first agent command ran, whether it succeeded, and whether a dry run
was requested. The core runtime remains focused on deterministic policy
resolution, injection, and verification.

## Goals

- Preserve observable behavior unless the original task explicitly requested a
  behavior change.
- Group scattered state, helper functions, and behavior into coherent
  components when doing so reduces net complexity.
- Extract repeated structure only when it clarifies real variation points.
- Prefer direct language-native syntax over heavier custom machinery when it is
  clearer and equally correct.
- Reduce user-facing steps and API friction.
- Keep ownership, lifetime, bounds, type-safety, and standard-availability
  constraints explicit.
- Run relevant checks when practical and report commands, results, and skipped
  checks.

The workflow is intentionally proportionate. If a larger redesign is required,
the agent should report that need instead of rewriting unrelated code during the
refinement pass.

## Modes

`off` is the default and preserves existing wrapper behavior.

`light` resolves and injects a refinement-focused policy context after a
successful first command, but does not run the agent a second time. This is
useful when another tool or human will perform the review.

`standard` runs a second agent command after a successful first command. The
second task asks for a behavior-preserving production-quality refinement pass and
adds `cpp.production_refinement` to the active packs by default.

`strict` also runs the second agent command. It is intended for release-quality
flows where `--verify-target` is supplied so deterministic verification runs
after the refinement pass.

If the first agent command fails, the refinement pass is skipped and the result
records the skip reason. If `--no-exec` is used, the wrapper can still resolve
and inject refinement context, but it will not execute an agent command.

## CLI Usage

Run the usual policy wrapper without automatic refinement:

```powershell
policy-codex --pack cpp.low_latency "Implement a C++20 matching-engine API."
```

Run a standard post-task refinement pass after the first successful Codex run:

```powershell
policy-codex `
  --pack cpp.low_latency `
  --post-refine `
  "Implement a C++20 matching-engine API."
```

Use an explicit mode:

```powershell
policy-codex `
  --pack cpp.low_latency `
  --post-refine-mode strict `
  --verify-target src `
  "Implement a C++20 matching-engine API."
```

Use a custom refinement pack set:

```powershell
policy-codex `
  --pack cpp.low_latency `
  --post-refine-mode standard `
  --post-refine-pack cpp.production_refinement `
  "Implement a C++20 matching-engine API."
```

Claude Code uses the same shared flags:

```powershell
policy-claude `
  --pack cpp.low_latency `
  --post-refine `
  "Implement a C++20 matching-engine API."
```

## Execution Order

The wrapper performs:

```text
resolve original task
inject original Effective Rules
run first agent command when execution is enabled
skip refinement if the first command fails
resolve refinement task with original packs plus refinement packs
inject refinement Effective Rules
run second agent command for standard and strict modes when execution is enabled
run verification when --verify-target is configured
return a JSON result that includes the refinement stage
```

Verification runs after the final agent stage so that checks evaluate the code
as it will be left for the user. The default `strict` expectation is therefore:

```text
first implementation pass -> refinement pass -> deterministic verification
```

## Result Shape

Wrapper JSON output keeps the original result fields and adds `refinement` when
a refinement mode is active:

```json
{
  "executed": true,
  "exit_code": 0,
  "verified": true,
  "violations": [],
  "refinement": {
    "mode": "strict",
    "pack_ids": ["cpp.low_latency", "cpp.production_refinement"],
    "executed": true,
    "exit_code": 0
  }
}
```

When refinement is skipped, the same field records the reason:

```json
{
  "refinement": {
    "mode": "standard",
    "executed": false,
    "skipped_reason": "initial agent command failed"
  }
}
```

## Quality Boundary

The refinement task text is deliberately narrow. It asks the agent to improve
structure, abstraction level, API ergonomics, and verification discipline while
preserving behavior and avoiding broad rewrites. This keeps the workflow aligned
with the Skills principle of retaining effective complexity and removing
accidental complexity.
