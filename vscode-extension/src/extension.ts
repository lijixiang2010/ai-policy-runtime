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
  postRefine: 'off' | 'light' | 'standard' | 'strict';
  postRefinePacks: string[];
  verifyTarget?: string;
};

type AgentTarget = 'codex' | 'claude';

type PolicyPaths = {
  root: string;
  config: string;
  codexHooks: string;
  codexConfig: string;
  effectivePrompt: string;
};

type EmbeddingEnvironmentConfig = Pick<
  PolicyConfig,
  'embeddingProvider' | 'embeddingBaseUrl' | 'embeddingApiKey' | 'embeddingModel' | 'embeddingTimeout'
>;

type LocalModelState = {
  defaultPath: string;
  installed: boolean;
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
const EFFECTIVE_PROMPT_FILE = path.join('.policy', 'current', 'effective-prompt.md');
const DEFAULT_AGENTS: AgentTarget[] = ['codex'];
const DEFAULT_PACKS = ['cpp.safe_generation'];
const DEFAULT_POST_REFINE_PACKS = ['cpp.production_refinement'];

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
  const workspace = new PolicyWorkspace();
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
        void workspace.syncProjectConfig().then(() => status.refresh());
      }
    })
  );

  void workspace.syncProjectConfig().then(() => status.refresh());
}

export function deactivate(): void {
  // VS Code disposes registered subscriptions automatically.
}

