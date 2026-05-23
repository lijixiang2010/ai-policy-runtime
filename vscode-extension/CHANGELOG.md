# Changelog

Maintained by Miles Li.

## 0.1.5

- Run Codex hooks directly through Python to avoid Node child-process Python launch failures in restricted environments.
- Report the direct Codex hook Python command in status/validation output before hooks fail silently.
- Add an embedding provider test command and VS Code configuration action.
- Add a VS Code command and configuration action to install the default local embedding model on demand.
- Add explicit workspace cleanup commands for CLI, npm, and VS Code extension users.
- Use the VS Code extension host Node runtime for bundled CLI actions when `AI_POLICY_NODE` is not set.
- Leave policy packs unselected by default for new workspaces.

## 0.1.4

- Refresh workspace agent hooks to the current VS Code extension runtime after upgrades.
- Show stale Codex and Claude runtime paths in validation output and report automatic repairs.
- Update CLI configuration to replace stale policy roots when reconfiguring upgraded npm installs.

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
