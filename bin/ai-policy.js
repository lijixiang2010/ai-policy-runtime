#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const PACKAGE_ROOT = path.resolve(__dirname, "..");
const PYTHON_MODULE = "ai_policy_runtime.cli";
const CLAUDE_CONFIGURE_SCRIPT = path.join(PACKAGE_ROOT, "tools", "configure_claude_desktop.py");
const CODEX_CONFIGURE_SCRIPT = path.join(PACKAGE_ROOT, "tools", "configure_codex.py");
const MIN_PYTHON = [3, 10];

function main(argv) {
  if (argv.length === 0 || argv[0] === "--help" || argv[0] === "-h") {
    printHelp();
    return 0;
  }

  const [command, ...rest] = argv;
  if (command === "configure") {
    return configure(rest);
  }
  if (command === "status") {
    return status(rest);
  }
  if (command === "enable") {
    return configure(["claude", ...rest]);
  }
  if (command === "disable") {
    return runConfigure(["--disable", ...withDefaultRoot(rest)]);
  }
  if (command === "plugin") {
    return plugin(rest);
  }
  if (command === "post-refine") {
    return postRefine(rest);
  }
  if (command === "runtime") {
    if (rest[0] === "rebuild") {
      return rebuildRuntime();
    }
    return runPython(["-m", PYTHON_MODULE, ...rest]);
  }
  if (command === "runtime-python") {
    if (rest.length === 0) {
      fail("runtime-python requires a Python script path.");
    }
    return runPython(rest);
  }
  if (command === "doctor") {
    return doctor();
  }

  return runPython(["-m", PYTHON_MODULE, command, ...withDefaultPolicyRoot(command, rest)]);
}

function configure(argv) {
  const [target, ...rest] = argv;
  if (!target || target === "claude") {
    return runClaudeConfigure(withDefaultRoot(rest));
  }
  if (target === "desktop" || target === "claude-desktop") {
    return runClaudeConfigure(withDefaultRoot(rest));
  }
  if (target === "codex") {
    return runCodexConfigure(withDefaultRoot(rest));
  }
  fail(`Unknown configure target: ${target}`);
}

function status(argv) {
  const { agent, rest } = extractOptionValue(argv, "--agent");
  if (agent === "codex") {
    return runCodexConfigure(["--status", ...withDefaultRoot(rest)]);
  }
  if (!agent || agent === "claude") {
    return runClaudeConfigure(["--status", ...withDefaultRoot(rest)]);
  }
  fail(`Unknown status agent: ${agent}`);
}

function plugin(argv) {
  const [action, ...rest] = argv;
  if (action === "enable") {
    return runClaudeConfigure(["--enable-plugin", ...withDefaultRoot(rest)]);
  }
  if (action === "disable") {
    return runClaudeConfigure(["--disable-plugin", ...withDefaultRoot(rest)]);
  }
  fail("Usage: ai-policy plugin <enable|disable> [--root <project>]");
}

function postRefine(argv) {
  const [mode, ...rest] = argv;
  if (!mode || mode.startsWith("-")) {
    fail("Usage: ai-policy post-refine <off|light|standard|strict> [--root <project>]");
  }
  return runClaudeConfigure(["--post-refine", mode, ...withDefaultRoot(rest)]);
}

function runClaudeConfigure(args) {
  const normalized = addPluginRoot(args);
  return runPython([CLAUDE_CONFIGURE_SCRIPT, ...normalized]);
}

function runCodexConfigure(args) {
  const normalized = addPluginRoot(args);
  return runPython([CODEX_CONFIGURE_SCRIPT, ...normalized]);
}

function withDefaultRoot(args) {
  if (hasOption(args, "--root")) {
    return args;
  }
  return ["--root", process.cwd(), ...args];
}

function addPluginRoot(args) {
  if (hasOption(args, "--plugin-root")) {
    return args;
  }
  return [...args, "--plugin-root", PACKAGE_ROOT];
}

function hasOption(args, name) {
  return args.some((item) => item === name || item.startsWith(`${name}=`));
}

function extractOptionValue(args, name) {
  const rest = [];
  let value = null;
  for (let index = 0; index < args.length; index += 1) {
    const item = args[index];
    if (item === name) {
      value = args[index + 1] || "";
      index += 1;
    } else if (item.startsWith(`${name}=`)) {
      value = item.slice(name.length + 1);
    } else {
      rest.push(item);
    }
  }
  return { agent: value, rest };
}

function withDefaultPolicyRoot(command, args) {
  const commandsUsingPolicyAssets = new Set(["resolve", "explain", "validate", "run", "model"]);
  if (!commandsUsingPolicyAssets.has(command) || hasOption(args, "--policy-root")) {
    return args;
  }
  return ["--policy-root", PACKAGE_ROOT, ...args];
}

function runPython(args) {
  const python = ensurePython();
  const env = {
    ...process.env,
    PYTHONPATH: prependPath(PACKAGE_ROOT, process.env.PYTHONPATH),
  };
  const result = spawnSync(python, args, { stdio: "inherit", env });
  if (result.error) {
    fail(result.error.message);
  }
  return result.status === null ? 1 : result.status;
}

