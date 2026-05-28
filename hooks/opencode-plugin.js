const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const PACKAGE_ROOT = "__AI_POLICY_RUNTIME_ROOT__";
const HOOK = path.join(PACKAGE_ROOT, "bin", "ai-policy-hook.js");
const SERVICE = "ai-policy-runtime";
const OPENCODE_STATE = path.join(".policy", "current", "opencode-plugin-state.json");
const OPENCODE_POST_REFINE_PROMPT = path.join(
  ".policy",
  "current",
  "opencode-post-refine-prompt.md",
);

function runHook(name, payload) {
  const result = spawnSync(process.execPath, [HOOK, name], {
    input: JSON.stringify(payload),
    encoding: "utf8",
    env: hookEnvironment(),
  });
  if (result.error) {
    return { ok: false, error: result.error.message };
  }
  const output = result.stdout.trim();
  if (!output) {
    return { ok: result.status === 0, response: {} };
  }
  try {
    return { ok: result.status === 0, response: parseHookOutput(output), stderr: result.stderr };
  } catch (error) {
    return { ok: false, error: error.message, stdout: output, stderr: result.stderr };
  }
}

function hookEnvironment() {
  const env = {
    ...process.env,
    AI_POLICY_AGENT: "opencode",
    AI_POLICY_ROOT: PACKAGE_ROOT,
  };
  if (
    !env.AI_POLICY_EMBEDDING_PROVIDER &&
    !env.AI_POLICY_EMBEDDING_BASE_URL &&
    !env.AI_POLICY_EMBEDDING_API_KEY
  ) {
    delete env.OPENAI_API_KEY;
  }
  return env;
}

function parseHookOutput(output) {
  try {
    return JSON.parse(output);
  } catch (originalError) {
    const lines = output.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    for (const line of lines.reverse()) {
      if (!line.startsWith("{") && !line.startsWith("[")) {
        continue;
      }
      try {
        return JSON.parse(line);
      } catch {
        // Try earlier candidates below.
      }
    }
    for (let index = output.length - 1; index >= 0; index -= 1) {
      const char = output[index];
      if (char !== "{" && char !== "[") {
        continue;
      }
      try {
        return JSON.parse(output.slice(index).trim());
      } catch {
        // Keep the original parse error if no candidate is valid.
      }
    }
    throw originalError;
  }
}

function promptFrom(input, output) {
  const direct =
    stringOrNull(input?.prompt) ??
    stringOrNull(input?.text) ??
    stringOrNull(input?.message) ??
    stringOrNull(output?.prompt) ??
    stringOrNull(output?.text);
  if (direct) {
    return direct;
  }
  return (
    promptFromParts(output?.parts) ||
    promptFromParts(input?.parts) ||
    promptFromParts(output?.message?.parts) ||
    promptFromParts(input?.message?.parts) ||
    ""
  );
}

function stringOrNull(value) {
  return typeof value === "string" ? value : null;
}

function promptFromParts(parts) {
  if (!Array.isArray(parts)) {
    return "";
  }
  return parts
    .map((part) => stringOrNull(part?.text) ?? stringOrNull(part?.content) ?? "")
    .filter(Boolean)
    .join("\n")
    .trim();
}

function idsFrom(source) {
  const properties = source?.properties ?? source ?? {};
  const message = properties.message ?? {};
  const session = properties.session ?? {};
  return {
    session_id:
      properties.sessionID ??
      properties.sessionId ??
      properties.session_id ??
      session.id ??
      null,
    turn_id:
      properties.messageID ??
      properties.messageId ??
      properties.message_id ??
      message.id ??
      properties.id ??
      null,
  };
}

function mergeIds(primary, fallback) {
  return {
    session_id: primary.session_id ?? fallback.session_id ?? null,
    turn_id: primary.turn_id ?? fallback.turn_id ?? null,
  };
}

