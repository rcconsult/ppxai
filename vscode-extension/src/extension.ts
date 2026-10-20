import * as vscode from 'vscode';
import * as os from 'os';
import * as path from 'path';
import * as fs from 'fs';
import * as cp from 'child_process';
import { HttpClient, getHttpClient, resetHttpClient } from './httpClient';
import { ChatViewProvider } from './chatPanel';
import { SessionsProvider } from './sessionsProvider';
import { getOutputChannel } from './outputChannel';

let backend: HttpClient;
let extensionVersion: string = 'unknown';
let serverTerminal: vscode.Terminal | undefined;
let serverProcess: cp.ChildProcess | undefined;
let startInFlight: Promise<boolean> | undefined;
// Set while stopServer() has already sent /shutdown, so closing the terminal
// does not send it again; cleared when a new server terminal opens.
let shutdownRequested = false;
// Grace before the force-kill when VS Code shuts the extension down; it
// allows deactivate() 5 s in total, and taskkill needs time inside that.
const DEACTIVATE_GRACE_MS = 2500;
const serverStatusCallbacks: Array<(running: boolean) => void> = [];

export function getExtensionVersion(): string {
    return extensionVersion;
}

/**
 * Register a callback to be notified of server status changes (v1.13.1)
 */
export function onServerStatusChange(callback: (running: boolean) => void): void {
    serverStatusCallbacks.push(callback);
}

/**
 * Notify all listeners of server status change
 */
function notifyServerStatus(running: boolean): void {
    for (const callback of serverStatusCallbacks) {
        callback(running);
    }
}

/**
 * Default binary search paths (v1.13.2)
 * These are used when ppxai-config.json is not found or has no paths section
 */
const DEFAULT_BIN_SEARCH_PATHS = [
    '{home}/.ppxai/bin',
    '{home}/.local/bin',
    '{home}/bin',
    '/usr/local/bin',
    '{home}/AppData/Local/ppxai',
];

/**
 * Expand path template variables (v1.13.2)
 * Supports {home} for home directory
 */
function expandPathTemplate(template: string): string {
    return template.replace('{home}', os.homedir());
}

/**
 * Read paths config from ppxai-config.json (v1.13.2)
 * Searches standard config locations, returns bin_search_paths or defaults
 */
function readPathsFromConfig(): string[] {
    const homeDir = os.homedir();
    const configLocations = [
        path.join(homeDir, '.ppxai', 'ppxai-config.json'),
        path.join(process.cwd(), 'ppxai-config.json'),
    ];

    for (const configPath of configLocations) {
        if (fs.existsSync(configPath)) {
            try {
                const configContent = fs.readFileSync(configPath, 'utf-8');
                const config = JSON.parse(configContent);
                if (config.paths?.bin_search_paths) {
                    return config.paths.bin_search_paths;
                }
            } catch {
                // Ignore parse errors, use defaults
            }
        }
    }

    return DEFAULT_BIN_SEARCH_PATHS;
}

/**
 * Find the ppxai-server binary (v1.13.2)
 * Reads search paths from ppxai-config.json, falls back to defaults
 */
function findServerBinary(): string {
    const platform = os.platform();
    const binaryName = platform === 'win32' ? 'ppxai-server.exe' : 'ppxai-server';

    // Get search paths from config or use defaults
    const searchPathTemplates = readPathsFromConfig();

    // Expand templates and append binary name
    for (const template of searchPathTemplates) {
        const searchDir = expandPathTemplate(template);
        const searchPath = path.join(searchDir, binaryName);
        if (fs.existsSync(searchPath)) {
            return searchPath;
        }
    }

    // Fall back to binary name (rely on PATH)
    return binaryName;
}

/**
 * Check if server is running (v1.13.1)
 */
export async function isServerRunning(): Promise<boolean> {
    return backend?.isRunning() && await backend?.isAvailable();
}

/**
 * Run ppxai-server as the terminal's own process (v1.19.5).
 *
 * The terminal is a Pseudoterminal: no shell, the extension spawns the
 * server and writes its output in. Earlier versions typed the command into
 * a shell terminal, and other extensions type into new shell terminals too:
 * Python Environments (`python-envs.terminal.autoActivationType: command`)
 * runs `source .venv/bin/activate` ~5 s after the terminal opens, VS Code
 * sends Ctrl+C first because the shell is busy, and the server died with
 * `reason: ctrl_c` 3 s after starting. Input here goes to handleInput and is
 * ignored, so nothing can interrupt the server; Stop Server is the way out.
 */
