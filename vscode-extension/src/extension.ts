import * as fs from 'fs/promises';
import { existsSync } from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';

type PolicyConfig = {
  enabled: boolean;
  agents: AgentTarget[];
  packs: string[];
  policyRoot?: string;
  autoInstall: boolean;
  embeddingProvider?: string;
  embeddingBaseUrl?: string;
  embeddingApiKey?: string;
  embeddingModel?: string;
  embeddingLocalModel?: string;
  embeddingTimeout?: string;
  gitCommitStyle: GitCommitStyle;
  postRefine: 'off' | 'light' | 'standard' | 'strict';
  postRefinePacks: string[];
  verifyTarget?: string;
};

type AgentTarget = 'codex' | 'claude';
type GitCommitStyle = 'auto' | 'conventional' | 'imperative';

type PolicyPaths = {
  root: string;
  policyRoot: string;
  config: string;
  codexHooks: string;
  codexConfig: string;
  claudeSettings: string;
  effectivePrompt: string;
  hookState: string;
};

type EmbeddingEnvironmentConfig = Pick<
  PolicyConfig,
  'embeddingProvider' | 'embeddingBaseUrl' | 'embeddingApiKey' | 'embeddingModel' | 'embeddingTimeout'
>;

type LocalModelState = {
  defaultPath: string;
  installed: boolean;
  configuredPath?: string;
  configuredInstalled?: boolean;
  available: boolean;
};

type EmbeddingAvailabilityState = {
  remoteConfigured: boolean;
  remoteSummary: string;
  local: LocalModelState;
};

type PackItem = vscode.QuickPickItem & {
  label: string;
  category: string;
  tags: string[];
};

const CONFIG_SECTION = 'aiPolicy';
const POLICY_CONFIG_FILE = path.join('.policy', 'config.json');
const CODEX_HOOKS_FILE = path.join('.codex', 'hooks.json');
const CODEX_CONFIG_FILE = path.join('.codex', 'config.toml');
const CLAUDE_SETTINGS_FILE = path.join('.claude', 'settings.local.json');
const EFFECTIVE_PROMPT_FILE = path.join('.policy', 'current', 'effective-prompt.md');
const HOOK_STATE_FILE = path.join('.policy', 'current', 'agent-hook-state.json');
const CLAUDE_MARKETPLACE_NAME = 'ai-policy-runtime';
const CLAUDE_PLUGIN_ID = 'ai-policy-runtime@ai-policy-runtime';
const DEFAULT_AGENTS: AgentTarget[] = ['codex'];
const DEFAULT_PACKS = ['cpp.safe_generation'];
const DEFAULT_POST_REFINE_PACKS = ['generic.production_refinement'];
const REQUIRED_RUNTIME_PATHS = [
  path.join('bin', 'ai-policy-hook.js'),
  path.join('bin', 'ai-policy.js'),
  path.join('hooks', 'hooks.json'),
  path.join('hooks', 'codex-hooks.json'),
  path.join('hooks', 'user_prompt_submit.py'),
  path.join('hooks', 'stop_refinement.py'),
  path.join('.claude-plugin', 'plugin.json'),
  path.join('.claude-plugin', 'marketplace.json'),
  path.join('.codex-plugin', 'plugin.json'),
  path.join('ai_policy_runtime', '__init__.py'),
  path.join('packs', 'cpp_safe_generation.pack.yaml'),
  path.join('skills', 'domain', 'git', 'workflow', 'commit_hygiene.skill.yaml'),
  path.join('schemas', 'effective-rules.schema.json'),
  'pyproject.toml'
];

const COMMANDS = {
  enable: 'aiPolicy.enable',
  disable: 'aiPolicy.disable',
  enablePostRefine: 'aiPolicy.enablePostRefine',
  configurePacks: 'aiPolicy.configurePacks',
  showStatus: 'aiPolicy.showStatus',
  showEffectiveRules: 'aiPolicy.showEffectiveRules',
  validateRuntime: 'aiPolicy.validateRuntime'
} as const;

const KNOWN_PACKS: PackItem[] = [
  {
    label: 'cpp.safe_generation',
    description: 'C++ safety-first code generation',
    category: 'Recommended',
    tags: ['C++', 'Safety', 'Generation']
  },
  {
    label: 'cpp.low_latency',
    description: 'C++ hot-path and low-latency work',
    category: 'Development',
    tags: ['C++', 'Performance']
  },
  {
    label: 'cpp.code_review',
    description: 'C++ review with safety checks',
    category: 'Review',
    tags: ['C++', 'Review', 'Safety']
  },
  {
    label: 'cpp.library_api_design',
    description: 'C++ API design and parameter intent',
    category: 'Design',
    tags: ['C++', 'API']
  },
  {
    label: 'cpp.modernization',
    description: 'Modern C++ refactoring guidance',
    category: 'Refinement',
    tags: ['C++', 'Refactor']
  },
  {
    label: 'cpp.production_refinement',
    description: 'C++ production polish and safety',
    category: 'Refinement',
    tags: ['C++', 'Production', 'Safety']
  },
  {
    label: 'generic.production_refinement',
    description: 'General code quality refinement',
    category: 'Refinement',
    tags: ['Generic', 'Production']
  },
  {
    label: 'python.production_refinement',
    description: 'Python production polish, typing, testing, security, and performance',
    category: 'Refinement',
    tags: ['Python', 'Production']
  },
  {
    label: 'cmake.production_refinement',
    description: 'CMake production polish for targets, dependencies, presets, and packaging',
    category: 'Refinement',
    tags: ['CMake', 'Production', 'Build']
  },
  {
    label: 'git.best_practices',
    description: 'Git commits, branches, conflicts, and history safety',
    category: 'Workflow',
    tags: ['Git', 'Review', 'Safety']
  },
  {
    label: 'cmake.best_practices',
    description: 'CMake targets, dependencies, packaging, presets, and tests',
    category: 'Build',
    tags: ['CMake', 'C++', 'Build']
  },
  {
    label: 'python.best_practices',
    description: 'Python professional engineering, APIs, typing, packaging, security, and tests',
    category: 'Development',
    tags: ['Python', 'API', 'Testing', 'Packaging']
  }
];

export function activate(context: vscode.ExtensionContext): void {
  const workspace = new PolicyWorkspace(context.extensionUri.fsPath);
  const status = new PolicyStatusBar(workspace);
  const panel = new PolicyConfigViewProvider(context.extensionUri, workspace, status);

  context.subscriptions.push(
    status,
    vscode.window.registerWebviewViewProvider(PolicyConfigViewProvider.viewType, panel),
    vscode.commands.registerCommand(COMMANDS.enable, () => setEnabled(workspace, status, true)),
    vscode.commands.registerCommand(COMMANDS.disable, () => setEnabled(workspace, status, false)),
    vscode.commands.registerCommand(COMMANDS.enablePostRefine, () => enablePostRefine(workspace, status, panel)),
    vscode.commands.registerCommand(COMMANDS.configurePacks, () => configurePacks(workspace)),
    vscode.commands.registerCommand(COMMANDS.showStatus, () => showStatus(workspace)),
    vscode.commands.registerCommand(COMMANDS.showEffectiveRules, () => showEffectiveRules(workspace)),
    vscode.commands.registerCommand(COMMANDS.validateRuntime, () => validateRuntime(workspace)),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(CONFIG_SECTION)) {
        void workspace.syncProjectConfig().then(() => {
          status.refresh();
          panel.refresh();
        });
      }
    }),
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      void workspace.syncProjectConfig().then(() => {
        status.refresh();
        panel.refresh();
      });
    })
  );

  void workspace.syncProjectConfig().then(() => {
    status.refresh();
    panel.refresh();
  });
}