class PolicyWorkspace {
  /** Read VS Code settings and write the project-local hook config. */
  async syncProjectConfig(): Promise<void> {
    const paths = this.pathsOrWarn();
    if (!paths) {
      return;
    }

    const config = this.readConfig();
    await fs.mkdir(path.dirname(paths.config), { recursive: true });
    await fs.writeFile(paths.config, `${JSON.stringify(projectConfig(config), null, 2)}\n`, 'utf8');
    await syncCodexAgentHooks(paths, config);
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
      config: path.join(root, POLICY_CONFIG_FILE),
      codexHooks: path.join(root, CODEX_HOOKS_FILE),
      codexConfig: path.join(root, CODEX_CONFIG_FILE),
      effectivePrompt: path.join(root, EFFECTIVE_PROMPT_FILE)
    };
  }

  rootPath(): string | undefined {
    return this.workspaceRoot();
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
      await this.workspace.saveConfig(normalizeConfig(message.config));
      this.status.refresh();
      await this.view?.webview.postMessage({ type: 'saved' });
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
      embeddingAvailability: readEmbeddingAvailability(config, this.workspace.rootPath()),
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
    <input id="policyRoot" type="text" placeholder="Leave empty: resolved from Claude/Codex hook location">
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
    byId('enabled').checked = Boolean(state.config.enabled);
    byId('autoInstall').checked = Boolean(state.config.autoInstall);
    byId('agentCodex').checked = agents.has('codex');
    byId('agentClaude').checked = agents.has('claude');
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
        ? state.config.embeddingLocalModel || ''
        : state.config.embeddingModel || '';
      const environment = provider === 'local' ? '' : envConfig.embeddingModel || '';
      field.value = configured || environment;
      field.dataset.envValue = environment;
      field.dataset.configured = configured ? 'true' : 'false';
      field.dataset.userEdited = 'false';
      field.addEventListener('input', () => { field.dataset.userEdited = 'true'; });
      field.addEventListener('change', () => { field.dataset.userEdited = 'true'; });
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
      if (provider.value !== provider.dataset.previousProvider) {
        resetProviderScopedEmbeddingFields();
        provider.dataset.previousProvider = provider.value;
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
      byId('embeddingModelLabel').textContent = isLocal ? 'Override local model' : 'Embedding model';
      byId('embeddingModel').placeholder = isLocal
        ? 'Leave empty to use the default local model'
        : 'text-embedding-3-small';
      byId('localModelStatus').textContent = localModel.installed
        ? 'Using default local model: ' + localModel.defaultPath
        : 'Default local model not found: ' + localModel.defaultPath;
      renderAutoEmbeddingStatus();
    }

    function renderAutoEmbeddingStatus() {
      const status = byId('autoEmbeddingStatus');
      const lines = [
        'OpenAI-compatible: ' + (availability.remoteConfigured ? 'configured (' + availability.remoteSummary + ')' : 'not configured'),
        'Local model: ' + (localModel.installed ? 'available (' + localModel.defaultPath + ')' : 'not found (' + localModel.defaultPath + ')')
      ];
      if (availability.remoteConfigured) {
        lines.push('Auto will use OpenAI-compatible embeddings.');
        status.classList.remove('warning');
      } else if (localModel.installed) {
        lines.push('Auto will use the default local sentence-transformers model.');
        status.classList.remove('warning');
      } else {
        lines.push('Configure an OpenAI-compatible endpoint or install the default local model before using semantic analysis.');
        status.classList.add('warning');
      }
      status.textContent = lines.join('\\n');
    }

    function resetProviderScopedEmbeddingFields() {
      for (const id of ['embeddingBaseUrl', 'embeddingApiKey', 'embeddingModel', 'embeddingTimeout']) {
        const field = byId(id);
        field.value = '';
        field.dataset.configured = 'false';
        field.dataset.userEdited = 'true';
      }
    }

    function readConfig() {
      const postRefine = byId('postRefineEnabled').checked
        ? byId('postRefine').value
        : 'off';
      return {
        enabled: byId('enabled').checked,
        agents: ['codex', 'claude'].filter((agent) => byId('agent' + agent.charAt(0).toUpperCase() + agent.slice(1)).checked),
        packs: Array.from(selected),
        policyRoot: byId('policyRoot').value.trim() || undefined,
        autoInstall: byId('autoInstall').checked,
        embeddingProvider: readEmbeddingField('embeddingProvider'),
        embeddingBaseUrl: readEmbeddingField('embeddingBaseUrl'),
        embeddingApiKey: readEmbeddingField('embeddingApiKey'),
        embeddingModel: byId('embeddingProvider').value === 'local'
          ? state.config.embeddingModel || undefined
          : readEmbeddingField('embeddingModel'),
        embeddingLocalModel: byId('embeddingProvider').value === 'local'
          ? readEmbeddingField('embeddingModel')
          : state.config.embeddingLocalModel || undefined,
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
  await workspace.updateSetting('enabled', enabled);
  await workspace.syncProjectConfig();
  status.refresh();
  vscode.window.showInformationMessage(
    `AI Policy Runtime is ${enabled ? 'enabled' : 'disabled'} for this workspace.`
  );
}

async function enablePostRefine(
  workspace: PolicyWorkspace,
  status: PolicyStatusBar,
  panel: PolicyConfigViewProvider
): Promise<void> {
  await Promise.all([
    workspace.updateSetting('enabled', true),
    workspace.updateSetting('postRefine', 'standard'),
    workspace.updateSetting('postRefinePacks', DEFAULT_POST_REFINE_PACKS)
  ]);
  await workspace.syncProjectConfig();
  status.refresh();
  panel.refresh();
  vscode.window.showInformationMessage('AI Policy Runtime post-task refinement is enabled for this workspace.');
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
      `Policy root: ${config.policyRoot || '(resolved from Claude/Codex hook location)'}`,
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
  const message = (await exists(paths.config))
    ? `AI Policy Runtime config is ready: ${paths.config}`
    : 'AI Policy Runtime config was not created.';
  vscode.window.showInformationMessage(message);
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

  const policyRoot = resolvePolicyRoot(config, paths.root);
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
  const updated = setTomlBool(original, 'features', 'codex_hooks', enabled);
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, updated, 'utf8');
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

function setTomlBool(text: string, section: string, key: string, value: boolean): string {
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
  workspaceRoot: string | undefined
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
    local: readLocalModelState(config, workspaceRoot)
  };
}

function readLocalModelState(config: PolicyConfig, workspaceRoot: string | undefined): LocalModelState {
  const defaultPath = path.join(
    resolvePolicyRoot(config, workspaceRoot),
    'models',
    'paraphrase-multilingual-MiniLM-L12-v2'
  );
  return {
    defaultPath,
    installed: existsSync(defaultPath)
  };
}

function resolvePolicyRoot(config: PolicyConfig, workspaceRoot: string | undefined): string {
  if (config.policyRoot) {
    return path.isAbsolute(config.policyRoot)
      ? config.policyRoot
      : path.resolve(workspaceRoot ?? process.cwd(), config.policyRoot);
  }
  return workspaceRoot ?? process.cwd();
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
    postRefine: normalizePostRefineMode(config.postRefine ?? 'off'),
    postRefinePacks: Array.isArray(config.postRefinePacks)
      ? config.postRefinePacks.filter(Boolean)
      : DEFAULT_POST_REFINE_PACKS,
    verifyTarget: cleanOptionalString(config.verifyTarget ?? '')
  };
}

function projectConfig(config: PolicyConfig): Omit<PolicyConfig, 'embeddingLocalModel'> {
  const { embeddingLocalModel, ...project } = config;
  if (project.embeddingProvider === 'local') {
    project.embeddingModel = embeddingLocalModel;
    project.embeddingBaseUrl = undefined;
    project.embeddingApiKey = undefined;
    project.embeddingTimeout = undefined;
  }
  return project;
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

function nonceValue(): string {
  const source = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  return Array.from({ length: 32 }, () => source[Math.floor(Math.random() * source.length)]).join('');
}