function createServerTerminal(command: string, args: string[]): vscode.Terminal {
    const write = new vscode.EventEmitter<string>();
    const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? os.homedir();
    let child: cp.ChildProcess | undefined;
    let inputHintShown = false;

    const pty: vscode.Pseudoterminal = {
        onDidWrite: write.event,
        open: () => {
            write.fire(`${[command, ...args].join(' ')}\r\n`);
            // PYTHONUNBUFFERED: stdout is a pipe now, not a tty; without it
            // the server's startup banner sits in Python's block buffer.
            child = cp.spawn(command, args, {
                cwd,
                env: { ...process.env, PYTHONUNBUFFERED: '1' },
                windowsHide: true,
            });
            serverProcess = child;
            shutdownRequested = false;
            const forward = (data: Buffer) => write.fire(data.toString().replace(/\r?\n/g, '\r\n'));
            child.stdout?.on('data', forward);
            child.stderr?.on('data', forward);
            child.on('error', (err) => {
                write.fire(`\r\n[ppxai] Could not start ${command}: ${err.message}\r\n`);
            });
            child.on('exit', (code, signal) => {
                if (serverProcess === child) {
                    serverProcess = undefined;
                }
                write.fire(`\r\n[ppxai] ppxai-server exited (${signal ?? `code ${code}`}).\r\n`);
            });
        },
        close: () => {
            // Terminal closed or disposed: take the server with it, as the
            // shell terminal did (SIGHUP) before. Every path that ends this
            // terminal lands here: the terminal's own close button, Start
            // replacing a stale terminal, and deactivate().
            if (child && child.exitCode === null && child.signalCode === null) {
                void stopChild(child);
            }
        },
        handleInput: () => {
            if (!inputHintShown) {
                inputHintShown = true;
                write.fire('\r\n[ppxai] This terminal ignores input. Use Stop Server to stop the server.\r\n');
            }
        },
    };

    return vscode.window.createTerminal({
        name: 'ppxai-server',
        pty,
        iconPath: new vscode.ThemeIcon('server-process'),
    });
}

/**
 * Stop a server process this extension spawned, the way Stop Server does.
 *
 * Not a bare `child.kill()`: on Windows the installed ppxai-server.exe is a
 * PyInstaller one-file build, so `child` is the bootloader and the real
 * server is ITS child. `kill()` is TerminateProcess on the bootloader alone;
 * the server kept running, kept :54320, and the next Start's server died on
 * the bind while the panel quietly reattached to the orphan. So: ask the
 * server to shut down (its lifespan runs, `reason: api_request`), wait, and
 * only then force it, taking the whole tree on win32.
 *
 * The /shutdown request is not awaited: its own abort is 5 s, and the grace
 * period runs from the moment it is sent. `graceMs` is shorter on the
 * deactivate() path, because VS Code gives deactivate() 5 s in all
 * (extHostExtensionService.terminate: `Promise.race([timeout(5000), ...])`)
 * and the force-kill has to land inside that.
 */
async function stopChild(proc: cp.ChildProcess, graceMs = 5000): Promise<void> {
    if (!shutdownRequested) {
        shutdownRequested = true;
        void backend?.shutdown();
    }
    await waitForExit(proc, graceMs);
    if (proc.exitCode !== null || proc.signalCode !== null) {
        return;
    }
    if (process.platform === 'win32' && proc.pid !== undefined) {
        await new Promise<void>(resolve => {
            const killer = cp.spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], {
                windowsHide: true,
                stdio: 'ignore',
            });
            killer.on('error', () => resolve());
            killer.on('exit', () => resolve());
        });
    } else {
        proc.kill();
    }
}

/** Resolve once `proc` has exited, or after `ms`, whichever comes first. */
function waitForExit(proc: cp.ChildProcess | undefined, ms: number): Promise<void> {
    if (!proc || proc.exitCode !== null || proc.signalCode !== null) {
        return Promise.resolve();
    }
    return new Promise(resolve => {
        const timer = setTimeout(resolve, ms);
        proc.once('exit', () => {
            clearTimeout(timer);
            resolve();
        });
    });
}

