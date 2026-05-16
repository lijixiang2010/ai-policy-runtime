import * as fs from 'fs/promises';
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
  embeddingTimeout?: string;
  postRefine: 'off' | 'light' | 'standard' | 'strict';
  postRefinePacks: string[];
  verifyTarget?: string;
};

type AgentTarget = 'codex' | 'claude';

type PolicyPaths = {
  root: string;
  config: string;
  effectivePrompt: string;
};

type PackItem = vscode.QuickPickItem & {
  label: string;
  category: string;
  tags: string[];
};

const CONFIG_SECTION = 'aiPolicy';
const POLICY_CONFIG_FILE = path.join('.policy', 'config.json');
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
  prepareClaudeDesktop: 'aiPolicy.prepareClaudeDesktop',
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
    vscode.commands.registerCommand(COMMANDS.prepareClaudeDesktop, () => prepareClaudeDesktop(workspace, status, panel)),
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

    await fs.mkdir(path.dirname(paths.config), { recursive: true });
    await fs.writeFile(paths.config, `${JSON.stringify(this.readConfig(), null, 2)}\n`, 'utf8');
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
      embeddingProvider: cleanOptionalString(config.get<string>('embeddingProvider', '')),
      embeddingBaseUrl: cleanOptionalString(config.get<string>('embeddingBaseUrl', '')),
      embeddingApiKey: cleanOptionalString(config.get<string>('embeddingApiKey', '')),
      embeddingModel: cleanOptionalString(config.get<string>('embeddingModel', '')),
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
      effectivePrompt: path.join(root, EFFECTIVE_PROMPT_FILE)
    };
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
      this.render();
      vscode.window.showInformationMessage('AI Policy Runtime configuration saved.');
      return;
    }
    if (message.type === 'showEffectiveRules') {
      await showEffectiveRules(this.workspace);
      return;
    }
    if (message.type === 'prepareClaudeDesktop') {
      await prepareClaudeDesktop(this.workspace, this.status, this);
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
    .actions {
      display: grid;
      gap: 8px;
      padding-top: 16px;
    }
    button {
      width: 100%;
      border: 0;
      padding: 8px 10px;
      color: var(--accent-text);
      background: var(--accent);
      font: inherit;
      cursor: pointer;
    }
    button.secondary {
      color: var(--vscode-button-secondaryForeground);
      background: var(--vscode-button-secondaryBackground);
    }
    .status {
      min-height: 18px;
      color: var(--muted);
      font-size: 12px;
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
      <label for="enabled">Enabled</label>
      <input id="enabled" type="checkbox">
    </div>
    <div class="row">
      <label for="autoInstall">Auto install</label>
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
    <div class="field">
      <label for="postRefine">Mode</label>
      <select id="postRefine">
        <option value="standard">Standard</option>
        <option value="light">Light</option>
        <option value="strict">Strict</option>
      </select>
    </div>
    <div class="field">
      <label for="verifyTarget">Verify target</label>
      <input id="verifyTarget" type="text" placeholder="src">
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
    <input id="policyRoot" type="text" placeholder="Agent plugin or policy asset root">
  </div>

  <div class="section">
    <div class="field">
      <label for="embeddingProvider">Embedding provider</label>
      <select id="embeddingProvider">
        <option value="">Auto</option>
        <option value="openai-compatible">OpenAI-compatible /v1/embeddings</option>
        <option value="local">Local sentence-transformers</option>
        <option value="hashing">Hashing matcher</option>
        <option value="disabled">Disabled</option>
      </select>
    </div>
    <div class="field">
      <label for="embeddingBaseUrl">OpenAI-compatible base URL</label>
      <input id="embeddingBaseUrl" type="text" placeholder="https://api.openai.com/v1">
    </div>
    <div class="field">
      <label for="embeddingApiKey">Embedding API key</label>
      <input id="embeddingApiKey" type="password" placeholder="Uses OPENAI_API_KEY when empty">
    </div>
    <div class="field">
      <label for="embeddingModel">Embedding model</label>
      <input id="embeddingModel" type="text" placeholder="text-embedding-3-small">
    </div>
    <div class="field">
      <label for="embeddingTimeout">Embedding timeout seconds</label>
      <input id="embeddingTimeout" type="text" placeholder="30">
    </div>
  </div>

  <div class="actions">
    <button id="save">Save Configuration</button>
    <button id="prepareClaude" class="secondary">Prepare Claude Desktop</button>
    <button id="show" class="secondary">Show Effective Rules</button>
    <button id="validate" class="secondary">Validate Runtime</button>
    <div id="status" class="status"></div>
  </div>

  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const state = ${state};
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
    byId('embeddingProvider').value = state.config.embeddingProvider || '';
    byId('embeddingBaseUrl').value = state.config.embeddingBaseUrl || '';
    byId('embeddingApiKey').value = state.config.embeddingApiKey || '';
    byId('embeddingModel').value = state.config.embeddingModel || '';
    byId('embeddingTimeout').value = state.config.embeddingTimeout || '';

    const packs = byId('packs');

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

    byId('packSearch').addEventListener('input', renderPacks);
    byId('postRefineEnabled').addEventListener('change', () => {
      if (byId('postRefineEnabled').checked && byId('postRefine').value === 'off') {
        byId('postRefine').value = 'standard';
      }
    });

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
        embeddingProvider: byId('embeddingProvider').value.trim() || undefined,
        embeddingBaseUrl: byId('embeddingBaseUrl').value.trim() || undefined,
        embeddingApiKey: byId('embeddingApiKey').value.trim() || undefined,
        embeddingModel: byId('embeddingModel').value.trim() || undefined,
        embeddingTimeout: byId('embeddingTimeout').value.trim() || undefined,
        postRefine,
        postRefinePacks: ${JSON.stringify(DEFAULT_POST_REFINE_PACKS)},
        verifyTarget: byId('verifyTarget').value.trim() || undefined
      };
    }

    byId('save').addEventListener('click', () => {
      byId('status').textContent = 'Saving...';
      vscode.postMessage({ type: 'save', config: readConfig() });
      setTimeout(() => { byId('status').textContent = 'Saved'; }, 120);
    });
    byId('prepareClaude').addEventListener('click', () => vscode.postMessage({ type: 'prepareClaudeDesktop' }));
    byId('show').addEventListener('click', () => vscode.postMessage({ type: 'showEffectiveRules' }));
    byId('validate').addEventListener('click', () => vscode.postMessage({ type: 'validateRuntime' }));
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
  const promptExists = await exists(paths.effectivePrompt);
  const document = await vscode.workspace.openTextDocument({
    language: 'plaintext',
    content: [
      `Enabled: ${config.enabled}`,
      `Agents: ${config.agents.length ? config.agents.join(', ') : '(none)'}`,
      `Packs: ${config.packs.length ? config.packs.join(', ') : '(none)'}`,
      `Policy root: ${config.policyRoot || '(agent plugin root)'}`,
      `Embedding provider: ${config.embeddingProvider || '(auto)'}`,
      `Embedding base URL: ${config.embeddingBaseUrl || '(default)'}`,
      `Embedding model: ${config.embeddingModel || '(default)'}`,
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

async function prepareClaudeDesktop(
  workspace: PolicyWorkspace,
  status: PolicyStatusBar,
  panel: PolicyConfigViewProvider
): Promise<void> {
  const paths = workspace.pathsOrWarn();
  if (!paths) {
    return;
  }

  const config = workspace.readConfig();
  const agents = Array.from(new Set([...config.agents, 'claude'] as AgentTarget[]));

  await Promise.all([
    workspace.updateSetting('enabled', true),
    workspace.updateSetting('agents', agents)
  ]);
  await workspace.syncProjectConfig();
  status.refresh();
  panel.refresh();

  const updated = workspace.readConfig();
  const pluginRoot = await claudePluginRootCandidate(paths.root, updated);
  const pluginManifest = path.join(pluginRoot, '.claude-plugin', 'plugin.json');
  const hookConfig = path.join(pluginRoot, 'hooks', 'claude-hooks.json');
  const manifestReady = await exists(pluginManifest);
  const hooksReady = await exists(hookConfig);

  const document = await vscode.workspace.openTextDocument({
    language: 'markdown',
    content: [
      '# Claude Desktop Readiness',
      '',
      `Workspace config: \`${paths.config}\``,
      `Enabled: ${updated.enabled}`,
      `Agents: ${updated.agents.join(', ') || '(none)'}`,
      `Packs: ${updated.packs.join(', ') || '(none)'}`,
      '',
      '## Plugin Files',
      '',
      `Plugin root: \`${pluginRoot}\``,
      `Manifest: ${manifestReady ? 'ready' : 'missing'} - \`${pluginManifest}\``,
      `Hooks: ${hooksReady ? 'ready' : 'missing'} - \`${hookConfig}\``,
      manifestReady && hooksReady
        ? ''
        : 'Set `aiPolicy.policyRoot` to the AI Policy Runtime checkout or installable plugin root when these files are missing from the workspace.',
      '',
      '## Claude for Windows',
      '',
      '1. Open Claude for Windows.',
      '2. Switch to the Code tab.',
      '3. Start or open a local project session.',
      '4. Open the prompt `+` menu, choose Plugins, then add this plugin root.',
      '5. Enable AI Policy Runtime for that session.',
      '',
      'Remote sessions do not load plugins; use a local or SSH session when plugin hooks are required.',
      '',
      'Official docs:',
      '',
      '- https://code.claude.com/docs/en/desktop',
      '- https://code.claude.com/docs/en/plugins-reference',
      '- https://code.claude.com/docs/en/hooks'
    ].join('\n')
  });
  await vscode.window.showTextDocument(document);
  vscode.window.showInformationMessage('Claude Desktop workspace configuration is ready.');
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

async function claudePluginRootCandidate(root: string, config: PolicyConfig): Promise<string> {
  if (config.policyRoot) {
    return path.resolve(root, config.policyRoot);
  }
  return root;
}

function cleanOptionalString(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
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
    embeddingProvider: cleanOptionalString(config.embeddingProvider ?? ''),
    embeddingBaseUrl: cleanOptionalString(config.embeddingBaseUrl ?? ''),
    embeddingApiKey: cleanOptionalString(config.embeddingApiKey ?? ''),
    embeddingModel: cleanOptionalString(config.embeddingModel ?? ''),
    embeddingTimeout: cleanOptionalString(config.embeddingTimeout ?? ''),
    postRefine: normalizePostRefineMode(config.postRefine ?? 'off'),
    postRefinePacks: Array.isArray(config.postRefinePacks)
      ? config.postRefinePacks.filter(Boolean)
      : DEFAULT_POST_REFINE_PACKS,
    verifyTarget: cleanOptionalString(config.verifyTarget ?? '')
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

function nonceValue(): string {
  const source = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  return Array.from({ length: 32 }, () => source[Math.floor(Math.random() * source.length)]).join('');
}
