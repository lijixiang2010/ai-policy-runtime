# AI Policy Runtime for VS Code

By Miles Li.

Configure AI Policy Runtime for Codex without editing environment variables by
hand. The extension writes workspace settings to `.policy/config.json`; the
Codex plugin hook reads that file before resolving Effective Rules for each
prompt.

## Requirements

Install and enable the AI Policy Runtime Codex plugin first. This VS Code
extension is the configuration surface for that plugin; it does not replace the
Codex hook.

## Quick Start

1. Open a workspace in VS Code.
2. Run `AI Policy: Enable`.
3. Run `AI Policy: Configure Packs`.
4. Use Codex normally.

## Commands

- `AI Policy: Enable`
- `AI Policy: Disable`
- `AI Policy: Configure Packs`
- `AI Policy: Show Status`
- `AI Policy: Show Effective Rules`
- `AI Policy: Validate Runtime`

## Settings

- `aiPolicy.enabled`: enable or disable the Codex hook for this workspace.
- `aiPolicy.packs`: policy packs to activate.
- `aiPolicy.policyRoot`: optional policy asset root.
- `aiPolicy.autoInstall`: allow the hook to install missing Python dependencies.
- `aiPolicy.embeddingProvider`: semantic matching provider.

Environment variables such as `AI_POLICY_PACKS` still override project settings
when both are set.