export function deactivate(): void {
  // VS Code disposes registered subscriptions automatically.
}

class PolicyWorkspace {
  constructor(private readonly extensionRoot: string) {}

  /** Read VS Code settings and write the project-local hook config. */
  async syncProjectConfig(): Promise<void> {
    const paths = this.pathsOrWarn();
    if (!paths) {
      return;
    }

    const config = this.readConfig();
    await fs.mkdir(path.dirname(paths.config), { recursive: true });
    await fs.writeFile(paths.config, `${JSON.stringify(projectConfig(config), null, 2)}\n`, 'utf8');
    await Promise.all([
      syncCodexAgentHooks(paths, config),
      syncClaudeAgentHooks(paths, config)
    ]);
  }

  async saveConfig(config: PolicyConfig): Promise<void> {
    await Promise.all([
      this.updateSetting('enabled', config.enabled),
      this.updateSetting('agents', config.agents),
      this.updateSetting('packs', config.packs),
      this.updateSetting('policyRoot', config.policyRoot ?? ''),
      this.updateSetting('autoInstall', config.autoInstall),
      this.updateSetting('embeddingProvider', config.embeddingProvider ?? ''),
      this.updateSetting('embeddingBaseUrl', config.embeddingBaseUrl ?? ''),
      this.updateSetting('embeddingApiKey', config.embeddingApiKey ?? ''),
      this.updateSetting('embeddingModel', config.embeddingModel ?? ''),
      this.updateSetting('embeddingLocalModel', config.embeddingLocalModel ?? ''),
      this.updateSetting('embeddingTimeout', config.embeddingTimeout ?? ''),
      this.updateSetting('gitCommitStyle', config.gitCommitStyle),
      this.updateSetting('postRefine', config.postRefine),
      this.updateSetting('postRefinePacks', config.postRefinePacks),
      this.updateSetting('verifyTarget', config.verifyTarget ?? '')
    ]);
    await this.syncProjectConfig();
  }

  readConfig(): PolicyConfig {
    const config = vscode.workspace.getConfiguration(CONFIG_SECTION);
    return {
      enabled: config.get<boolean>('enabled', false),
      agents: normalizeAgents(config.get<string[]>('agents', DEFAULT_AGENTS)),
      packs: config.get<string[]>('packs', DEFAULT_PACKS),
      policyRoot: cleanOptionalString(config.get<string>('policyRoot', '')),
      autoInstall: config.get<boolean>('autoInstall', true),
      embeddingProvider: normalizeEmbeddingProvider(config.get<string>('embeddingProvider', '')),
      embeddingBaseUrl: cleanOptionalString(config.get<string>('embeddingBaseUrl', '')),
      embeddingApiKey: cleanOptionalString(config.get<string>('embeddingApiKey', '')),
      embeddingModel: cleanOptionalString(config.get<string>('embeddingModel', '')),
      embeddingLocalModel: cleanOptionalString(config.get<string>('embeddingLocalModel', '')),
      embeddingTimeout: cleanOptionalString(config.get<string>('embeddingTimeout', '')),
      gitCommitStyle: normalizeGitCommitStyle(config.get<string>('gitCommitStyle', 'auto')),
      postRefine: normalizePostRefineMode(config.get<string>('postRefine', 'off')),
      postRefinePacks: config.get<string[]>('postRefinePacks', DEFAULT_POST_REFINE_PACKS),
      verifyTarget: cleanOptionalString(config.get<string>('verifyTarget', ''))
    };
  }

  async updateSetting(key: keyof PolicyConfig, value: unknown): Promise<void> {
    await vscode.workspace
      .getConfiguration(CONFIG_SECTION)
      .update(key, value, vscode.ConfigurationTarget.Workspace);
  }

  pathsOrWarn(): PolicyPaths | undefined {
    const root = this.workspaceRoot();
    if (!root) {
      vscode.window.showWarningMessage('Open a workspace folder before configuring AI Policy Runtime.');
      return undefined;
    }
    return {
      root,
      policyRoot: this.resolveRuntimeRoot(root),
      config: path.join(root, POLICY_CONFIG_FILE),
      codexHooks: path.join(root, CODEX_HOOKS_FILE),
      codexConfig: path.join(root, CODEX_CONFIG_FILE),
      claudeSettings: path.join(root, CLAUDE_SETTINGS_FILE),
      effectivePrompt: path.join(root, EFFECTIVE_PROMPT_FILE),
      hookState: path.join(root, HOOK_STATE_FILE)
    };
  }

  rootPath(): string | undefined {
    return this.workspaceRoot();
  }

  runtimeRoot(): string {
    return this.resolveRuntimeRoot(this.workspaceRoot());
  }

  private resolveRuntimeRoot(workspaceRoot: string | undefined): string {
    const config = this.readConfig();
    if (config.policyRoot) {
      return path.isAbsolute(config.policyRoot)
        ? config.policyRoot
        : path.resolve(workspaceRoot ?? process.cwd(), config.policyRoot);
    }
    return this.extensionRoot;
  }

  private workspaceRoot(): string | undefined {
    return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  }
}