/**
 * Start the ppxai-server in a terminal (v1.13.1, v1.13.2)
 *
 * v1.19.5: a second Start while one is in flight joins it instead of
 * disposing the half-started terminal (which killed that server) and
 * running another retry loop.
 */
export async function startServer(): Promise<boolean> {
    if (startInFlight) {
        return startInFlight;
    }
    startInFlight = (async (): Promise<boolean> => {
        // Check if already running
        if (await isServerRunning()) {
            vscode.window.showInformationMessage('ppxai-server is already running');
            notifyServerStatus(true);
            return true;
        }

        // Check if terminal exists but server not responding
        if (serverTerminal) {
            serverTerminal.dispose();
            serverTerminal = undefined;
        }

        // Find the server binary
        const serverBinary = findServerBinary();
        const binaryExists = fs.existsSync(serverBinary);

        // Log for debugging
        console.log(`[ppxai] Server binary path: ${serverBinary}`);
        console.log(`[ppxai] Binary exists: ${binaryExists}`);

        // v1.13.2: the installed binary, else uv run for dev environments.
        // An argv array needs no quoting for paths with spaces.
        const [command, args]: [string, string[]] = binaryExists
            ? [serverBinary, []]
            : ['uv', ['run', 'ppxai-server']];

        console.log(`[ppxai] Starting server with command: ${[command, ...args].join(' ')}`);
        serverTerminal = createServerTerminal(command, args);
        serverTerminal.show(true); // Show but don't take focus

        // Wait for server to start with circuit breaker pattern (v1.13.2)
        // Longer initial delays for Windows (antivirus scanning on first run)
        // Delays: 2s, 3s, 4s, 5s, 8s, 12s then give up
        const retryDelays = [2000, 3000, 4000, 5000, 8000, 12000];
        let started = false;
        for (const delay of retryDelays) {
            await new Promise(resolve => setTimeout(resolve, delay));
            started = await backend.start();
            if (started || !serverProcess) {
                break;  // up, or the process already exited (its terminal says why)
            }
        }
        if (started) {
            vscode.window.showInformationMessage('ppxai-server started successfully');
            notifyServerStatus(true);
            return true;
        }
        if (!serverProcess) {
            vscode.window.showErrorMessage('ppxai-server exited during startup. See the ppxai-server terminal.');
            return false;
        }

        // Give it more time and retry
        await new Promise(resolve => setTimeout(resolve, 3000));
        const retryStarted = await backend.start();
        if (retryStarted) {
            vscode.window.showInformationMessage('ppxai-server started successfully');
            notifyServerStatus(true);
            return true;
        }

        vscode.window.showWarningMessage('ppxai-server may still be starting. Check the terminal for status.');
        return false;
    })();
    try {
        return await startInFlight;
    } finally {
        startInFlight = undefined;
    }
}

/**
 * Stop the ppxai-server (v1.13.1, v1.13.10: use HTTP endpoint)
 *
 * v1.13.10: Uses POST /shutdown endpoint for graceful shutdown
 * (same as web app), instead of sending Ctrl+C to terminal.
 */
export async function stopServer(): Promise<void> {
    // v1.13.10: Use HTTP endpoint for graceful shutdown (like web app)
    shutdownRequested = true;
    try {
        await backend.shutdown();
    } catch (error) {
        // Server may already be down or unreachable
        console.log('Server shutdown request completed (may have been already down)');
    }

    // Wait for the server we started to exit (it shuts down 0.5 s after
    // answering /shutdown); closing the terminal below kills it otherwise.
    await waitForExit(serverProcess, 5000);

    // Clean up terminal if we started one
    if (serverTerminal) {
        serverTerminal.dispose();
        serverTerminal = undefined;
    }

    backend.stop();
    notifyServerStatus(false);
    vscode.window.showInformationMessage('ppxai-server stopped');
}

/**
 * Toggle server state (v1.13.1)
 */
export async function toggleServer(): Promise<boolean> {
    const running = await isServerRunning();
    if (running) {
        await stopServer();
        return false;
    } else {
        return await startServer();
    }
}

