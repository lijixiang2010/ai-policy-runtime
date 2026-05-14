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
- `AI Policy: Configure Packs`
- `AI Policy: Show Status`
- `AI Policy: Show Effective Rules`
- `AI Policy: Validate Runtime`

## Settings

- `aiPolicy.enabled`: enable or disable the Codex hook for this workspace.
- `aiPolicy.packs`: policy packs to activate.
- `aiPolicy.policyRoot`: optional policy asset root.
- `aiPolicy.autoInstall`: allow the hook to install missing Python dependencies.
- `aiPolicy.embeddingProvider`: optional semantic embedding provider.
- `aiPolicy.embeddingBaseUrl`: optional OpenAI-compatible embeddings base URL.
- `aiPolicy.embeddingApiKey`: optional API key for the embeddings endpoint.
- `aiPolicy.embeddingModel`: optional embedding model.
- `aiPolicy.embeddingTimeout`: optional embedding request timeout in seconds.

Environment variables such as `AI_POLICY_PACKS` still override project settings
when both are set.