class PolicyConfigViewProvider implements vscode.WebviewViewProvider {
  static readonly viewType = 'aiPolicy.config';
  private view?: vscode.WebviewView;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly workspace: PolicyWorkspace,
    private readonly status: PolicyStatusBar
  ) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'media')]
    };
    this.render();

    view.webview.onDidReceiveMessage((message: { type: string; config?: PolicyConfig }) => {
      void this.handleMessage(message);
    });
  }

  private async handleMessage(message: { type: string; config?: PolicyConfig }): Promise<void> {
    if (message.type === 'save' && message.config) {
      const before = this.workspace.readConfig();
      const next = normalizeConfig(message.config);
      await this.workspace.saveConfig(next);
      this.status.refresh();
      await this.view?.webview.postMessage({ type: 'saved' });
      maybeShowCodexTrustHint(this.workspace, before, next);
      maybeShowClaudeRestartHint(before, next);
      return;
    }
    if (message.type === 'showEffectiveRules') {
      await showEffectiveRules(this.workspace);
      return;
    }
    if (message.type === 'validateRuntime') {
      await validateRuntime(this.workspace);
    }
  }

  private render(): void {
    if (!this.view) {
      return;
    }
    this.view.webview.html = this.html(this.view.webview, this.workspace.readConfig());
  }

  refresh(): void {
    this.render();
  }

  private html(webview: vscode.Webview, config: PolicyConfig): string {
    const nonce = nonceValue();
    const state = JSON.stringify({
      config,
      environmentConfig: readEmbeddingEnvironmentConfig(),
      embeddingAvailability: readEmbeddingAvailability(config, this.workspace.rootPath(), this.workspace.runtimeRoot()),
      packs: KNOWN_PACKS.map(({ label, description, category, tags }) => ({
        label,
        description,
        category,
        tags
      }))
    });
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
  <title>AI Policy Runtime</title>
  <style>
    :root {
      color-scheme: light dark;
      --line: var(--vscode-sideBarSectionHeader-border, color-mix(in srgb, var(--vscode-foreground) 18%, transparent));
      --muted: var(--vscode-descriptionForeground);
      --accent: var(--vscode-button-background);
      --accent-text: var(--vscode-button-foreground);
    }
    body {
      margin: 0;
      padding: 18px 16px 22px;
      color: var(--vscode-foreground);
      background: var(--vscode-sideBar-background);
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
    }
    .mast {
      display: grid;
      gap: 6px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--line);
    }
    h1 {
      margin: 0;
      font-size: 16px;
      font-weight: 700;
      letter-spacing: 0;
    }
    .subtle {
      color: var(--muted);
      line-height: 1.45;
    }
    .section {
      display: grid;
      gap: 10px;
      padding: 16px 0;
      border-bottom: 1px solid var(--line);
    }
    .row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .check-row {
      display: grid;
      grid-template-columns: 18px 1fr;
      gap: 8px;
      align-items: center;
      font-weight: 400;
    }
    label {
      font-weight: 600;
    }
    input[type="text"], select {
      width: 100%;
      box-sizing: border-box;
      color: var(--vscode-input-foreground);
      background: var(--vscode-input-background);
      border: 1px solid var(--vscode-input-border, transparent);
      padding: 7px 8px;
      outline: none;
    }
    input[type="text"]:focus, select:focus {
      border-color: var(--vscode-focusBorder);
    }
    .pack-list {
      display: grid;
      gap: 8px;
    }
    input[type="password"] {
      width: 100%;
      box-sizing: border-box;
      color: var(--vscode-input-foreground);
      background: var(--vscode-input-background);
      border: 1px solid var(--vscode-input-border, transparent);
      padding: 7px 8px;
      outline: none;
    }
    input[type="password"]:focus {
      border-color: var(--vscode-focusBorder);
    }
    .field {
      display: grid;
      gap: 6px;
    }
    .switch-note {
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .provider-note {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      padding: 2px 0;
    }
    .model-status {
      border: 1px solid var(--line);
      background: var(--vscode-editorWidget-background);
      padding: 8px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    .model-status.warning {
      color: var(--vscode-inputValidation-warningForeground, var(--vscode-foreground));
      border-color: var(--vscode-inputValidation-warningBorder, var(--line));
      background: var(--vscode-inputValidation-warningBackground, var(--vscode-editorWidget-background));
    }
    .pack {
      display: grid;
      grid-template-columns: 18px 1fr;
      gap: 8px;
      align-items: start;
      padding: 8px;
      border: 1px solid var(--line);
      background: var(--vscode-editorWidget-background);
    }
    .pack strong {
      font-weight: 600;
      overflow-wrap: anywhere;
    }
    .pack span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      margin-top: 2px;
    }
    .empty {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      padding: 4px 0;
    }
    [hidden] {
      display: none !important;
    }
  </style>
</head>
<body>
  <div class="mast">
    <h1>AI Policy Runtime</h1>
    <div class="subtle">Agent prompt policy for this workspace.</div>
  </div>

  <div class="section">
    <div class="row">
      <label for="enabled">Enable agent hooks</label>
      <input id="enabled" type="checkbox">
    </div>
    <p class="switch-note">When enabled, the selected agents receive task-scoped Effective Rules for this workspace.</p>
    <div class="row">
      <label for="autoInstall">Install dependencies automatically</label>
      <input id="autoInstall" type="checkbox">
    </div>
  </div>

  <div class="section">
    <label>Agents</label>
    <label class="check-row" for="agentCodex">
      <input id="agentCodex" type="checkbox" value="codex">
      <span>Codex</span>
    </label>
    <label class="check-row" for="agentClaude">
      <input id="agentClaude" type="checkbox" value="claude">
      <span>Claude Code</span>
    </label>
  </div>

  <div class="section">
    <div class="field">
      <label for="gitCommitStyle">Git commit style</label>
      <select id="gitCommitStyle">
        <option value="auto">Auto</option>
        <option value="conventional">Conventional Commits</option>
        <option value="imperative">Plain imperative subjects</option>
      </select>
    </div>
    <p class="switch-note">Auto follows explicit project tooling or recent history; otherwise Git tasks use concise imperative subjects.</p>
  </div>

  <div class="section">
    <div class="row">
      <label for="postRefineEnabled">Post-refinement</label>
      <input id="postRefineEnabled" type="checkbox">
    </div>
    <p class="switch-note">Continue once before a supported agent ends a turn to compress structure, remove accidental complexity, and run practical checks.</p>
    <div id="postRefineControls" class="field">
      <label for="postRefine">Mode</label>
      <select id="postRefine">
        <option value="standard">Standard</option>
        <option value="light">Light</option>
        <option value="strict">Strict</option>
      </select>
      <div class="field">
        <label for="verifyTarget">Verification scope</label>
        <input id="verifyTarget" type="text" placeholder="src">
        <p class="switch-note">Optional path or target the refinement pass should verify before ending.</p>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="row">
      <label>Packs</label>
      <span id="selectedCount" class="subtle">0 selected</span>
    </div>
    <input id="packSearch" type="text" placeholder="Search packs">
    <div id="packs" class="pack-list"></div>
  </div>

  <div class="section">
    <label for="policyRoot">Policy root</label>
    <input id="policyRoot" type="text" placeholder="Leave empty: use this extension's bundled runtime">
  </div>

  <div class="section">
    <div class="field">
      <label for="embeddingProvider">Embedding provider</label>
      <select id="embeddingProvider">
        <option value="">Auto</option>
        <option value="openai-compatible">OpenAI-compatible /v1/embeddings</option>
        <option value="local">Local sentence-transformers</option>
      </select>
    </div>
    <div id="autoEmbeddingNote" class="provider-note">
      Runtime chooses an OpenAI-compatible endpoint when remote credentials are configured, otherwise a local sentence-transformers model when available.
    </div>
    <div id="autoEmbeddingStatus" class="model-status"></div>
    <div id="openAiEmbeddingFields" class="field">
      <div class="field">
        <label for="embeddingBaseUrl">OpenAI-compatible base URL</label>
        <input id="embeddingBaseUrl" type="text" placeholder="https://api.openai.com/v1">
      </div>
      <div class="field">
        <label for="embeddingApiKey">Embedding API key</label>
        <input id="embeddingApiKey" type="password" placeholder="Uses OPENAI_API_KEY when empty">
      </div>
    </div>
    <div id="localEmbeddingNote" class="provider-note">
      Uses sentence-transformers from the local Python environment/cache. No API key is used.
    </div>
    <div id="localModelStatus" class="model-status"></div>
    <div id="embeddingModelField" class="field">
      <label id="embeddingModelLabel" for="embeddingModel">Embedding model</label>
      <input id="embeddingModel" type="text" placeholder="text-embedding-3-small">
    </div>
    <div id="embeddingTimeoutField" class="field">
      <label for="embeddingTimeout">Embedding timeout seconds</label>
      <input id="embeddingTimeout" type="text" placeholder="30">
    </div>
  </div>

  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const state = ${state};
    const envConfig = state.environmentConfig || {};
    const availability = state.embeddingAvailability || {};
    const localModel = availability.local || {};
    const byId = (id) => document.getElementById(id);
    const selected = new Set(state.config.packs || []);
    const agents = new Set(state.config.agents || ['codex']);
    let draftEmbeddingModel = state.config.embeddingModel || '';
    let draftEmbeddingLocalModel = state.config.embeddingLocalModel || '';
    byId('enabled').checked = Boolean(state.config.enabled);
    byId('autoInstall').checked = Boolean(state.config.autoInstall);
    byId('agentCodex').checked = agents.has('codex');
    byId('agentClaude').checked = agents.has('claude');
    byId('gitCommitStyle').value = state.config.gitCommitStyle || 'auto';
    byId('postRefineEnabled').checked = (state.config.postRefine || 'off') !== 'off';
    byId('postRefine').value = state.config.postRefine && state.config.postRefine !== 'off'
      ? state.config.postRefine
      : 'standard';
    byId('verifyTarget').value = state.config.verifyTarget || '';
    byId('policyRoot').value = state.config.policyRoot || '';
    setEmbeddingValue('embeddingProvider', 'embeddingProvider');
    setEmbeddingValue('embeddingBaseUrl', 'embeddingBaseUrl');
    setEmbeddingValue('embeddingApiKey', 'embeddingApiKey');
    setEmbeddingValue('embeddingTimeout', 'embeddingTimeout');
    setProviderModelValue();
    byId('embeddingProvider').dataset.previousProvider = byId('embeddingProvider').value;
    syncEmbeddingProviderFields();

    const packs = byId('packs');

    function setEmbeddingValue(id, key) {
      const field = byId(id);
      const configured = state.config[key] || '';
      const environment = envConfig[key] || '';
      field.value = configured || environment;
      field.dataset.envValue = environment;
      field.dataset.configured = configured ? 'true' : 'false';
      field.dataset.userEdited = 'false';
      field.addEventListener('input', () => { field.dataset.userEdited = 'true'; });
      field.addEventListener('change', () => { field.dataset.userEdited = 'true'; });
    }

    function setProviderModelValue() {
      const field = byId('embeddingModel');
      const provider = byId('embeddingProvider').value;
      const configured = provider === 'local'
        ? draftEmbeddingLocalModel
        : draftEmbeddingModel;
      const environment = provider === 'local' ? '' : envConfig.embeddingModel || '';
      field.value = configured || environment;
      field.dataset.envValue = environment;
      field.dataset.configured = configured ? 'true' : 'false';
      field.dataset.userEdited = 'false';
      field.addEventListener('input', () => {
        field.dataset.userEdited = 'true';
        rememberProviderModelValue();
      });
      field.addEventListener('change', () => {
        field.dataset.userEdited = 'true';
        rememberProviderModelValue();
      });
    }

    function rememberProviderModelValue(provider = byId('embeddingProvider').value) {
      const value = byId('embeddingModel').value.trim();
      if (provider === 'local') {
        draftEmbeddingLocalModel = value;
      } else {
        draftEmbeddingModel = value;
      }
    }

    function packMarkup(pack) {
      const row = document.createElement('label');
      row.className = 'pack';
      row.innerHTML = '<input type="checkbox" value="' + pack.label + '">' +
        '<div><strong>' + pack.label + '</strong><span>' + pack.description + '</span></div>';
      row.querySelector('input').checked = selected.has(pack.label);
      row.querySelector('input').addEventListener('change', (event) => {
        if (event.target.checked) {
          selected.add(pack.label);
        } else {
          selected.delete(pack.label);
        }
        syncPackInputs();
        renderSelected();
        scheduleSave();
      });
      return row;
    }

    function renderPacks() {
      const query = byId('packSearch').value.trim().toLowerCase();
      packs.innerHTML = '';
      const matches = state.packs.filter((pack) => {
        const haystack = [pack.label, pack.description, pack.category].concat(pack.tags).join(' ').toLowerCase();
        return !query || haystack.includes(query);
      });
      matches.forEach((pack) => packs.appendChild(packMarkup(pack)));
      if (!matches.length) {
        packs.innerHTML = '<div class="empty">No packs match this search.</div>';
      }
    }

    function syncPackInputs() {
      document.querySelectorAll('input[value]').forEach((item) => {
        if (state.packs.some((pack) => pack.label === item.value)) {
          item.checked = selected.has(item.value);
        }
      });
    }

    function renderSelected() {
      const labels = Array.from(selected);
      byId('selectedCount').textContent = labels.length + ' selected';
    }

    renderPacks();
    renderSelected();
    syncPostRefineControls();

    byId('packSearch').addEventListener('input', renderPacks);
    byId('embeddingProvider').addEventListener('change', () => {
      const provider = byId('embeddingProvider');
      const previousProvider = provider.dataset.previousProvider || '';
      if (provider.value !== provider.dataset.previousProvider) {
        rememberProviderModelValue(previousProvider);
        provider.dataset.previousProvider = provider.value;
        setProviderModelValue();
      }
      syncEmbeddingProviderFields();
      scheduleSave();
    });
    byId('postRefineEnabled').addEventListener('change', () => {
      if (byId('postRefineEnabled').checked && byId('postRefine').value === 'off') {
        byId('postRefine').value = 'standard';
      }
      syncPostRefineControls();
      scheduleSave();
    });

    const configFieldIds = [
      'enabled',
      'autoInstall',
      'agentCodex',
      'agentClaude',
      'gitCommitStyle',
      'postRefine',
      'verifyTarget',
      'policyRoot',
      'embeddingProvider',
      'embeddingBaseUrl',
      'embeddingApiKey',
      'embeddingModel',
      'embeddingTimeout'
    ];
    for (const id of configFieldIds) {
      const field = byId(id);
      field.addEventListener('change', scheduleSave);
      if (field.type === 'text' || field.type === 'password') {
        field.addEventListener('input', scheduleSave);
      }
    }

    function syncPostRefineControls() {
      byId('postRefineControls').hidden = !byId('postRefineEnabled').checked;
    }

    function syncEmbeddingProviderFields() {
      const provider = byId('embeddingProvider').value;
      const isOpenAi = provider === 'openai-compatible';
      const isLocal = provider === 'local';
      byId('autoEmbeddingNote').hidden = Boolean(provider);
      byId('autoEmbeddingStatus').hidden = Boolean(provider);
      byId('openAiEmbeddingFields').hidden = !isOpenAi;
      byId('localEmbeddingNote').hidden = !isLocal;
      byId('localModelStatus').hidden = !isLocal;
      byId('embeddingModelField').hidden = !(isOpenAi || isLocal);
      byId('embeddingTimeoutField').hidden = !isOpenAi;
      byId('embeddingModelLabel').textContent = isLocal ? 'Local model path' : 'Embedding model';
      byId('embeddingModel').placeholder = isLocal
        ? 'Path to a sentence-transformers model directory'
        : 'text-embedding-3-small';
      byId('localModelStatus').textContent = localModelStatusText();
      renderAutoEmbeddingStatus();
    }

    function renderAutoEmbeddingStatus() {
      const status = byId('autoEmbeddingStatus');
      const lines = [
        'OpenAI-compatible: ' + (availability.remoteConfigured ? 'configured (' + availability.remoteSummary + ')' : 'not configured'),
        autoLocalModelSummary()
      ];
      if (availability.remoteConfigured) {
        lines.push('Auto will use OpenAI-compatible embeddings.');
        status.classList.remove('warning');
      } else if (localModel.available) {
        lines.push('Auto will use the local sentence-transformers model.');
        status.classList.remove('warning');
      } else {
        lines.push('Configure an OpenAI-compatible endpoint or install the default local model before using semantic analysis.');
        status.classList.add('warning');
      }
      status.textContent = lines.join('\\n');
    }

    function localModelStatusText() {
      if (localModel.configuredPath) {
        return localModel.configuredInstalled
          ? 'Using configured local model: ' + localModel.configuredPath
          : 'Configured local model not found: ' + localModel.configuredPath;
      }
      return localModel.installed
        ? 'Using default local model: ' + localModel.defaultPath
        : 'Default local model not found: ' + localModel.defaultPath;
    }

    function autoLocalModelSummary() {
      if (localModel.configuredPath) {
        return 'Configured local model: ' + (localModel.configuredInstalled ? 'available (' : 'not found (') + localModel.configuredPath + ')';
      }
      return 'Local model: ' + (localModel.installed ? 'available (' : 'not found (') + localModel.defaultPath + ')';
    }

    function readConfig() {
      rememberProviderModelValue();
      const postRefine = byId('postRefineEnabled').checked
        ? byId('postRefine').value
        : 'off';
      const provider = byId('embeddingProvider').value;
      return {
        enabled: byId('enabled').checked,
        agents: ['codex', 'claude'].filter((agent) => byId('agent' + agent.charAt(0).toUpperCase() + agent.slice(1)).checked),
        packs: Array.from(selected),
        policyRoot: byId('policyRoot').value.trim() || undefined,
        autoInstall: byId('autoInstall').checked,
        gitCommitStyle: byId('gitCommitStyle').value,
        embeddingProvider: readEmbeddingField('embeddingProvider'),
        embeddingBaseUrl: readEmbeddingField('embeddingBaseUrl'),
        embeddingApiKey: readEmbeddingField('embeddingApiKey'),
        embeddingModel: provider === 'local'
          ? draftEmbeddingModel || undefined
          : readEmbeddingField('embeddingModel'),
        embeddingLocalModel: provider === 'local'
          ? draftEmbeddingLocalModel || undefined
          : draftEmbeddingLocalModel || undefined,
        embeddingTimeout: readEmbeddingField('embeddingTimeout'),
        postRefine,
        postRefinePacks: ${JSON.stringify(DEFAULT_POST_REFINE_PACKS)},
        verifyTarget: byId('verifyTarget').value.trim() || undefined
      };
    }

    function readEmbeddingField(id) {
      const field = byId(id);
      const value = field.value.trim();
      if (!value) {
        return undefined;
      }
      if (
        field.dataset.configured !== 'true' &&
        field.dataset.userEdited !== 'true' &&
        value === (field.dataset.envValue || '')
      ) {
        return undefined;
      }
      return value;
    }

    let saveTimer;
    function scheduleSave() {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        vscode.postMessage({ type: 'save', config: readConfig() });
      }, 350);
    }

  </script>
