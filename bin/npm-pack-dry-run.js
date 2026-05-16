#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const cache = fs.mkdtempSync(path.join(os.tmpdir(), "ai-policy-npm-cache-"));
const npmExecPath = process.env.npm_execpath;
const command = npmExecPath ? process.execPath : npmCommand();
const args = npmExecPath
  ? [npmExecPath, "pack", "--dry-run"]
  : ["pack", "--dry-run"];

const result = spawnSync(command, args, {
  stdio: "inherit",
  env: {
    ...process.env,
    npm_config_cache: cache,
  },
});

if (result.error) {
  console.error(`npm-pack-dry-run: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status === null ? 1 : result.status);

function npmCommand() {
  return process.platform === "win32" ? "npm.cmd" : "npm";
}
