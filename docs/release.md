# Release Guide

This project publishes the end-user command through NPM as `ai-policy-runtime`.
The installed package exposes both `ai-policy` and `ai-policy-runtime`.

## Local Release Check

Run the full release gate before creating a tag or GitHub release:

```powershell
npm run release:check
```

The gate verifies:

- Node CLI syntax
- NPM package contents via `npm pack --dry-run`
- Python unit tests, including tarball install smoke tests

For a publish-shaped local check without uploading:

```powershell
npm run publish:dry-run
```

## Versioning

Keep the NPM and Python package versions aligned:

```text
package.json
pyproject.toml
.claude-plugin/plugin.json
.claude-plugin/marketplace.json
.codex-plugin/plugin.json
```

Use semantic versioning:

- Patch: bug fixes and packaging fixes.
- Minor: new commands, new supported clients, new non-breaking policy packs.
- Major: breaking CLI behavior or incompatible config/schema changes.

## Publish From GitHub

1. Ensure the repository secret `NPM_TOKEN` is configured.
2. Run `npm run release:check` locally.
3. Update versions and release notes.
4. Push the release commit and tag.
5. Create a GitHub release.

The `Publish NPM Package` workflow runs release checks and publishes with NPM
provenance.

For a manual dry run, start the workflow with `dry_run=true`. For an explicit
manual publish, start it with `dry_run=false`.

## Post-Publish Smoke Test

After publishing:

```powershell
npm install -g ai-policy-runtime
ai-policy doctor
ai-policy status --root D:\work\scratch-project
ai-policy configure claude --root D:\work\scratch-project
```

Confirm that:

- `ai-policy doctor` reports `ok: true`.
- `ai-policy status` is read-only before configuration.
- `ai-policy configure claude` writes `.policy/config.json` and
  `.claude/settings.local.json`.
- Claude Desktop sees `ai-policy-runtime@ai-policy-runtime` in the configured
  workspace.
