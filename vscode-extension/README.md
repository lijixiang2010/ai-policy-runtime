# AI Policy Runtime for VS Code

By Miles Li.

Configure AI Policy Runtime for AI coding agents without editing environment
variables by hand. The extension writes workspace settings to
`.policy/config.json`; supported agent hooks and wrappers read that file before
resolving Effective Rules for each prompt.

## Requirements

Install and enable the relevant AI Policy Runtime agent integration first. This
VS Code extension is the configuration surface for those integrations; it does
not replace agent hooks or wrappers.

## Quick Start

1. Open a workspace in VS Code.
2. Run `AI Policy: Enable`.
3. Run `AI Policy: Enable Post-Task Refinement` when a supported agent should
   continue once before ending a turn for production refinement.
4. Run `AI Policy: Configure Packs`.
5. Select Codex, Claude Code, or both in the side-bar configuration view.
6. Use your agent normally.

## Local VSIX Install

Build and install the extension from this repository:

```powershell
cd D:\MilesLi\ai-policy-runtime\vscode-extension
npm ci
npm run package
& "$env:LOCALAPPDATA\Programs\Microsoft VS Code\bin\code.cmd" --install-extension ".\ai-policy-runtime-0.1.0.vsix" --force
```

Reload VS Code after installing or replacing icon assets:

```text
Developer: Reload Window
```

## Commands

- `AI Policy: Enable`
- `AI Policy: Disable`
- `AI Policy: Enable Post-Task Refinement`
- `AI Policy: Configure Packs`
- `AI Policy: Show Status`
- `AI Policy: Show Effective Rules`
- `AI Policy: Validate Runtime`

## Settings

- `aiPolicy.enabled`: enable or disable AI Policy Runtime for this workspace.
- `aiPolicy.agents`: agent integrations that should use this workspace policy.
- `aiPolicy.packs`: policy packs to activate.
- `aiPolicy.policyRoot`: optional policy asset root.
- `aiPolicy.autoInstall`: allow agent hooks to install missing Python dependencies.
- `aiPolicy.embeddingProvider`: optional semantic embedding provider.
- `aiPolicy.embeddingBaseUrl`: optional OpenAI-compatible embeddings base URL.
- `aiPolicy.embeddingApiKey`: optional API key for the embeddings endpoint.
- `aiPolicy.embeddingModel`: optional embedding model.
- `aiPolicy.embeddingTimeout`: optional embedding request timeout in seconds.
- `aiPolicy.postRefine`: agent Stop-hook post-task refinement mode.
- `aiPolicy.postRefinePacks`: packs added for the refinement continuation.
- `aiPolicy.verifyTarget`: optional target agents should verify during strict
  refinement.

Environment variables such as `AI_POLICY_PACKS` still override project settings
when both are set.
