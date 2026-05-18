# Git Best Practices Skill Pack

`git.best_practices` gives agents task-aware guidance for common Git work:
commits, staging, branches, synchronization, conflict resolution, pull request
readiness, and history rewrite safety.

## Covered Workflows

- Working tree safety: inspect status before state-changing commands, preserve
  unrelated local work, stage only intended paths or hunks, and keep secrets,
  credentials, private keys, and local machine paths out of history.
- Commit hygiene: keep commits focused, review the staged diff, and write
  accurate imperative commit messages. Conventional Commit style is used when
  the project or user asks for it.
- Branching and synchronization: use focused topic branches, fetch before
  integration, use fast-forward-only pulls for shared mainline updates when
  appropriate, and choose merge or rebase intentionally.
- Stash and clean safety: stash unfinished temporary work instead of creating
  arbitrary work-in-progress commits, and dry-run clean operations before
  deleting untracked or ignored files.
- History rewrite safety: avoid rewriting shared history without explicit
  consent, prefer revert for published changes, and use force-with-lease when a
  rewritten branch must be pushed.
- Conflict and review workflow: resolve conflicts by preserving both sides'
  intent, avoid blind ours/theirs resolutions, remove all conflict markers, and
  prepare focused reviewable diffs.
- Pull request and release readiness: keep PRs reviewable, include validation
  context, match title style, and keep release branches limited to release work
  or narrowly approved fixes.

## Sources

The pack is synthesized from:

- Pro Git, especially branching, merging, rewriting history, reset semantics,
  and contributing workflows: https://git-scm.com/book/en/v2
- Git best-practice notes by Aditi: https://gist.github.com/Aditi3/a7a1ddd1ecef73dab548f7955210cfff
- Git workflow and commit-message notes by Luis MTS: https://gist.github.com/luismts/495d982e8c5b1a0ced4a57cf3d93cf60
