![AI Policy Runtime banner](docs/assets/banner.png)

# AI Policy Runtime

Generate better AI code with task-aware policies for Codex and Claude Code.

AI Policy Runtime gives your AI coding agent focused engineering rules for the
task at hand. It can guide implementation, review, refactoring, API design,
performance-sensitive work, Git workflows, CMake, Python, and post-task
refinement without making you rewrite prompts for every request.

The result is more consistent agent behavior across a workspace.

## What It Does

- Detects the task type and applies focused coding rules.
- Shares one workspace configuration across Codex and Claude Code.
- Uses embeddings for stronger multilingual task matching.
- Can run a post-task refinement pass before the agent finishes.
- Shows the exact Effective Rules used for the latest prompt.

C++ currently has the deepest coverage, including ownership, lifetime, bounds
safety, API design, modern C++, and low-latency work. Python, CMake, Git, and
general refinement packs are also included.

## Install

### VS Code

Install the **AI Policy Runtime** extension, then open its side bar in your
workspace.

Use it with the Codex or Claude Code extension you already use. Enable the
runtime, select the agent, choose policy packs, and configure embeddings if you
want semantic task matching.

For Codex, trust the generated workspace hooks when Codex asks. Until the hooks
are trusted, Codex will not run them, so AI Policy Runtime will appear enabled
but no rules will be injected.

### Command Line

```powershell
npm install -g ai-policy-runtime
ai-policy doctor
```

Configure a project for Codex:

```powershell
ai-policy configure codex --root D:\work\project
```

Configure a project for Claude Code:

```powershell
ai-policy configure claude --root D:\work\project
```

## Embeddings

AI Policy Runtime uses embeddings for product-quality multilingual task
matching. You choose the provider:

- **Auto**: use a configured OpenAI-compatible endpoint, otherwise use a
  configured local model when available.
- **OpenAI-compatible**: use an endpoint such as OpenAI, OpenRouter, or another
  `/v1/embeddings` service.
- **Local**: use a sentence-transformers model path that you provide.

The package does not include or download a local model by default.

Configure a local model from the CLI:

```powershell
ai-policy embedding configure --root D:\work\project --provider local --model D:\models\paraphrase-multilingual-MiniLM-L12-v2
```

Or download the recommended default model:

```powershell
ai-policy embedding configure --root D:\work\project --provider local --install
```

Check the current embedding setup:

```powershell
ai-policy embedding status --root D:\work\project
```

## Common Commands

```powershell
ai-policy status --root D:\work\project
ai-policy resolve --pack cpp.safe_generation "Implement this C++ API"
ai-policy explain "Review this change for ownership and lifetime risks"
ai-policy validate
```

## Policy Packs

Included packs:

- `cpp.safe_generation`
- `cpp.low_latency`
- `cpp.code_review`
- `cpp.library_api_design`
- `cpp.modernization`
- `cpp.production_refinement`
- `python.best_practices`
- `python.production_refinement`
- `cmake.best_practices`
- `cmake.production_refinement`
- `git.best_practices`
- `generic.production_refinement`

## Workspace Files

AI Policy Runtime stores transparent project state in workspace files:

- `.policy/config.json`
- `.policy/current/effective-prompt.md`
- `.policy/current/agent-hook-state.json`
- `.codex/hooks.json` and `.codex/config.toml` when Codex is enabled
- `.claude/settings.local.json` when Claude Code is enabled

These files make the active policy visible and reproducible. Review them before
committing workspace-specific settings.

## Notes

- AI Policy Runtime is not an LLM. It prepares task-aware policy context for AI
  coding agents.
- Local models are optional and user-configured.
- Remote embedding requests are only used when you configure a remote provider
  or credentials.
- See [docs/usage.md](docs/usage.md) for CLI and advanced setup details.
