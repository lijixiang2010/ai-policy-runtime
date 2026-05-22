# Changelog

Maintained by Miles Li.

## 0.1.3

- Improve multilingual semantic task detection while keeping Skills DSL authoring English-only.
- Use Git working-tree context to recognize short commit requests when there are repository changes.
- Clarify local embedding model setup and VS Code extension development install docs.

## 0.1.2

- Preserve non-ASCII prompt text in post-task refinement on Windows by emitting ASCII-safe hook JSON.

## 0.1.1

- Improve Marketplace description and README for product clarity.
- Preserve configured local model paths when switching embedding providers.
- Make local embedding configuration take precedence over stale remote model environment values.
- Align direct CLI commands with project embedding and policy-root configuration.

## 0.1.0

- Add workspace enable/disable commands for AI Policy Runtime.
- Add pack selection for Codex prompts.
- Write project-local `.policy/config.json` for the Codex hook.
- Add status and Effective Rules viewing commands.
- Bundle the AI Policy Runtime assets inside the VS Code extension.
- Auto-generate Codex project hook files for each workspace.
- Add runtime validation details and latest hook-state reporting.
