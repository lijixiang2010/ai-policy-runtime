# AI Policy Runtime

Generate better AI code with task-aware policies for Codex and Claude Code.

AI Policy Runtime gives your AI coding agent focused engineering rules for the
current task. It can guide implementation, review, refactoring, API design,
performance-sensitive work, Git, CMake, Python, and post-task refinement.

Instead of relying on one generic instruction set, each workspace gets a clear
policy configuration that your selected agents use automatically.

## Why Install It

- Improve generated code without rewriting prompts by hand.
- Keep Codex and Claude Code behavior consistent in a workspace.
- Choose focused policy packs for the kind of work you do.
- Use OpenAI-compatible or local embeddings for better task matching.
- Inspect the exact Effective Rules generated for the latest prompt.

C++ has the deepest policy coverage today. Python, CMake, Git, and general
refinement packs are also included.

## Quick Start

1. Install Codex or Claude Code for VS Code.
2. Install **AI Policy Runtime**.
3. Open a workspace.
4. Open the AI Policy Runtime side bar.
5. Enable the runtime.
6. Select Codex, Claude Code, or both.
7. Choose policy packs.
8. Run **AI Policy Runtime: Validate Runtime**.

For Codex, approve the generated workspace hooks when Codex asks you to trust
them. Until the hooks are trusted, Codex will not run them, so AI Policy Runtime
can look enabled while no rules are injected.

After updating AI Policy Runtime, reload the VS Code window and run
**AI Policy Runtime: Validate Runtime**. Validation refreshes workspace hook
files if they still point at an older extension runtime.

## Embeddings

Embeddings are recommended for product-quality multilingual task matching.

Choose one provider in the side bar:

- **Auto**: use a configured OpenAI-compatible endpoint, otherwise use a
  configured local model when available.
- **OpenAI-compatible**: use an embeddings endpoint such as OpenAI, OpenRouter,
  or another `/v1/embeddings` service.
- **Local sentence-transformers**: use a local model path that you provide.

The extension does not ship a local model by default. If you choose local
embeddings, set **Local model path** to an existing sentence-transformers model
directory.

## What It Creates

AI Policy Runtime keeps configuration in your workspace:

- `.policy/config.json`
- `.policy/current/effective-prompt.md`
- `.policy/current/agent-hook-state.json`
- `.codex/hooks.json` and `.codex/config.toml` when Codex is enabled
- `.claude/settings.local.json` when Claude Code is enabled

These files are plain text so you can inspect what was configured and what
rules were generated. Review them before committing workspace-specific settings.

## Commands

- **AI Policy Runtime: Enable**
- **AI Policy Runtime: Disable**
- **AI Policy Runtime: Configure Packs**
- **AI Policy Runtime: Enable Post-Task Refinement**
- **AI Policy Runtime: Show Status**
- **AI Policy Runtime: Show Effective Rules**
- **AI Policy Runtime: Validate Runtime**

## Privacy

AI Policy Runtime is not an LLM. It prepares policy context for the AI agent you
already use.

Remote embedding requests are only made when you configure a remote embedding
provider or credentials. Local embeddings use the model path you configure on
your machine.
