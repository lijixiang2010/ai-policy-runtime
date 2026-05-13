import * as fs from 'fs/promises';
import * as path from 'path';
import * as vscode from 'vscode';

type PolicyConfig = {
  enabled: boolean;
  packs: string[];
  policyRoot?: string;
  autoInstall: boolean;
  embeddingProvider?: string;
};

type PolicyPaths = {
  root: string;
  config: string;
  effectivePrompt: string;
};

type PackItem = vscode.QuickPickItem & { label: string };

const CONFIG_SECTION = 'aiPolicy';
const POLICY_CONFIG_FILE = path.join('.policy', 'config.json');
const EFFECTIVE_PROMPT_FILE = path.join('.policy', 'current', 'effective-prompt.md');
const DEFAULT_PACKS = ['cpp.safe_generation'];
const DEFAULT_EMBEDDING_PROVIDER = 'hashing';

const COMMANDS = {
  enable: 'aiPolicy.enable',
  disable: 'aiPolicy.disable',
  configurePacks: 'aiPolicy.configurePacks',
  showStatus: 'aiPolicy.showStatus',
  showEffectiveRules: 'aiPolicy.showEffectiveRules',
  validateRuntime: 'aiPolicy.validateRuntime'
} as const;

const KNOWN_PACKS: PackItem[] = [
  { label: 'cpp.safe_generation', description: 'C++ safety-first code generation' },
  { label: 'cpp.low_latency', description: 'C++ hot-path and low-latency work' },
  { label: 'cpp.code_review', description: 'C++ review with safety checks' },
  { label: 'cpp.library_api_design', description: 'C++ API design and parameter intent' },
  { label: 'cpp.modernization', description: 'Modern C++ refactoring guidance' },
  { label: 'cpp.production_refinement', description: 'C++ production polish and safety' },
  { label: 'generic.production_refinement', description: 'General code quality refinement' }
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

    await fs.mkdir(path.dirname(paths.config), { recursive: true });
    await fs.writeFile(paths.config, `${JSON.stringify(this.readConfig(), null, 2)}\n`, 'utf8');
  }

  async saveConfig(config: PolicyConfig): Promise<void> {
    await Promise.all([
      this.updateSetting('enabled', config.enabled),
      this.updateSetting('packs', config.packs),
      this.updateSetting('policyRoot', config.policyRoot ?? ''),
      this.updateSetting('autoInstall', config.autoInstall),
      this.updateSetting('embeddingProvider', config.embeddingProvider ?? 'auto')
    ]);
    await this.syncProjectConfig();
  }

  readConfig(): PolicyConfig {
    const config = vscode.workspace.getConfiguration(CONFIG_SECTION);
    const embeddingProvider = config.get<string>('embeddingProvider', DEFAULT_EMBEDDING_PROVIDER);
    return {
      enabled: config.get<boolean>('enabled', false),
      packs: config.get<string[]>('packs', DEFAULT_PACKS),
      policyRoot: cleanOptionalString(config.get<string>('policyRoot', '')),
      autoInstall: config.get<boolean>('autoInstall', true),
      embeddingProvider: embeddingProvider === 'auto' ? undefined : embeddingProvider
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

  private html(webview: vscode.Webview, config: PolicyConfig): string {
    const nonce = nonceValue();
    const state = JSON.stringify({
      config,
      packs: KNOWN_PACKS.map(({ label, description }) => ({ label, description }))
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
    .pack {
      display: grid;
      grid-template-columns: 18px 1fr;
      gap: 8px;
      align-items: start;
      padding: 7px 0;
    }
    .pack span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      margin-top: 2px;
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
    <div class="subtle">Codex prompt policy for this workspace.</div>
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
    <label>Packs</label>
    <div id="packs" class="pack-list"></div>
  </div>

  <div class="section">
    <label for="provider">Embedding provider</label>
    <select id="provider">
      <option value="auto">auto</option>
      <option value="hashing">hashing</option>
      <option value="disabled">disabled</option>
      <option value="local">local</option>
      <option value="openai-compatible">openai-compatible</option>
    </select>
    <label for="policyRoot">Policy root</label>
    <input id="policyRoot" type="text" placeholder="Codex plugin root">
  </div>

  <div class="actions">
    <button id="save">Save Configuration</button>
    <button id="show" class="secondary">Show Effective Rules</button>
    <button id="validate" class="secondary">Validate Runtime</button>
    <div id="status" class="status"></div>
  </div>

  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const state = ${state};
    const byId = (id) => document.getElementById(id);
    const selected = new Set(state.config.packs || []);
    byId('enabled').checked = Boolean(state.config.enabled);
    byId('autoInstall').checked = Boolean(state.config.autoInstall);
    byId('provider').value = state.config.embeddingProvider || 'auto';
    byId('policyRoot').value = state.config.policyRoot || '';

    const packs = byId('packs');
    state.packs.forEach((pack) => {
      const id = 'pack-' + pack.label.replaceAll('.', '-');
      const row = document.createElement('label');
      row.className = 'pack';
      row.innerHTML = '<input type="checkbox" id="' + id + '" value="' + pack.label + '">' +
        '<div>' + pack.label + '<span>' + pack.description + '</span></div>';
      packs.appendChild(row);
      row.querySelector('input').checked = selected.has(pack.label);
    });

    function readConfig() {
      return {
        enabled: byId('enabled').checked,
        packs: Array.from(document.querySelectorAll('#packs input:checked')).map((item) => item.value),
        policyRoot: byId('policyRoot').value.trim() || undefined,
        autoInstall: byId('autoInstall').checked,
        embeddingProvider: byId('provider').value === 'auto' ? undefined : byId('provider').value
      };
    }

    byId('save').addEventListener('click', () => {
      byId('status').textContent = 'Saving...';
      vscode.postMessage({ type: 'save', config: readConfig() });
      setTimeout(() => { byId('status').textContent = 'Saved'; }, 120);
    });
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
    this.item.text = config.enabled ? 'AI Policy: On' : 'AI Policy: Off';
    this.item.tooltip = config.enabled
      ? `Packs: ${config.packs.join(', ') || '(none)'}`
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

async function configurePacks(workspace: PolicyWorkspace): Promise<void> {
  const selected = new Set(workspace.readConfig().packs);
  const picks = await vscode.window.showQuickPick(
    KNOWN_PACKS.map((pack) => ({
      ...pack,
      picked: selected.has(pack.label)
    })),
    {
      canPickMany: true,
      title: 'Select AI Policy packs for Codex'
    }
  );
  if (!picks) {
    return;
  }

  await workspace.updateSetting('packs', picks.map((item) => item.label));
  await workspace.syncProjectConfig();
  vscode.window.showInformationMessage(`AI Policy packs updated: ${picks.length || 'none'}.`);
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
      `Packs: ${config.packs.length ? config.packs.join(', ') : '(none)'}`,
      `Policy root: ${config.policyRoot || '(Codex plugin root)'}`,
      `Embedding provider: ${config.embeddingProvider || 'auto'}`,
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
    packs: Array.isArray(config.packs) ? config.packs.filter(Boolean) : DEFAULT_PACKS,
    policyRoot: cleanOptionalString(config.policyRoot ?? ''),
    autoInstall: Boolean(config.autoInstall),
    embeddingProvider: config.embeddingProvider
  };
}

function nonceValue(): string {
  const source = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  return Array.from({ length: 32 }, () => source[Math.floor(Math.random() * source.length)]).join('');
}
