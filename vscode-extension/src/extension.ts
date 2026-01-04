import * as vscode from 'vscode';
import * as os from 'os';
import { HttpClient, getHttpClient, resetHttpClient } from './httpClient';
import { ChatViewProvider } from './chatPanel';
import { SessionsProvider } from './sessionsProvider';

let backend: HttpClient;
let extensionVersion: string = 'unknown';
let serverTerminal: vscode.Terminal | undefined;
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
 * Find the ppxai-server binary (v1.13.1)
 * Returns the binary name, expecting it to be in PATH (via install.sh or system)
 */
function findServerBinary(): string {
    const platform = os.platform();
    const binaryName = platform === 'win32' ? 'ppxai-server.exe' : 'ppxai-server';

    // Return just the binary name - let the shell find it in PATH
    // If user installed via install.sh, ~/.local/bin should be in PATH
    // Otherwise, uv run ppxai-server works as fallback
    return binaryName;
}

/**
 * Check if server is running (v1.13.1)
 */
export async function isServerRunning(): Promise<boolean> {
    return backend?.isRunning() && await backend?.isAvailable();
}

/**
 * Start the ppxai-server in a terminal (v1.13.1)
 */
export async function startServer(): Promise<boolean> {
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

    // Determine the command to run
    // Try ppxai-server directly first (if in PATH via install.sh)
    // Fall back to 'uv run ppxai-server' for dev environments
    const serverBinary = findServerBinary();

    // Create terminal with specific name
    serverTerminal = vscode.window.createTerminal({
        name: 'ppxai-server',
        hideFromUser: false, // Show terminal so user can see output
        iconPath: new vscode.ThemeIcon('server-process')
    });

    // Try running the server
    // First try direct binary, if that fails user will see error and can try uv run
    serverTerminal.sendText(`${serverBinary} || uv run ppxai-server`);
    serverTerminal.show(true); // Show but don't take focus

    // Wait a bit for server to start, then check health
    await new Promise(resolve => setTimeout(resolve, 2000));

    // Try to connect
    const started = await backend.start();
    if (started) {
        vscode.window.showInformationMessage('ppxai-server started successfully');
        notifyServerStatus(true);
        return true;
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
}

/**
 * Stop the ppxai-server (v1.13.1)
 */
export async function stopServer(): Promise<void> {
    if (serverTerminal) {
        // Send Ctrl+C to gracefully stop
        serverTerminal.sendText('\x03'); // Ctrl+C
        await new Promise(resolve => setTimeout(resolve, 500));
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

    // Initialize HTTP backend (connects to ppxai-server)
    backend = getHttpClient();

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
                        chatViewProvider.updateStatus();
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
                await backend.clearHistory();
                chatViewProvider.refreshHistory();
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

export function deactivate() {
    // Stop server terminal if running
    if (serverTerminal) {
        serverTerminal.dispose();
        serverTerminal = undefined;
    }
    // Reset HTTP client
    resetHttpClient();
}