function ensurePython() {
  if (process.env.AI_POLICY_PYTHON) {
    assertPythonVersion(process.env.AI_POLICY_PYTHON);
    return process.env.AI_POLICY_PYTHON;
  }

  const venvPython = venvPythonPath();
  if (fs.existsSync(venvPython)) {
    assertPythonVersion(venvPython);
    return venvPython;
  }

  const basePython = findBasePython();
  const venvDir = path.dirname(path.dirname(venvPython));
  fs.mkdirSync(path.dirname(venvDir), { recursive: true });
  runChecked(basePython, pythonArgs(basePython, ["-m", "venv", venvDir]), undefined);
  runChecked(venvPython, ["-m", "pip", "install", "--disable-pip-version-check", "-e", PACKAGE_ROOT], {
    ...process.env,
    PYTHONPATH: prependPath(PACKAGE_ROOT, process.env.PYTHONPATH),
  });
  assertPythonVersion(venvPython);
  return venvPython;
}

function findBasePython() {
  const candidates = process.platform === "win32" ? ["py", "python", "python3"] : ["python3", "python"];
  for (const candidate of candidates) {
    const result = spawnSync(candidate, pythonArgs(candidate, ["--version"]), { stdio: "ignore" });
    if (!result.error && result.status === 0 && pythonVersion(candidate)) {
      return candidate === "py" ? "py" : candidate;
    }
  }
  fail("Python 3.10+ is required. Install Python or set AI_POLICY_PYTHON.");
}

function assertPythonVersion(command) {
  const version = pythonVersion(command);
  if (!version) {
    fail(`Could not run Python interpreter: ${command}`);
  }
  if (compareVersion(version, MIN_PYTHON) < 0) {
    fail(`Python ${MIN_PYTHON.join(".")}+ is required; found ${version.join(".")} at ${command}`);
  }
}

function pythonVersion(command) {
  const code = "import sys,json; print(json.dumps(list(sys.version_info[:3])))";
  const result = spawnSync(command, pythonArgs(command, ["-c", code]), { encoding: "utf8" });
  if (result.error || result.status !== 0) {
    return null;
  }
  try {
    return JSON.parse(result.stdout.trim());
  } catch {
    return null;
  }
}

function compareVersion(left, right) {
  for (let index = 0; index < right.length; index += 1) {
    const delta = (left[index] || 0) - (right[index] || 0);
    if (delta !== 0) {
      return delta;
    }
  }
  return 0;
}

function pythonArgs(command, args) {
  return command === "py" ? ["-3", ...args] : args;
}

function runChecked(command, args, env) {
  const result = spawnSync(command, args, { stdio: "inherit", env });
  if (result.error) {
    fail(result.error.message);
  }
  if (result.status !== 0) {
    process.exit(result.status || 1);
  }
}

function venvPythonPath() {
  const root = process.env.AI_POLICY_HOME || defaultStateDir();
  if (process.platform === "win32") {
    return path.join(root, "venv", "Scripts", "python.exe");
  }
  return path.join(root, "venv", "bin", "python");
}

function defaultStateDir() {
  if (process.platform === "win32") {
    return path.join(process.env.LOCALAPPDATA || os.homedir(), "ai-policy-runtime");
  }
  return path.join(process.env.XDG_CACHE_HOME || path.join(os.homedir(), ".cache"), "ai-policy-runtime");
}

function prependPath(first, existing) {
  return existing ? `${first}${path.delimiter}${existing}` : first;
}

function doctor() {
  const python = ensurePython();
  const version = pythonVersion(python);
  const checks = {
    packageJson: fs.existsSync(path.join(PACKAGE_ROOT, "package.json")),
    pythonPackage: fs.existsSync(path.join(PACKAGE_ROOT, "ai_policy_runtime", "__init__.py")),
    claudePlugin: fs.existsSync(path.join(PACKAGE_ROOT, ".claude-plugin", "plugin.json")),
    claudeHooks: fs.existsSync(path.join(PACKAGE_ROOT, "hooks", "claude-hooks.json")),
    skills: fs.existsSync(path.join(PACKAGE_ROOT, "skills")),
    packs: fs.existsSync(path.join(PACKAGE_ROOT, "packs")),
  };
  console.log(JSON.stringify({
    packageRoot: PACKAGE_ROOT,
    python,
    pythonVersion: version ? version.join(".") : null,
    stateDir: path.dirname(path.dirname(venvPythonPath())),
    venvPython: venvPythonPath(),
    usingExplicitPython: Boolean(process.env.AI_POLICY_PYTHON),
    checks,
    ok: Object.values(checks).every(Boolean) && Boolean(version),
  }, null, 2));
  return 0;
}

function rebuildRuntime() {
  if (process.env.AI_POLICY_PYTHON) {
    fail("runtime rebuild manages the cached venv; unset AI_POLICY_PYTHON first.");
  }
  const venvDir = path.dirname(path.dirname(venvPythonPath()));
  fs.rmSync(venvDir, { recursive: true, force: true });
  const python = ensurePython();
  console.log(JSON.stringify({
    rebuilt: true,
    python,
    stateDir: path.dirname(venvDir),
  }, null, 2));
  return 0;
}

function printHelp() {
  console.log(`AI Policy Runtime

Usage:
  ai-policy configure claude [--root <project>]
  ai-policy configure codex [--root <project>]
  ai-policy status [--agent <claude|codex>] [--root <project>]
  ai-policy disable [--root <project>]
  ai-policy plugin <enable|disable> [--root <project>]
  ai-policy post-refine <off|light|standard|strict> [--root <project>]
  ai-policy runtime <runtime-command> [...]
  ai-policy runtime rebuild
  ai-policy doctor

Examples:
  ai-policy configure claude --root D:\\work\\project
  ai-policy configure codex --root D:\\work\\project
  ai-policy post-refine standard --root D:\\work\\project
  ai-policy status --agent codex --root D:\\work\\project
`);
}

function fail(message) {
  console.error(`ai-policy: ${message}`);
  process.exit(1);
}

process.exitCode = main(process.argv.slice(2));