function appendContext(output, context) {
  if (!context || !output) {
    return;
  }
  if (typeof output.prompt === "string") {
    output.prompt = `${output.prompt}\n\n${context}`;
    return;
  }
  if (typeof output.text === "string") {
    output.text = `${output.text}\n\n${context}`;
    return;
  }
  if (Array.isArray(output.context)) {
    output.context.push(context);
    return;
  }
  if (Array.isArray(output.parts)) {
    output.parts.push({ type: "text", text: context });
  }
}

function runUserPromptHook(cwd, prompt, ids) {
  return runHook("opencode-user-prompt-submit", {
    cwd,
    prompt,
    ...ids,
  });
}

async function log(client, level, message, extra) {
  await client?.app?.log?.({
    body: { service: SERVICE, level, message, extra },
  });
}

function writeState(cwd, state) {
  const statePath = path.join(cwd, OPENCODE_STATE);
  fs.mkdirSync(path.dirname(statePath), { recursive: true });
  fs.writeFileSync(statePath, `${JSON.stringify(state, null, 2)}\n`, "utf8");
}

function writePostRefinePrompt(cwd, prompt) {
  const promptPath = path.join(cwd, OPENCODE_POST_REFINE_PROMPT);
  fs.mkdirSync(path.dirname(promptPath), { recursive: true });
  fs.writeFileSync(promptPath, `${prompt}\n`, "utf8");
}

function removePostRefinePrompt(cwd) {
  fs.rmSync(path.join(cwd, OPENCODE_POST_REFINE_PROMPT), { force: true });
}

async function AiPolicyRuntime({ client, directory, worktree }) {
  const cwd = worktree || directory || process.cwd();
  await log(client, "info", "OpenCode plugin initialized", { packageRoot: PACKAGE_ROOT, cwd });

  return {
    "shell.env": async (_input, output) => {
      output.env = output.env || {};
      output.env.AI_POLICY_AGENT = "opencode";
      output.env.AI_POLICY_ROOT = PACKAGE_ROOT;
    },

    "tui.prompt.append": async (input, output) => {
      const prompt = promptFrom(input, output);
      if (!prompt || typeof prompt !== "string") {
        return;
      }
      const result = runUserPromptHook(cwd, prompt, idsFrom(input));
      const context = result.response?.hookSpecificOutput?.additionalContext;
      appendContext(output, context);
      if (!result.ok) {
        await log(client, "warn", "User prompt hook failed", result);
      }
    },

    "chat.message": async (input, output) => {
      const prompt = promptFrom(input, output);
      if (!prompt || typeof prompt !== "string") {
        return;
      }
      const result = runUserPromptHook(cwd, prompt, mergeIds(idsFrom(output), idsFrom(input)));
      const context = result.response?.hookSpecificOutput?.additionalContext;
      appendContext(output, context);
      writeState(cwd, {
        event: "chat.message",
        hookOk: result.ok,
        promptChars: prompt.length,
        contextChars: String(context || "").length,
        error: result.error ?? null,
      });
      if (!result.ok) {
        await log(client, "warn", "User chat message hook failed", result);
      }
    },

    event: async ({ event }) => {
      if (event?.type !== "session.idle") {
        return;
      }
      const result = runHook("opencode-stop-refinement", {
        cwd,
        ...idsFrom(event),
      });
      if (!result.ok || result.response?.decision !== "block") {
        removePostRefinePrompt(cwd);
        writeState(cwd, {
          event: "session.idle",
          postRefinePrepared: false,
          hookOk: result.ok,
          decision: result.response?.decision ?? null,
          error: result.error ?? null,
        });
        return;
      }
      writePostRefinePrompt(cwd, String(result.response.reason || ""));
      writeState(cwd, {
        event: "session.idle",
        postRefinePrepared: true,
        reasonChars: String(result.response.reason || "").length,
      });
      await log(client, "info", "Post-refinement prompt prepared", {
        reasonChars: String(result.response.reason || "").length,
      });
    },
  };
}

module.exports = AiPolicyRuntime;