</body>
</html>`;
  }
}

class PolicyStatusBar implements vscode.Disposable {
  private readonly item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);

  constructor(private readonly workspace: PolicyWorkspace) {
    this.item.command = COMMANDS.showStatus;
  }

  refresh(): void {
    const config = this.workspace.readConfig();
    this.item.text = config.enabled ? 'AI Policy Runtime: On' : 'AI Policy Runtime: Off';
    this.item.tooltip = config.enabled
      ? `Agents: ${config.agents.join(', ') || '(none)'}; packs: ${config.packs.join(', ') || '(none)'}; post-refine: ${config.postRefine}`
      : 'AI Policy Runtime is disabled';
    this.item.show();
  }

  dispose(): void {
    this.item.dispose();
  }
}

async function setEnabled(
  workspace: PolicyWorkspace,
  status: PolicyStatusBar,
  enabled: boolean
): Promise<void> {
  const before = workspace.readConfig();
  await workspace.updateSetting('enabled', enabled);
  await workspace.syncProjectConfig();
  status.refresh();
  vscode.window.showInformationMessage(
    `AI Policy Runtime is ${enabled ? 'enabled' : 'disabled'} for this workspace.`
  );
  const after = workspace.readConfig();
  maybeShowCodexTrustHint(workspace, before, after);
  maybeShowClaudeRestartHint(before, after);
}

async function enablePostRefine(
  workspace: PolicyWorkspace,
  status: PolicyStatusBar,
  panel: PolicyConfigViewProvider
): Promise<void> {
  const before = workspace.readConfig();
  await Promise.all([
    workspace.updateSetting('enabled', true),
    workspace.updateSetting('postRefine', 'standard'),
    workspace.updateSetting('postRefinePacks', DEFAULT_POST_REFINE_PACKS)
  ]);
  await workspace.syncProjectConfig();
  status.refresh();
  panel.refresh();
  vscode.window.showInformationMessage('AI Policy Runtime post-task refinement is enabled for this workspace.');
  const after = workspace.readConfig();
  maybeShowCodexTrustHint(workspace, before, after);
  maybeShowClaudeRestartHint(before, after);
}

function maybeShowCodexTrustHint(
  workspace: PolicyWorkspace,
  before: PolicyConfig,
  after: PolicyConfig
): void {
  const codexWasActive = before.enabled && before.agents.includes('codex');
  const codexIsActive = after.enabled && after.agents.includes('codex');
  if (!codexIsActive || codexWasActive) {
    return;
  }
  const validate = 'Validate Runtime';
  vscode.window
    .showInformationMessage(
      'AI Policy Runtime configured Codex hooks for this workspace. In Codex Settings, open Hooks and approve the project hooks when prompted.',
      validate
    )
    .then((choice) => {
      if (choice === validate) {
        void validateRuntime(workspace);
      }
    });
}

function maybeShowClaudeRestartHint(before: PolicyConfig, after: PolicyConfig): void {
  const claudeWasActive = before.enabled && before.agents.includes('claude');
  const claudeIsActive = after.enabled && after.agents.includes('claude');
  if (!claudeIsActive || claudeWasActive) {
    return;
  }
  vscode.window.showInformationMessage(
    'AI Policy Runtime configured Claude Code plugin settings for this workspace. Restart or reload the Claude Code session if it was already open.'
  );
}

async function configurePacks(workspace: PolicyWorkspace): Promise<void> {
  const selected = new Set(workspace.readConfig().packs);
  const picks = await vscode.window.showQuickPick(
    KNOWN_PACKS.map((pack) => ({
      ...pack,
      picked: selected.has(pack.label)
    })),
    {
      canPickMany: true,
      title: 'Select AI Policy Runtime packs'
    }
  );
  if (!picks) {
    return;
  }

  await workspace.updateSetting('packs', picks.map((item) => item.label));
  await workspace.syncProjectConfig();
  vscode.window.showInformationMessage(`AI Policy Runtime packs updated: ${picks.length || 'none'}.`);
}

async function showStatus(workspace: PolicyWorkspace): Promise<void> {
  const paths = workspace.pathsOrWarn();
  if (!paths) {
    return;
  }

  const config = workspace.readConfig();
  const hookConfig = projectConfig(config);
  const environmentConfig = readEmbeddingEnvironmentConfig();
  const effectiveEmbeddingValue = (key: keyof EmbeddingEnvironmentConfig, fallback: string) =>
    hookConfig[key] || environmentConfig[key] || fallback;
  const promptExists = await exists(paths.effectivePrompt);
  const document = await vscode.workspace.openTextDocument({
    language: 'plaintext',
    content: [
      `Enabled: ${config.enabled}`,
      `Agents: ${config.agents.length ? config.agents.join(', ') : '(none)'}`,
      `Packs: ${config.packs.length ? config.packs.join(', ') : '(none)'}`,
      `Policy root: ${paths.policyRoot}`,
      `Git commit style: ${config.gitCommitStyle}`,
      `Embedding provider: ${effectiveEmbeddingValue('embeddingProvider', '(auto)')}`,
      `Embedding base URL: ${effectiveEmbeddingValue('embeddingBaseUrl', '(default)')}`,
      `Embedding model: ${effectiveEmbeddingValue('embeddingModel', '(default)')}`,
      `Post-refinement: ${config.postRefine}`,
      `Post-refinement packs: ${config.postRefinePacks.join(', ') || '(none)'}`,
      `Verify target: ${config.verifyTarget || '(not configured)'}`,
      `Project config: ${paths.config}`,
      `Latest Effective Rules: ${promptExists ? paths.effectivePrompt : '(not generated yet)'}`
    ].join('\n')
  });
  await vscode.window.showTextDocument(document);
}

async function showEffectiveRules(workspace: PolicyWorkspace): Promise<void> {
  const paths = workspace.pathsOrWarn();
  if (!paths) {
    return;
  }
  if (!(await exists(paths.effectivePrompt))) {
    vscode.window.showWarningMessage('No Effective Rules have been generated for this workspace yet.');
    return;
  }

  const document = await vscode.workspace.openTextDocument(paths.effectivePrompt);
  await vscode.window.showTextDocument(document);
}

async function validateRuntime(workspace: PolicyWorkspace): Promise<void> {
  const paths = workspace.pathsOrWarn();
  if (!paths) {
    return;
  }

  await workspace.syncProjectConfig();
  const config = workspace.readConfig();
  const missingRuntime = await missingRuntimePaths(paths.policyRoot);
  const configExists = await exists(paths.config);
  const codexHooksExists = await exists(paths.codexHooks);
  const codexConfigExists = await exists(paths.codexConfig);
  const codexConfigText = codexConfigExists ? await fs.readFile(paths.codexConfig, 'utf8') : '';
  const codexHooks = codexHooksExists ? await readJsonObject(paths.codexHooks) : {};
  const hooks = objectValue(codexHooks, 'hooks');
  const codexIsActive = config.enabled && config.agents.includes('codex');
  const codexFeatureEnabled = tomlBool(codexConfigText, 'features', 'hooks');
  const userPromptConfigured = eventHasAiPolicyHook(hooks, 'UserPromptSubmit');
  const stopConfigured = eventHasAiPolicyHook(hooks, 'Stop');
  const claudeIsActive = config.enabled && config.agents.includes('claude');
  const claudeSettingsExists = await exists(paths.claudeSettings);
  const claudeSettings = claudeSettingsExists ? await readJsonObject(paths.claudeSettings) : {};
  const claudeMarketplaceRegistered = claudeMarketplaceIsRegistered(claudeSettings, paths.policyRoot);
  const claudePluginEnabled = claudePluginIsEnabled(claudeSettings);
  const hookState = (await exists(paths.hookState)) ? await readJsonObject(paths.hookState) : {};
  const latestPrompt = optionalJsonString(hookState.prompt);
  const latestGenerated = hookState.effective_rules_generated === true;
  const latestError = optionalJsonString(hookState.hook_error);

  const problems = [
    ...missingRuntime.map((item) => `Missing runtime file: ${item}`),
    ...(!configExists ? [`Missing workspace config: ${paths.config}`] : []),
    ...(codexIsActive && !codexHooksExists ? [`Missing Codex hooks config: ${paths.codexHooks}`] : []),
    ...(codexIsActive && !codexConfigExists ? [`Missing Codex config: ${paths.codexConfig}`] : []),
    ...(codexIsActive && codexConfigExists && !codexFeatureEnabled ? ['Codex project hooks feature is not enabled.'] : []),
    ...(codexIsActive && codexHooksExists && !userPromptConfigured ? ['Codex UserPromptSubmit hook is not configured.'] : []),
    ...(codexIsActive && codexHooksExists && !stopConfigured ? ['Codex Stop hook is not configured.'] : []),
    ...(claudeIsActive && !claudeSettingsExists ? [`Missing Claude settings: ${paths.claudeSettings}`] : []),
    ...(claudeIsActive && claudeSettingsExists && !claudeMarketplaceRegistered ? ['Claude plugin marketplace is not registered.'] : []),
    ...(claudeIsActive && claudeSettingsExists && !claudePluginEnabled ? ['Claude plugin is not enabled.'] : []),
    ...(latestError ? [`Latest hook error: ${latestError}`] : [])
  ];
  const ready = problems.length === 0;

  const content = [
    ready ? 'AI Policy Runtime validation passed.' : 'AI Policy Runtime validation found issues.',
    '',
    'Workspace',
    `- Root: ${paths.root}`,
    `- Policy config: ${configExists ? paths.config : 'missing'}`,
    '',
    'Runtime',
    `- Policy root: ${paths.policyRoot}`,
    `- Bundled files: ${missingRuntime.length ? 'missing files' : 'OK'}`,
    '',
    'Codex Hooks',
    `- Config: ${codexConfigExists ? paths.codexConfig : 'missing'}`,
    `- Hooks file: ${codexHooksExists ? paths.codexHooks : 'missing'}`,
    `- [features].hooks: ${codexFeatureEnabled ? 'true' : 'false'}`,
    `- UserPromptSubmit: ${userPromptConfigured ? 'configured' : 'missing'}`,
    `- Stop: ${stopConfigured ? 'configured' : 'missing'}`,
    '',
    'Claude Code Plugin',
    `- Settings: ${claudeSettingsExists ? paths.claudeSettings : 'missing'}`,
    `- Marketplace: ${claudeMarketplaceRegistered ? 'registered' : 'missing'}`,
    `- Plugin enabled: ${claudePluginEnabled ? 'true' : 'false'}`,
    '',
    'Latest Hook State',
    `- State file: ${(await exists(paths.hookState)) ? paths.hookState : 'not generated yet'}`,
    `- Prompt: ${latestPrompt ? trimForReport(latestPrompt) : '(none yet)'}`,
    `- Effective Rules generated: ${latestGenerated ? 'yes' : 'no'}`,
    `- Hook error: ${latestError || '(none)'}`,
    '',
    ready
      ? 'Next step: use Codex in this workspace. If Codex asks about project hooks, approve the AI Policy Runtime hooks.'
      : `Issues:\n${problems.map((item) => `- ${item}`).join('\n')}`
  ].join('\n');

  const document = await vscode.workspace.openTextDocument({ language: 'plaintext', content });
  await vscode.window.showTextDocument(document);
  if (ready) {
    vscode.window.showInformationMessage('AI Policy Runtime validation passed.');
  } else {
    vscode.window.showErrorMessage('AI Policy Runtime validation found issues. Opened details.');
  }
}

async function syncCodexAgentHooks(paths: PolicyPaths, config: PolicyConfig): Promise<void> {
  const enabled = config.enabled && config.agents.includes('codex');
  if (!enabled && !(await exists(paths.codexHooks)) && !(await exists(paths.codexConfig))) {
    return;
  }
  await Promise.all([
    configureCodexHooks(paths, config, enabled),
    configureCodexConfig(paths.codexConfig, enabled)
  ]);
}

async function configureCodexHooks(paths: PolicyPaths, config: PolicyConfig, enabled: boolean): Promise<void> {
  await fs.mkdir(path.dirname(paths.codexHooks), { recursive: true });
  const hooksConfig = await readJsonObject(paths.codexHooks);
  const hooks = objectValue(hooksConfig, 'hooks');
  hooksConfig.hooks = hooks;

  const policyRoot = paths.policyRoot;
  const userPromptHook = codexHookEntry(policyRoot, 'codex-user-prompt-submit', 'Generating Effective Rules');
  const stopHook = codexHookEntry(policyRoot, 'codex-stop-refinement', 'Checking post-task refinement');

  if (enabled) {
    upsertEventHook(hooks, 'UserPromptSubmit', userPromptHook);
    upsertEventHook(hooks, 'Stop', stopHook);
  } else {
    removeEventHook(hooks, 'UserPromptSubmit');
    removeEventHook(hooks, 'Stop');
  }

  await fs.writeFile(paths.codexHooks, `${JSON.stringify(hooksConfig, null, 2)}\n`, 'utf8');
}

function codexHookEntry(policyRoot: string, hookName: string, statusMessage: string): Record<string, unknown> {
  const hookRunner = path.join(policyRoot, 'bin', 'ai-policy-hook.js');
  return {
    hooks: [
      {
        type: 'command',
        command: shellCommand(process.env.AI_POLICY_NODE || 'node', hookRunner, hookName),
        timeout: 30,
        statusMessage
      }
    ]
  };
}

function upsertEventHook(
  hooks: Record<string, unknown>,
  event: 'UserPromptSubmit' | 'Stop',
  entry: Record<string, unknown>
): void {
  const entries = hookEventEntries(hooks, event);
  removeAiPolicyEntries(entries);
  entries.push(entry);
  hooks[event] = entries;
}

function removeEventHook(hooks: Record<string, unknown>, event: 'UserPromptSubmit' | 'Stop'): void {
  const value = hooks[event];
  if (!Array.isArray(value)) {
    return;
  }
  removeAiPolicyEntries(value);
  if (!value.length) {
    delete hooks[event];
  }
}

function hookEventEntries(hooks: Record<string, unknown>, event: 'UserPromptSubmit' | 'Stop'): unknown[] {
  const value = hooks[event];
  return Array.isArray(value) ? value : [];
}

function removeAiPolicyEntries(entries: unknown[]): void {
  const kept = entries.filter((entry) => !isAiPolicyHookEntry(entry));
  entries.splice(0, entries.length, ...kept);
}

function isAiPolicyHookEntry(entry: unknown): boolean {
  if (!isRecord(entry)) {
    return false;
  }
  const hooks = entry.hooks;
  if (!Array.isArray(hooks)) {
    return false;
  }
  return hooks.some((item) => isRecord(item) && String(item.command ?? '').includes('ai-policy-hook.js'));
}

async function configureCodexConfig(filePath: string, enabled: boolean): Promise<void> {
  const original = (await exists(filePath)) ? await fs.readFile(filePath, 'utf8') : '';
  const updated = setTomlBool(original, 'features', 'hooks', enabled, ['codex_hooks']);
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, updated, 'utf8');
}

async function syncClaudeAgentHooks(paths: PolicyPaths, config: PolicyConfig): Promise<void> {
  const enabled = config.enabled && config.agents.includes('claude');
  if (!enabled && !(await exists(paths.claudeSettings))) {
    return;
  }

  const settings = await readJsonObject(paths.claudeSettings);
  const marketplaces = objectValue(settings, 'extraKnownMarketplaces');
  marketplaces[CLAUDE_MARKETPLACE_NAME] = {
    source: {
      source: 'directory',
      path: paths.policyRoot
    }
  };
  settings.extraKnownMarketplaces = marketplaces;

  const enabledPlugins = objectValue(settings, 'enabledPlugins');
  enabledPlugins[CLAUDE_PLUGIN_ID] = enabled;
  settings.enabledPlugins = enabledPlugins;

  await fs.mkdir(path.dirname(paths.claudeSettings), { recursive: true });
  await fs.writeFile(paths.claudeSettings, `${JSON.stringify(settings, null, 2)}\n`, 'utf8');
}

async function missingRuntimePaths(policyRoot: string): Promise<string[]> {
  const missing = [];
  for (const relativePath of REQUIRED_RUNTIME_PATHS) {
    const absolutePath = path.join(policyRoot, relativePath);
    if (!(await exists(absolutePath))) {
      missing.push(absolutePath);
    }
  }
  return missing;
}

function eventHasAiPolicyHook(hooks: Record<string, unknown>, event: 'UserPromptSubmit' | 'Stop'): boolean {
  return hookEventEntries(hooks, event).some((entry) => isAiPolicyHookEntry(entry));
}

function claudeMarketplaceIsRegistered(settings: Record<string, unknown>, policyRoot: string): boolean {
  const marketplaces = asRecord(settings.extraKnownMarketplaces);
  const marketplace = asRecord(marketplaces?.[CLAUDE_MARKETPLACE_NAME]);
  const source = asRecord(marketplace?.source);
  return source?.source === 'directory' && source.path === policyRoot;
}

function claudePluginIsEnabled(settings: Record<string, unknown>): boolean {
  const enabledPlugins = asRecord(settings.enabledPlugins);
  return enabledPlugins?.[CLAUDE_PLUGIN_ID] === true;
}

function optionalJsonString(value: unknown): string | undefined {
  if (typeof value !== 'string') {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed || undefined;
}

function trimForReport(value: string): string {
  const collapsed = value.replace(/\s+/g, ' ').trim();
  return collapsed.length <= 160 ? collapsed : `${collapsed.slice(0, 157)}...`;
}

function tomlBool(text: string, section: string, key: string): boolean {
  let inSection = false;
  for (const line of text.split(/\r?\n/)) {
    const stripped = line.trim();
    if (!stripped || stripped.startsWith('#')) {
      continue;
    }
    if (stripped.startsWith('[') && stripped.endsWith(']')) {
      inSection = stripped === `[${section}]`;
      continue;
    }
    if (inSection && stripped.startsWith(`${key} `) && stripped.includes('=')) {
      return stripped.split('=', 2)[1].split('#', 1)[0].trim().toLowerCase() === 'true';
    }
  }
  return false;
}

async function readJsonObject(filePath: string): Promise<Record<string, unknown>> {
  if (!(await exists(filePath))) {
    return {};
  }
  const parsed: unknown = JSON.parse(await fs.readFile(filePath, 'utf8'));
  return isRecord(parsed) ? parsed : {};
}

function objectValue(record: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = record[key];
  return isRecord(value) ? value : {};
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return isRecord(value) ? value : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function shellCommand(command: string, script: string, hookName: string): string {
  return [command, script, hookName].map(quoteShell).join(' ');
}

function quoteShell(value: string): string {
  const escaped = value.replace(/"/g, '\\"');
  return /\s|\\|:/.test(escaped) ? `"${escaped}"` : escaped;
}

function setTomlBool(
  text: string,
  section: string,
  key: string,
  value: boolean,
  removeKeys: string[] = []
): string {
  const lines = text.split(/\r?\n/);
  const target = `${key} = ${value ? 'true' : 'false'}`;
  const sectionHeader = `[${section}]`;
  let inSection = false;
  let sectionFound = false;
  let keyWritten = false;
  const output: string[] = [];

  for (const [index, line] of lines.entries()) {
    if (!line && index === lines.length - 1) {
      continue;
    }
    const stripped = line.trim();
    if (stripped.startsWith('[') && stripped.endsWith(']')) {
      if (inSection && !keyWritten) {
        output.push(target);
        keyWritten = true;
      }
      inSection = stripped === sectionHeader;
      sectionFound = sectionFound || inSection;
      output.push(line);
      continue;
    }
    if (inSection && removeKeys.some((removeKey) => stripped.startsWith(`${removeKey} `) && stripped.includes('='))) {
      continue;
    }
    if (inSection && stripped.startsWith(`${key} `) && stripped.includes('=')) {
      output.push(target);
      keyWritten = true;
      continue;
    }
    output.push(line);
  }

  if (!sectionFound) {
    if (output.length && output[output.length - 1].trim()) {
      output.push('');
    }
    output.push(sectionHeader, target);
  } else if (inSection && !keyWritten) {
    output.push(target);
  }

  return `${output.join('\n').trimEnd()}\n`;
}

function cleanOptionalString(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

function readEmbeddingEnvironmentConfig(): EmbeddingEnvironmentConfig {
  return {
    embeddingProvider: normalizeEmbeddingProvider(process.env.AI_POLICY_EMBEDDING_PROVIDER ?? ''),
    embeddingBaseUrl: cleanOptionalString(process.env.AI_POLICY_EMBEDDING_BASE_URL ?? ''),
    embeddingApiKey: cleanOptionalString(
      process.env.AI_POLICY_EMBEDDING_API_KEY ?? process.env.OPENAI_API_KEY ?? ''
    ),
    embeddingModel: cleanOptionalString(process.env.AI_POLICY_EMBEDDING_MODEL ?? ''),
    embeddingTimeout: cleanOptionalString(process.env.AI_POLICY_EMBEDDING_TIMEOUT ?? '')
  };
}

function readEmbeddingAvailability(
  config: PolicyConfig,
  workspaceRoot: string | undefined,
  defaultPolicyRoot: string
): EmbeddingAvailabilityState {
  const remoteConfigured = Boolean(
    config.embeddingBaseUrl ||
      config.embeddingApiKey ||
      process.env.AI_POLICY_EMBEDDING_BASE_URL?.trim() ||
      process.env.AI_POLICY_EMBEDDING_API_KEY?.trim() ||
      process.env.OPENAI_API_KEY?.trim()
  );
  return {
    remoteConfigured,
    remoteSummary: remoteConfigured
      ? (config.embeddingBaseUrl ||
          cleanOptionalString(process.env.AI_POLICY_EMBEDDING_BASE_URL ?? '') ||
          'credentials available')
      : 'not configured',
    local: readLocalModelState(config, workspaceRoot, defaultPolicyRoot)
  };
}

function readLocalModelState(
  config: PolicyConfig,
  workspaceRoot: string | undefined,
  defaultPolicyRoot: string
): LocalModelState {
  const defaultPath = path.join(
    resolvePolicyRoot(config, workspaceRoot, defaultPolicyRoot),
    'models',
    'paraphrase-multilingual-MiniLM-L12-v2'
  );
  const configuredPath = config.embeddingLocalModel
    ? resolveWorkspacePath(config.embeddingLocalModel, workspaceRoot)
    : undefined;
  const configuredInstalled = configuredPath ? existsSync(configuredPath) : undefined;
  const installed = existsSync(defaultPath);
  return {
    defaultPath,
    installed,
    configuredPath,
    configuredInstalled,
    available: configuredInstalled ?? installed
  };
}

function resolveWorkspacePath(value: string, workspaceRoot: string | undefined): string {
  if (path.isAbsolute(value) || !workspaceRoot) {
    return path.normalize(value);
  }
  return path.join(workspaceRoot, value);
}

function resolvePolicyRoot(
  config: PolicyConfig,
  workspaceRoot: string | undefined,
  defaultPolicyRoot: string
): string {
  if (config.policyRoot) {
    return path.isAbsolute(config.policyRoot)
      ? config.policyRoot
      : path.resolve(workspaceRoot ?? process.cwd(), config.policyRoot);
  }
  return defaultPolicyRoot;
}

function normalizeEmbeddingProvider(value: string): string | undefined {
  const provider = cleanOptionalString(value)?.toLowerCase().replace('_', '-');
  if (!provider) {
    return undefined;
  }
  return provider;
}

async function exists(filePath: string): Promise<boolean> {
  try {
    await fs.stat(filePath);
    return true;
  } catch {
    return false;
  }
}

function normalizeConfig(config: PolicyConfig): PolicyConfig {
  return {
    enabled: Boolean(config.enabled),
    agents: normalizeAgents(config.agents),
    packs: Array.isArray(config.packs) ? config.packs.filter(Boolean) : DEFAULT_PACKS,
    policyRoot: cleanOptionalString(config.policyRoot ?? ''),
    autoInstall: Boolean(config.autoInstall),
    embeddingProvider: normalizeEmbeddingProvider(config.embeddingProvider ?? ''),
    embeddingBaseUrl: cleanOptionalString(config.embeddingBaseUrl ?? ''),
    embeddingApiKey: cleanOptionalString(config.embeddingApiKey ?? ''),
    embeddingModel: cleanOptionalString(config.embeddingModel ?? ''),
    embeddingLocalModel: cleanOptionalString(config.embeddingLocalModel ?? ''),
    embeddingTimeout: cleanOptionalString(config.embeddingTimeout ?? ''),
    gitCommitStyle: normalizeGitCommitStyle(config.gitCommitStyle ?? 'auto'),
    postRefine: normalizePostRefineMode(config.postRefine ?? 'off'),
    postRefinePacks: Array.isArray(config.postRefinePacks)
      ? config.postRefinePacks.filter(Boolean)
      : DEFAULT_POST_REFINE_PACKS,
    verifyTarget: cleanOptionalString(config.verifyTarget ?? '')
  };
}

function projectConfig(config: PolicyConfig): Omit<PolicyConfig, 'embeddingLocalModel' | 'gitCommitStyle'> & { git: { commitStyle: GitCommitStyle } } {
  const { embeddingLocalModel, ...project } = config;
  if (project.embeddingProvider === 'local') {
    project.embeddingModel = embeddingLocalModel;
    project.embeddingBaseUrl = undefined;
    project.embeddingApiKey = undefined;
    project.embeddingTimeout = undefined;
  }
  const { gitCommitStyle, ...projectConfig } = project;
  return {
    ...projectConfig,
    git: {
      commitStyle: gitCommitStyle
    }
  };
}

function normalizeAgents(value: unknown): AgentTarget[] {
  if (!Array.isArray(value)) {
    return DEFAULT_AGENTS;
  }
  const agents = value.filter((item): item is AgentTarget => item === 'codex' || item === 'claude');
  return agents.length ? Array.from(new Set(agents)) : DEFAULT_AGENTS;
}

function normalizePostRefineMode(value: string): PolicyConfig['postRefine'] {
  if (value === 'light' || value === 'standard' || value === 'strict') {
    return value;
  }
  return 'off';
}

function normalizeGitCommitStyle(value: string): GitCommitStyle {
  const normalized = cleanOptionalString(value)?.toLowerCase().replace('_', '-');
  if (normalized === 'conventional' || normalized === 'imperative') {
    return normalized;
  }
  return 'auto';
}

function nonceValue(): string {
  const source = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  return Array.from({ length: 32 }, () => source[Math.floor(Math.random() * source.length)]).join('');
}
