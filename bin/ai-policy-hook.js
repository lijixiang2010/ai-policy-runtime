#!/usr/bin/env node
"use strict";

const path = require("path");
const { spawnSync } = require("child_process");

const PACKAGE_ROOT = path.resolve(__dirname, "..");
const CLI = path.join(PACKAGE_ROOT, "bin", "ai-policy.js");

const HOOKS = {
  "codex-user-prompt-submit": path.join(PACKAGE_ROOT, "hooks", "user_prompt_submit.py"),
  "codex-stop-refinement": path.join(PACKAGE_ROOT, "hooks", "stop_refinement.py"),
  "claude-user-prompt-submit": path.join(PACKAGE_ROOT, "hooks", "claude_user_prompt_submit.py"),
  "claude-stop-refinement": path.join(PACKAGE_ROOT, "hooks", "claude_stop_refinement.py"),
};

const hook = process.argv[2];
const script = HOOKS[hook];
if (!script) {
  console.error(
    "ai-policy-hook: expected codex-user-prompt-submit, codex-stop-refinement, " +
      "claude-user-prompt-submit, or claude-stop-refinement"
  );
  process.exit(1);
}

const result = spawnSync(process.execPath, [CLI, "runtime-python", script], {
  stdio: "inherit",
  env: {
    ...process.env,
    AI_POLICY_HOOK_SCRIPT: script,
  },
});

if (result.error) {
  console.error(`ai-policy-hook: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status === null ? 1 : result.status);
