"use strict";

const fs = require("fs");
const path = require("path");

const EXTENSION_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(EXTENSION_ROOT, "..");

const DIRECTORIES = [
  "ai_policy_runtime",
  "bin",
  "docs/reference",
  "hooks",
  "packs",
  "schemas",
  "skills",
  "tools",
  ".claude-plugin",
  ".codex-plugin",
];

const FILES = [
  "MANIFEST.in",
  "pyproject.toml",
  "requirements.txt",
];

const REQUIRED_PATHS = [
  "bin/ai-policy-hook.js",
  "bin/ai-policy.js",
  "hooks/hooks.json",
  "hooks/codex-hooks.json",
  "hooks/user_prompt_submit.py",
  "hooks/stop_refinement.py",
  ".claude-plugin/plugin.json",
  ".claude-plugin/marketplace.json",
  ".codex-plugin/plugin.json",
  "ai_policy_runtime/__init__.py",
  "packs/cpp_safe_generation.pack.yaml",
  "skills/domain/git/workflow/commit_hygiene.skill.yaml",
  "schemas/effective-rules.schema.json",
  "pyproject.toml",
];

function copyDirectory(relativePath) {
  const source = path.join(REPO_ROOT, relativePath);
  const target = path.join(EXTENSION_ROOT, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.rmSync(target, { recursive: true, force: true });
  fs.cpSync(source, target, { recursive: true });
}

function copyFile(relativePath) {
  const target = path.join(EXTENSION_ROOT, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(path.join(REPO_ROOT, relativePath), target);
}

for (const directory of DIRECTORIES) {
  copyDirectory(directory);
}

for (const file of FILES) {
  copyFile(file);
}

const missing = REQUIRED_PATHS.filter((relativePath) => {
  return !fs.existsSync(path.join(EXTENSION_ROOT, relativePath));
});
if (missing.length > 0) {
  throw new Error(`Missing packaged runtime files:\n${missing.map((item) => `- ${item}`).join("\n")}`);
}

console.log("Prepared AI Policy Runtime assets for VS Code extension packaging.");
