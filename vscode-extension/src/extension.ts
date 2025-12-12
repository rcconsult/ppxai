import * as vscode from 'vscode';
import { HttpClient, getHttpClient, resetHttpClient } from './httpClient';
import { ChatViewProvider } from './chatPanel';
import { SessionsProvider } from './sessionsProvider';

let backend: HttpClient;

export async function activate(context: vscode.ExtensionContext) {
    console.log('ppxai extension activating...');

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

    console.log('ppxai extension activated');
}

export function deactivate() {
    // Reset HTTP client
    resetHttpClient();
}