export async function activate(context: vscode.ExtensionContext) {
    // Get version from package.json
    extensionVersion = context.extension.packageJSON.version || 'unknown';
    console.log(`ppxai extension v${extensionVersion} activating...`);

    // The extension's one general-purpose output channel ("ppxai") — created
    // here (once) and registered for disposal so it doesn't leak across
    // repeated activate/deactivate cycles. Separate from HttpClient's own
    // "ppxai HTTP" channel (session/SSE/consent tracing), which keeps its
    // own lifecycle.
    context.subscriptions.push(getOutputChannel());

    // Initialize HTTP backend (connects to ppxai-server)
    backend = getHttpClient();

    // Item 40: restore the /v1 API bearer from SecretStorage (set via the
    // `ppxai.setApiToken` command below). SecretStorage — never settings —
    // so the token can't sync to other machines or leak into dotfiles.
    try {
        const storedApiToken = await context.secrets.get('ppxai.apiToken');
        if (storedApiToken) { backend.setApiToken(storedApiToken); }
    } catch { /* secrets unavailable — run token-less */ }

    // Initialize chat view provider
    const chatViewProvider = new ChatViewProvider(context, backend);

    // Initialize sessions provider
    const sessionsProvider = new SessionsProvider(context);

    // Register webview provider
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider('ppxai.chatView', chatViewProvider)
    );

    // Register tree data provider for sessions
    context.subscriptions.push(
        vscode.window.registerTreeDataProvider('ppxai.sessions', sessionsProvider)
    );

    // Register commands
    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.openChat', () => {
            vscode.commands.executeCommand('ppxai.chatView.focus');
        })
    );

    // Item 40: set/clear the bearer for the protected /v1 API surface
    // (`/task` family + /v1/tokens). Masked input; empty submit clears.
    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.setApiToken', async () => {
            const value = await vscode.window.showInputBox({
                prompt: 'ppxai API token for /v1 calls (leave empty to clear)',
                password: true,
                ignoreFocusOut: true,
            });
            if (value === undefined) { return; } // dismissed — no change
            if (value.trim() === '') {
                await context.secrets.delete('ppxai.apiToken');
                backend.setApiToken(undefined);
                vscode.window.showInformationMessage('ppxai: API token cleared.');
                return;
            }
            await context.secrets.store('ppxai.apiToken', value.trim());
            backend.setApiToken(value.trim());
            vscode.window.showInformationMessage(
                `ppxai: API token stored (…${value.trim().slice(-4)}) — attached to /v1 calls.`);
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.explainSelection', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                vscode.window.showWarningMessage('No active editor');
                return;
            }
            const selection = editor.document.getText(editor.selection);
            if (!selection) {
                vscode.window.showWarningMessage('No text selected');
                return;
            }
            const language = editor.document.languageId;
            await chatViewProvider.sendCodingTask('explain', selection, language);
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.generateTests', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                vscode.window.showWarningMessage('No active editor');
                return;
            }
            const content = editor.document.getText(editor.selection) || editor.document.getText();
            const language = editor.document.languageId;
            const filename = editor.document.fileName;
            await chatViewProvider.sendCodingTask('test', content, language, filename);
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.generateDocs', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                vscode.window.showWarningMessage('No active editor');
                return;
            }
            const content = editor.document.getText(editor.selection) || editor.document.getText();
            const language = editor.document.languageId;
            const filename = editor.document.fileName;
            await chatViewProvider.sendCodingTask('docs', content, language, filename);
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.debugError', async () => {
            const errorMessage = await vscode.window.showInputBox({
                prompt: 'Enter the error message to debug',
                placeHolder: 'Paste error message here...'
            });
            if (errorMessage) {
                await chatViewProvider.sendCodingTask('debug', errorMessage);
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.implement', async () => {
            const description = await vscode.window.showInputBox({
                prompt: 'Describe what you want to implement',
                placeHolder: 'e.g., A function that validates email addresses'
            });
            if (description) {
                const editor = vscode.window.activeTextEditor;
                const language = editor?.document.languageId || 'python';
                await chatViewProvider.sendCodingTask('implement', description, language);
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.switchProvider', async () => {
            // Ensure backend is running
            if (!backend.isRunning()) {
                try {
                    await backend.start();
                } catch (error) {
                    vscode.window.showErrorMessage(`Failed to start backend: ${error}`);
                    return;
                }
            }

            try {
                const providers = await backend.getProviders();
                if (providers.length === 0) {
                    vscode.window.showErrorMessage('No providers available');
                    return;
                }

                const items = providers.map(p => ({
                    label: p.name,
                    description: p.has_api_key ? '' : '(no API key)',
                    id: p.id
                }));

                const selected = await vscode.window.showQuickPick(items, {
                    placeHolder: 'Select AI provider'
                });

                if (selected) {
                    const success = await backend.setProvider((selected as any).id);
                    if (success) {
                        // "Loading the <provider> provider…" and friends
                        // (ADR 0016 §5) ride on the response's events.
                        chatViewProvider._drainEnvelopeEvents(success.events);
                        chatViewProvider.updateStatus();
                        // 2026-09-21 (owner decision 8): re-anchor the full
                        // AppState (including modelSupportsVision) so the
                        // attach-button badge reflects the new provider's
                        // default model immediately. Mirrors web's
                        // handleProviderChange — see chatPanel.ts's
                        // `reanchorState()` doc comment for why updateStatus()
                        // alone does not cover this field.
                        void chatViewProvider.reanchorState();
                        vscode.window.showInformationMessage(`Switched to ${selected.label}`);
                    } else {
                        vscode.window.showErrorMessage(`Failed to switch to ${selected.label}`);
                    }
                }
            } catch (error) {
                vscode.window.showErrorMessage(`Failed to switch provider: ${error}`);
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.switchModel', async () => {
            // Ensure backend is running
            if (!backend.isRunning()) {
                try {
                    await backend.start();
                } catch (error) {
                    vscode.window.showErrorMessage(`Failed to start backend: ${error}`);
                    return;
                }
            }

            try {
                const models = await backend.getModels();
                if (models.length === 0) {
                    vscode.window.showErrorMessage('No models available');
                    return;
                }

                const selected = await vscode.window.showQuickPick(
                    models.map(m => ({
                        label: m.name,
                        description: m.description,
                        id: m.id
                    })),
                    { placeHolder: 'Select model' }
                );

                if (selected) {
                    await backend.setModel((selected as any).id);
                    chatViewProvider.updateStatus();
                    // 2026-09-21 (owner decision 8): see the matching
                    // comment in ppxai.switchProvider above.
                    void chatViewProvider.reanchorState();
                    vscode.window.showInformationMessage(`Switched to ${selected.label}`);
                }
            } catch (error) {
                vscode.window.showErrorMessage(`Failed to switch model: ${error}`);
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.loadSession', async (sessionName: string) => {
            // Ensure backend is running
            if (!backend.isRunning()) {
                try {
                    await backend.start();
                } catch (error) {
                    vscode.window.showErrorMessage(`Failed to start backend: ${error}`);
                    return;
                }
            }

            try {
                const success = await backend.loadSession(sessionName);
                if (success) {
                    chatViewProvider.refreshHistory();
                    await chatViewProvider.updateStatus();  // v1.15.3: Update provider/model from restored session
                    vscode.window.showInformationMessage(`Loaded session: ${sessionName}`);
                } else {
                    vscode.window.showErrorMessage(`Session not found: ${sessionName}`);
                }
            } catch (error) {
                vscode.window.showErrorMessage(`Failed to load session: ${error}`);
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.refreshSessions', () => {
            sessionsProvider.refresh();
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.saveSession', async () => {
            // Ensure backend is running
            if (!backend.isRunning()) {
                try {
                    await backend.start();
                } catch (error) {
                    vscode.window.showErrorMessage(`Failed to start backend: ${error}`);
                    return;
                }
            }

            try {
                const sessionName = await backend.saveSession();
                sessionsProvider.refresh();
                vscode.window.showInformationMessage(`Session saved: ${sessionName}`);
            } catch (error) {
                vscode.window.showErrorMessage(`Failed to save session: ${error}`);
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.clearHistory', async () => {
            try {
                // v1.19.1: goes through the panel's single clear path (command
                // envelope → CommandFactory → handle_clear) rather than the
                // bespoke backend.clearHistory() REST call. Keeps the palette
                // command, the webview button, and a typed /clear on one
                // handler — see ChatViewProvider.clearConversation.
                await chatViewProvider.clearConversation();
            } catch (error) {
                vscode.window.showErrorMessage(`Failed to clear history: ${error}`);
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.interrupt', async () => {
            try {
                await backend.interrupt();
                vscode.window.showInformationMessage('Interrupted current request');
            } catch (error) {
                vscode.window.showErrorMessage(`Failed to interrupt: ${error}`);
            }
        })
    );

    // Server control commands (v1.13.1)
    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.startServer', async () => {
            await startServer();
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.stopServer', async () => {
            await stopServer();
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.toggleServer', async () => {
            await toggleServer();
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.serverStatus', async () => {
            const running = await isServerRunning();
            if (running) {
                const health = await backend.getHealth();
                vscode.window.showInformationMessage(
                    `ppxai-server is running (v${health.version})`
                );
            } else {
                const action = await vscode.window.showWarningMessage(
                    'ppxai-server is not running',
                    'Start Server'
                );
                if (action === 'Start Server') {
                    await startServer();
                }
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.reloadConfig', async () => {
            const running = await isServerRunning();
            if (!running) {
                vscode.window.showWarningMessage('ppxai-server is not running');
                return;
            }
            try {
                const result = await backend.reloadConfig();
                if (result.success) {
                    vscode.window.showInformationMessage(
                        `Configuration reloaded from ${result.config_path || 'defaults'}`
                    );
                    // Re-sync state — config reload may change provider, model, tools, etc.
                    chatViewProvider.updateStatus();
                } else {
                    vscode.window.showErrorMessage(`Failed to reload config: ${result.message}`);
                }
            } catch (error) {
                vscode.window.showErrorMessage(`Failed to reload config: ${error}`);
            }
        })
    );

    // Context usage commands (v1.13.9)
    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.showContextUsage', async () => {
            const running = await isServerRunning();
            if (!running) {
                vscode.window.showWarningMessage('ppxai-server is not running');
                return;
            }
            try {
                const info = await backend.getContextInfo();
                const usageBar = '█'.repeat(Math.floor(info.usage_percent / 10)) +
                                '░'.repeat(10 - Math.floor(info.usage_percent / 10));
                const injectionList = info.injected_contexts.length > 0
                    ? info.injected_contexts.map(c => `  • ${c.source} (${Math.round(c.size/1000)}KB${c.truncated ? ', truncated' : ''})`).join('\n')
                    : '  (none)';

                vscode.window.showInformationMessage(
                    `Context Usage: ${info.usage_percent.toFixed(1)}%\n` +
                    `[${usageBar}] ${info.estimated_tokens.toLocaleString()}/${info.context_limit.toLocaleString()} tokens\n` +
                    `Messages: ${info.message_count} | Injections: ${info.injected_contexts.length}`,
                    { modal: false }
                );
            } catch (error) {
                vscode.window.showErrorMessage(`Failed to get context info: ${error}`);
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('ppxai.clearContextInjections', async () => {
            const running = await isServerRunning();
            if (!running) {
                vscode.window.showWarningMessage('ppxai-server is not running');
                return;
            }
            try {
                const result = await backend.clearContextInjections();
                if (result.success) {
                    if (result.removed_count > 0) {
                        vscode.window.showInformationMessage(
                            `Cleared ${result.removed_count} injected file(s) from context`
                        );
                    } else {
                        vscode.window.showInformationMessage('No injected files to clear');
                    }
                }
            } catch (error) {
                vscode.window.showErrorMessage(`Failed to clear context: ${error}`);
            }
        })
    );

    // Handle terminal close events to track server state
    context.subscriptions.push(
        vscode.window.onDidCloseTerminal((terminal) => {
            if (terminal === serverTerminal) {
                serverTerminal = undefined;
                backend.stop();
                notifyServerStatus(false);
            }
        })
    );

    console.log('ppxai extension activated');
}

export async function deactivate(): Promise<void> {
    // Stop server terminal if running
    const proc = serverProcess;
    if (serverTerminal) {
        serverTerminal.dispose();
        serverTerminal = undefined;
    }
    // Returned to VS Code, which waits for it: a fire-and-forget stop would
    // die with the extension host and leave the server running. VS Code waits
    // 5 s at most, so this stop gets a 2.5 s grace before the force-kill
    // instead of the 5 s the terminal's own close() allows (the /shutdown it
    // sent is not repeated).
    if (proc && proc.exitCode === null && proc.signalCode === null) {
        await stopChild(proc, DEACTIVATE_GRACE_MS);
    }
    // Reset HTTP client
    resetHttpClient();
}
