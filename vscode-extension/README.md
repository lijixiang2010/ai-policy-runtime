# AI Policy Runtime

Generate better AI code with task-aware policies.

AI Policy Runtime helps Codex and Claude Code adjust their coding guidance to
the work in front of them. Instead of using one generic instruction set for
every prompt, your agent can apply focused policies for safety, API design,
review, modernization, performance-sensitive code, and post-task refinement.

It is designed for general AI coding workflows. C++ currently has the deepest
policy coverage, including ownership, lifetime, bounds safety, modern C++,
low-latency constraints, and library API design.

## Why Use It

- Improve generated code quality without rewriting prompts by hand.
- Keep agent behavior consistent across a workspace.
- Apply different policy packs for implementation, review, refactoring, and API design.
- Add a focused refinement pass before an agent finishes a task.
- Inspect the active policy when you need to understand what guided a response.

## Requirements

Install the Codex or Claude Code extension you want to use in VS Code. Then
enable AI Policy Runtime for the workspace and select the matching agent.

AI Policy Runtime ships its policy runtime inside the VS Code extension package.
Each workspace only stores its own `.policy` and agent hook configuration; users
do not need to copy the runtime into their projects.

## Quick Start

1. Open a workspace.
2. Open the AI Policy Runtime side bar.
3. Enable the runtime.
4. Select Codex, Claude Code, or both.
5. Choose the policy packs for your project.
6. Run `AI Policy Runtime: Validate Runtime` if you want a readiness report.

Your selected AI coding agents will use the workspace policy automatically.
For Codex, approve the generated project hooks when Codex asks you to trust them.

## What It Creates

AI Policy Runtime automatically creates and maintains workspace-local files:

- `.policy/config.json`
- `.codex/hooks.json`
- `.codex/config.toml`

The latest hook run is reported in `.policy/current/agent-hook-state.json`, and
the rendered rules are written to `.policy/current/effective-prompt.md`.

## Available Commands

- `AI Policy Runtime: Enable`
- `AI Policy Runtime: Disable`
- `AI Policy Runtime: Configure Packs`
- `AI Policy Runtime: Enable Post-Task Refinement`
- `AI Policy Runtime: Show Status`
- `AI Policy Runtime: Show Effective Rules`
- `AI Policy Runtime: Validate Runtime`
