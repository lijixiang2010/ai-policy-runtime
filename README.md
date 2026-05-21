![AI Policy Runtime banner](docs/assets/banner.png)

# AI Policy Runtime

Task-aware coding guidance for AI agents.

AI Policy Runtime helps Codex, Claude Code, and other AI coding workflows use
the right engineering rules for the task in front of them. Instead of sending
one large generic prompt every time, it detects the work type and supplies a
focused policy: safe implementation, review, refactoring, API design,
performance-sensitive code, Git workflow, CMake, Python, or post-task
refinement.

The result is calmer, more consistent agent behavior across a workspace.

## What You Get

- Task-specific rules for coding, review, refactoring, and design work.
- Workspace-level configuration shared by supported agents.
- Optional semantic task matching with OpenAI-compatible or local embeddings.
- Optional post-task refinement before an agent finishes.
- Inspectable Effective Rules so you can see what guidance was applied.

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

AI Policy Runtime can classify tasks with embeddings. You choose the provider:

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

AI Policy Runtime stores project configuration in normal workspace files:

- `.policy/config.json`
- `.policy/current/effective-prompt.md`
- `.policy/current/agent-hook-state.json`
- `.codex/hooks.json` and `.codex/config.toml` when Codex is enabled
- `.claude/settings.local.json` when Claude Code is enabled

These files make the active policy visible and reproducible.

## Notes

- AI Policy Runtime is not an LLM. It prepares task-aware policy context for AI
  coding agents.
- Local models are optional and user-configured.
- Remote embedding requests are only used when you configure a remote provider
  or credentials.
- See [docs/usage.md](docs/usage.md) for advanced CLI, hook, and runtime
  details.
