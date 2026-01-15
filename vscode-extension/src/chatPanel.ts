/**
 * Chat Panel Webview Provider
 *
 * Interrupt handling (Esc key) inspired by Claude Code by Anthropic
 * https://claude.ai/code
 *
 * v1.14.0 - Uses shared modules for command definitions and formatters
 *           to maintain parity with Desktop Web App.
 */

import * as vscode from 'vscode';
import { HttpClient, StreamEvent } from './httpClient';
import { startServer, stopServer, onServerStatusChange } from './extension';

// Import shared modules for command definitions and formatters
import {
    SLASH_COMMANDS,
    generateHelpText,
    isAIForwardedCommand,
    parseCommand
} from './shared/commands';
import {
    formatToolsStatus,
    formatToolsList,
    formatToolConfig,
    formatToolHelp,
    formatAgentStatus,
    formatCheckpointStatus,
    formatCheckpointList,
    formatCheckpointInfo,
    formatCheckpointBackendHelp,
    formatUsageStats,
    formatUsageDisplayHelp,
    formatStatus,
    formatProvidersList,
    formatModelsList,
    formatSessionsList
} from './shared/formatters';

export class ChatViewProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'ppxai.chatView';

    private _view?: vscode.WebviewView;
    private _backend: HttpClient;
    private _context: vscode.ExtensionContext;

    constructor(
        context: vscode.ExtensionContext,
        backend: HttpClient
    ) {
        this._context = context;
        this._backend = backend;
    }

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken
    ) {
        this._view = webviewView;

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this._context.extensionUri]
        };

        webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);

        // Handle messages from the webview
        webviewView.webview.onDidReceiveMessage(async (message) => {
            switch (message.type) {
                case 'chat':
                    await this.handleChat(message.content);
                    break;
                case 'clear':
                    await this._backend.clearHistory();
                    this._view?.webview.postMessage({ type: 'cleared' });
                    break;
                case 'save':
                    vscode.commands.executeCommand('ppxai.saveSession');
                    break;
                case 'saveAnswer':
                    await this.handleSaveAnswer(message.content);
                    break;
                case 'ready':
                    await this.initializeBackend();
                    break;
                case 'toggleTools':
                    await this.handleToggleTools(message.enable);
                    break;
                case 'toggleDebugLog':
                    await this.handleToggleDebugLog(message.enable);
                    break;
                case 'toggleServer':
                    await this.handleToggleServer(message.stop);
                    break;
                case 'toggleAgent':
                    await this.handleToggleAgent(message.enable);
                    break;
                case 'undoCheckpoint':
                    await this.handleUndoCheckpoint();
                    break;
                case 'searchFiles':
                    await this.handleSearchFilesForAutocomplete(message.query);
                    break;
                case 'openLink':
                    if (message.url) {
                        vscode.env.openExternal(vscode.Uri.parse(message.url));
                    }
                    break;
                case 'interrupt':
                    await this.handleInterrupt();
                    break;
                case 'clearContext':
                    await this.handleClearContext();
                    break;
            }
        });
    }

    private async handleSearchFilesForAutocomplete(query: string) {
        if (!this._view) { return; }

        try {
            const matches = await this.searchFiles(query || '', 10);
            const workspaceFolders = vscode.workspace.workspaceFolders;
            const pathModule = require('path');

            // v1.13.8: Include special refs (@git, @tree) at the start
            const specialRefs = [
                { name: '@git', path: 'Include git diff' },
                { name: '@tree', path: 'Include project structure' },
            ];

            // Filter special refs by query
            const queryLower = (query || '').toLowerCase();
            const filteredSpecialRefs = specialRefs.filter(ref =>
                ref.name.toLowerCase().includes(queryLower)
            );

            const files = matches.map(m => {
                const name = m.path.split('/').pop() || '';
                const relPath = workspaceFolders
                    ? pathModule.relative(workspaceFolders[0].uri.fsPath, m.fsPath)
                    : m.path;
                return { name, path: relPath };
            });

            this._view.webview.postMessage({
                type: 'fileSuggestions',
                files: [...filteredSpecialRefs, ...files]
            });
        } catch (error) {
            // Silently fail - autocomplete is optional
        }
    }

    private async initializeBackend() {
        try {
            // Register for server status changes (v1.13.1)
            onServerStatusChange((running: boolean) => {
                this.updateServerStatus(running);
            });

            // Connect to ppxai-server if not running (v1.13.2: auto-start server)
            if (!this._backend.isRunning()) {
                // Show connecting state (v1.13.1)
                this._view?.webview.postMessage({
                    type: 'serverStatus',
                    connected: false,
                    connecting: true
                });
                this._view?.webview.postMessage({
                    type: 'systemMessage',
                    content: 'Connecting to ppxai-server...'
                });

                // First try to connect to existing server
                let connected = await this._backend.start();

                // v1.13.2: If no server running, auto-start it
                if (!connected) {
                    this._view?.webview.postMessage({
                        type: 'systemMessage',
                        content: 'Starting ppxai-server...'
                    });

                    // Start the server binary
                    const serverStarted = await startServer();
                    if (serverStarted) {
                        // Server started, now connect
                        connected = await this._backend.start();
                    }
                }

                // Update server status (v1.13.1)
                this._view?.webview.postMessage({
                    type: 'serverStatus',
                    connected: connected,
                    connecting: false
                });
                if (!connected) {
                    this._view?.webview.postMessage({
                        type: 'error',
                        content: 'Could not connect to ppxai-server. Click the server badge to start it, or run: ppxai-server'
                    });
                    return;
                }
            } else {
                // Already connected (v1.13.1)
                this._view?.webview.postMessage({
                    type: 'serverStatus',
                    connected: true,
                    connecting: false
                });
            }

            // Set working directory for context injection
            const workspaceFolders = vscode.workspace.workspaceFolders;
            if (workspaceFolders && workspaceFolders.length > 0) {
                await this._backend.setWorkingDir(workspaceFolders[0].uri.fsPath);
            }

            // Sync tools setting from VSCode configuration
            const config = vscode.workspace.getConfiguration('ppxai');
            const enableTools = config.get<boolean>('enableTools', false);
            if (enableTools) {
                await this._backend.enableTools();
            }

            await this.updateStatus();
            await this.refreshHistory();
            await this.updateDebugLogStatus();
            await this.updateAgentStatus();  // v1.11.8
            await this.updateWorkspaceDisplay();
        } catch (error) {
            this._view?.webview.postMessage({
                type: 'error',
                content: `Failed to initialize backend: ${error}`
            });
        }
    }

    private async handleChat(content: string) {
        if (!this._view) { return; }

        const trimmed = content.trim();

        // Check if it's a slash command
        if (trimmed.startsWith('/')) {
            await this.handleSlashCommand(trimmed);
            return;
        }

        // Regular chat message
        // Show user message
        this._view.webview.postMessage({
            type: 'userMessage',
            content
        });

        // Process @filename references and build augmented message
        const { message: augmentedMessage, files: resolvedFiles } = await this.processFileReferences(content);

        // Show resolved files notification if any were found
        if (resolvedFiles.length > 0) {
            const fileList = resolvedFiles.map(f => f.name).join(', ');
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: `*Including ${resolvedFiles.length} file(s): ${fileList}*`
            });
        }

        // Inject workspace context for AI awareness (v1.11.2)
        const workspaceContext = await this.getWorkspaceContext();
        const finalMessage = workspaceContext + augmentedMessage;

        // Start streaming response
        this._view.webview.postMessage({ type: 'startResponse' });

        try {
            await this._backend.chat(finalMessage, (event) => {
                this.handleStreamEvent(event);
            });
        } catch (error) {
            // Don't show interrupt as error - user initiated it
            if (error instanceof Error && error.message === 'Interrupted by user') {
                // Silent interrupt handling
                this._view.webview.postMessage({ type: 'endResponse' });
                await this.updateStatus();  // v1.12.0: Update usage badge after response
                return;
            }
            this._view.webview.postMessage({
                type: 'error',
                content: String(error)
            });
        }

        this._view.webview.postMessage({ type: 'endResponse' });
        await this.updateStatus();  // v1.12.0: Update usage badge after response
    }

    /**
     * Process @filename references in a message and return augmented message with file contents
     */
    private async processFileReferences(content: string): Promise<{ message: string; files: { name: string; path: string }[] }> {
        // Match @filename patterns (word characters, dots, hyphens, slashes)
        const refPattern = /@([\w.\-\/]+)/g;
        const matches = [...content.matchAll(refPattern)];

        if (matches.length === 0) {
            return { message: content, files: [] };
        }

        const fs = require('fs');
        const resolvedFiles: { name: string; path: string; content: string }[] = [];
        let processedMessage = content;

        for (const match of matches) {
            const ref = match[1];
            const fullMatch = match[0];

            // Skip special context providers - let backend handle these
            // @tree = project structure, @git = git diff
            const specialContextProviders = ['tree', 'git'];
            if (specialContextProviders.includes(ref.toLowerCase())) {
                continue;  // Don't treat as file reference
            }

            // Try to resolve the file
            const files = await this.searchFiles(ref, 1);
            if (files.length > 0) {
                const filePath = files[0].fsPath;
                try {
                    const fileContent = fs.readFileSync(filePath, 'utf-8');
                    const fileName = filePath.split('/').pop() || ref;

                    resolvedFiles.push({
                        name: fileName,
                        path: filePath,
                        content: fileContent
                    });

                    // Replace @ref with just the filename in the message
                    processedMessage = processedMessage.replace(fullMatch, fileName);
                } catch (err) {
                    // File couldn't be read, leave reference as-is
                }
            }
        }

        if (resolvedFiles.length === 0) {
            return { message: content, files: [] };
        }

        // Build augmented message with file contents as context
        let augmentedMessage = processedMessage;
        augmentedMessage += '\n\n---\n**Referenced Files:**\n';

        for (const file of resolvedFiles) {
            const ext = file.name.split('.').pop() || '';
            augmentedMessage += `\n**${file.name}** (\`${file.path}\`):\n\`\`\`${ext}\n${file.content}\n\`\`\`\n`;
        }

        return {
            message: augmentedMessage,
            files: resolvedFiles.map(f => ({ name: f.name, path: f.path }))
        };
    }

    private handleStreamEvent(event: StreamEvent) {
        if (!this._view) { return; }

        switch (event.type) {
            case 'thinking':
                // Request received, processing
                this._view.webview.postMessage({
                    type: 'thinking',
                    content: event.content
                });
                break;
            case 'started':
                // API call started, waiting for tokens
                this._view.webview.postMessage({
                    type: 'started',
                    content: event.content
                });
                break;
            case 'reasoning_chunk':
                // v1.13.9: Reasoning tokens from DeepSeek R1, GPT-OSS 120B
                this._view.webview.postMessage({
                    type: 'reasoning_chunk',
                    content: event.content
                });
                break;
            case 'chunk':
                this._view.webview.postMessage({
                    type: 'chunk',
                    content: event.content
                });
                break;
            case 'tool_call':
                try {
                    const data = JSON.parse(event.content);
                    this._view.webview.postMessage({
                        type: 'toolCall',
                        tool: data.tool,
                        arguments: data.arguments,
                        verbose: this._backend.toolsVerbose  // v1.12.0: Pass verbose state
                    });
                } catch {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `🔧 Tool call: ${event.content}`
                    });
                }
                break;
            case 'tool_result':
                try {
                    const data = JSON.parse(event.content);
                    this._view.webview.postMessage({
                        type: 'toolResult',
                        tool: data.tool,
                        result: data.result,
                        verbose: this._backend.toolsVerbose  // v1.12.0: Pass verbose state
                    });
                } catch {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `📋 Tool result: ${event.content}`
                    });
                }
                break;
            case 'context_injected':
                try {
                    const data = JSON.parse(event.content);
                    this._view.webview.postMessage({
                        type: 'contextInjected',
                        source: data.source,
                        language: data.language,
                        size: data.size,
                        truncated: data.truncated
                    });
                } catch {
                    // Ignore parse errors
                }
                break;
            case 'consent_request':
                // Phase 1C: File edit consent request
                this.handleConsentRequest(event);
                break;
            case 'status':
                // v1.12.0: Checkpoint notifications and status messages
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: event.content
                });
                break;
            case 'agent_iteration':
                // v1.12.0: Agent loop iteration progress
                try {
                    const data = event.metadata || JSON.parse(event.content);
                    const iteration = data.iteration || 0;
                    const max = data.max || 10;
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `━━━ Iteration ${iteration}/${max} ━━━`
                    });
                } catch {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `━━━ Agent iteration ━━━`
                    });
                }
                break;
            case 'agent_complete':
                // v1.12.0: Agent task completed
                try {
                    const data = event.metadata || JSON.parse(event.content);
                    const summary = data.summary || '';
                    let message = '✅ Task completed!';
                    if (summary) {
                        message += `\nSummary: ${summary}`;
                    }
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: message
                    });
                } catch {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: '✅ Task completed!'
                    });
                }
                break;
            case 'agent_max_iterations':
                // v1.12.0: Agent reached max iterations
                try {
                    const data = event.metadata || JSON.parse(event.content);
                    const iterations = data.iterations || 10;
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `⚠️  Max iterations (${iterations}) reached\nTask may be incomplete. Review output above.`
                    });
                } catch {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: '⚠️  Max iterations reached'
                    });
                }
                break;
            case 'working_dir_changed':
                // v1.13.2: Working directory changed by tool
                try {
                    const newPath = event.content || event.metadata?.path;
                    if (newPath) {
                        this._view.webview.postMessage({
                            type: 'workingDirChanged',
                            path: newPath
                        });
                    }
                } catch {
                    // Ignore errors
                }
                break;
            case 'error':
                this._view.webview.postMessage({
                    type: 'error',
                    content: event.content
                });
                break;
            case 'done':
                // CRITICAL: When tools are used, stream_end contains the full response
                // but no chunk events were sent. We need to capture the content here.
                if (event.content && event.content.trim()) {
                    this._view.webview.postMessage({
                        type: 'fullResponse',
                        content: event.content
                    });
                } else {
                    // v1.13.2: Handle empty responses (common with GPT-OSS 120B after tool iterations)
                    // Notify webview that response is complete but empty
                    this._view.webview.postMessage({
                        type: 'emptyResponse'
                    });
                }
                break;
        }
    }

    private async handleConsentRequest(event: StreamEvent) {
        /**
         * Handle consent requests (file editing or shell commands)
         *
         * v1.11.0: File edit consent
         * v1.11.2: Shell command consent
         */
        try {
            const data = JSON.parse(event.content);

            // Determine consent type
            if (data.type === 'shell' || data.command) {
                // Shell command consent (v1.11.2)
                await this.handleShellConsentRequest(data);
            } else {
                // File edit consent (v1.11.0)
                await this.handleFileConsentRequest(data, event.metadata);
            }
        } catch (error) {
            console.error('Consent request error:', error);
        }
    }

    private async handleFileConsentRequest(data: any, metadata: any) {
        /**
         * Handle file edit consent request (Phase 1C: v1.11.0)
         *
         * Shows a keyboard-friendly QuickPick asking user for permission to edit a file.
         * Supports: Yes (this file), No, Always (all files), Never (block all)
         */
        try {
            const filePath = data.file_path || metadata?.file_path;

            if (!filePath) {
                console.error('File consent request missing file_path');
                return;
            }

            // Show keyboard-friendly QuickPick
            const items = [
                {
                    label: '$(check) Yes',
                    detail: 'Allow editing this file (y)',
                    value: 'y'
                },
                {
                    label: '$(x) No',
                    detail: 'Deny editing this file (n)',
                    value: 'n'
                },
                {
                    label: '$(check-all) Always',
                    detail: 'Allow all file edits this session (a)',
                    value: 'always'
                },
                {
                    label: '$(circle-slash) Never',
                    detail: 'Block all file edits this session (v)',
                    value: 'never'
                }
            ];

            const selected = await vscode.window.showQuickPick(items, {
                placeHolder: `📝 File Edit: ${filePath}`,
                title: 'File Edit Consent Required',
                ignoreFocusOut: true
            });

            // Map selection to response
            const response: 'y' | 'n' | 'always' | 'never' = (selected?.value as 'y' | 'n' | 'always' | 'never') || 'n';

            // Send consent response to server
            await this._backend.consent(filePath, response);

        } catch (error) {
            console.error('Consent request error:', error);
            // On error, deny for safety
            try {
                const filePath = data.file_path || metadata?.file_path;
                if (filePath) {
                    await this._backend.consent(filePath, 'n');
                }
            } catch {
                // Ignore - best effort
            }
        }
    }

    private async handleShellConsentRequest(data: any) {
        /**
         * Handle shell command consent request (v1.11.2)
         *
         * Shows a keyboard-friendly QuickPick asking user for permission to execute a shell command.
         * Displays command, working directory, and risk level.
         * Supports: Yes (this command), No, Always (all commands), Never (block all)
         */
        try {
            const command = data.command;
            const workingDir = data.working_dir || '.';
            const riskLevel = data.risk_level || 'unknown';

            if (!command) {
                console.error('Shell consent request missing command');
                return;
            }

            // Determine risk emoji and message
            let riskEmoji = '⚠️';
            let riskMessage = 'DANGEROUS';
            if (riskLevel === 'never') {
                riskEmoji = '🛑';
                riskMessage = 'BLOCKED - CATASTROPHIC';
            } else if (riskLevel === 'safe') {
                riskEmoji = '✅';
                riskMessage = 'SAFE';
            }

            // Show keyboard-friendly QuickPick
            const items = [
                {
                    label: '$(check) Yes',
                    detail: 'Allow this command (y)',
                    value: 'y'
                },
                {
                    label: '$(x) No',
                    detail: 'Deny this command (n)',
                    value: 'n'
                },
                {
                    label: '$(check-all) Always',
                    detail: 'Allow all shell commands this session (a)',
                    value: 'always'
                },
                {
                    label: '$(circle-slash) Never',
                    detail: 'Block all shell commands this session (v)',
                    value: 'never'
                }
            ];

            const selected = await vscode.window.showQuickPick(items, {
                placeHolder: `${riskEmoji} ${riskMessage}: ${command.length > 50 ? command.substring(0, 50) + '...' : command}`,
                title: `Shell Command Consent Required (in ${workingDir})`,
                ignoreFocusOut: true
            });

            // Map selection to response
            const response: 'y' | 'n' | 'always' | 'never' = (selected?.value as 'y' | 'n' | 'always' | 'never') || 'n';

            // Send shell consent response to server
            await this._backend.shellConsent(command, workingDir, response);

        } catch (error) {
            console.error('Shell consent request error:', error);
            // On error, deny for safety
            try {
                const command = data.command;
                const workingDir = data.working_dir || '.';
                if (command) {
                    await this._backend.shellConsent(command, workingDir, 'n');
                }
            } catch {
                // Ignore - best effort
            }
        }
    }

    private async handleSlashCommand(input: string) {
        if (!this._view) { return; }

        const parts = input.split(/\s+/);
        const command = parts[0].toLowerCase();
        const args = parts.slice(1);

        // Show command in chat
        this._view.webview.postMessage({
            type: 'commandMessage',
            content: input
        });

        try {
            switch (command) {
                case '/help':
                    await this.showHelp();
                    break;

                case '/clear':
                    await this._backend.clearHistory();
                    this._view.webview.postMessage({ type: 'cleared' });
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: '✓ Conversation history cleared'
                    });
                    break;

                case '/save':
                    const sessionName = await this._backend.saveSession();
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `✓ Session saved: ${sessionName}`
                    });
                    break;

                case '/export':
                    try {
                        const filename = args.length > 0 ? args[0] : undefined;
                        const filepath = await this._backend.exportAnswer(filename);
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: `✓ Answer exported to: ${filepath}`
                        });
                    } catch (error: any) {
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: `✗ ${error.message || 'Failed to export answer'}`
                        });
                    }
                    break;

                case '/load':
                    if (args.length === 0) {
                        // Show session picker
                        const sessions = await this._backend.getSessions();
                        if (sessions.length === 0) {
                            this._view.webview.postMessage({
                                type: 'systemMessage',
                                content: 'No saved sessions found'
                            });
                        } else {
                            const items = sessions.map(s => ({
                                label: s.name,
                                description: `${s.provider}/${s.model} - ${s.message_count} messages`,
                                detail: s.created_at
                            }));
                            const selected = await vscode.window.showQuickPick(items, {
                                placeHolder: 'Select a session to load'
                            });
                            if (selected) {
                                await this._backend.loadSession(selected.label);
                                await this.refreshHistory();
                                this._view.webview.postMessage({
                                    type: 'systemMessage',
                                    content: `✓ Loaded session: ${selected.label}`
                                });
                            }
                        }
                    } else {
                        const loaded = await this._backend.loadSession(args[0]);
                        if (loaded) {
                            await this.refreshHistory();
                            this._view.webview.postMessage({
                                type: 'systemMessage',
                                content: `✓ Loaded session: ${args[0]}`
                            });
                        } else {
                            this._view.webview.postMessage({
                                type: 'error',
                                content: `Session not found: ${args[0]}`
                            });
                        }
                    }
                    break;

                case '/sessions':
                    const sessions = await this._backend.getSessions();
                    if (sessions.length === 0) {
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: 'No saved sessions'
                        });
                    } else {
                        let sessionText = '**Saved Sessions:**\n\n';
                        sessionText += '| Session | Messages | Provider/Model | Created | Last Saved |\n';
                        sessionText += '|:--------|:--------:|:---------------|:--------|:-----------|\n';
                        sessions.forEach(s => {
                            const created = s.created_at ? s.created_at.slice(0, 16).replace('T', ' ') : 'unknown';
                            const saved = s.saved_at ? s.saved_at.slice(0, 16).replace('T', ' ') : '-';
                            sessionText += `| \`${s.name}\` | ${s.message_count} | ${s.provider}/${s.model} | ${created} | ${saved} |\n`;
                        });
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: sessionText
                        });
                    }
                    break;

                case '/model':
                    if (args.length === 0) {
                        // Show model picker
                        const models = await this._backend.getModels();
                        const items = models.map(m => ({
                            label: m.name,
                            description: m.description,
                            id: m.id
                        }));
                        const selected = await vscode.window.showQuickPick(items, {
                            placeHolder: 'Select a model'
                        });
                        if (selected) {
                            await this._backend.setModel((selected as any).id);
                            await this.updateStatus();
                            this._view.webview.postMessage({
                                type: 'systemMessage',
                                content: `✓ Switched to model: ${selected.label}`
                            });
                        }
                    } else if (args[0] === 'list') {
                        // List available models
                        const models = await this._backend.getModels();
                        const status = await this._backend.getStatus();
                        const modelList = models.map(m =>
                            `• **${m.id}**${m.id === status.model ? ' ✓' : ''} - ${m.description}`
                        ).join('\n');
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: `**Available Models:**\n${modelList}`
                        });
                    } else {
                        const set = await this._backend.setModel(args[0]);
                        if (set) {
                            await this.updateStatus();
                            this._view.webview.postMessage({
                                type: 'systemMessage',
                                content: `✓ Switched to model: ${args[0]}`
                            });
                        } else {
                            this._view.webview.postMessage({
                                type: 'error',
                                content: `Model not found: ${args[0]}`
                            });
                        }
                    }
                    break;

                case '/provider':
                    if (args.length === 0) {
                        // Show provider picker
                        const providers = await this._backend.getProviders();
                        const items = providers.map(p => ({
                            label: p.name,
                            description: p.has_api_key ? '' : '(no API key)',
                            id: p.id
                        }));
                        const selected = await vscode.window.showQuickPick(items, {
                            placeHolder: 'Select a provider'
                        });
                        if (selected) {
                            await this._backend.setProvider((selected as any).id);
                            await this.updateStatus();
                            this._view.webview.postMessage({
                                type: 'systemMessage',
                                content: `✓ Switched to provider: ${selected.label}`
                            });
                        }
                    } else if (args[0] === 'list') {
                        // List available providers
                        const providers = await this._backend.getProviders();
                        const status = await this._backend.getStatus();
                        const providerList = providers.map(p =>
                            `• **${p.id}**${p.id === status.provider ? ' ✓' : ''} - ${p.name}${p.has_api_key ? '' : ' (no API key)'}`
                        ).join('\n');
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: `**Available Providers:**\n${providerList}`
                        });
                    } else {
                        const set = await this._backend.setProvider(args[0]);
                        if (set) {
                            await this.updateStatus();
                            this._view.webview.postMessage({
                                type: 'systemMessage',
                                content: `✓ Switched to provider: ${args[0]}`
                            });
                        } else {
                            this._view.webview.postMessage({
                                type: 'error',
                                content: `Provider not found or no API key: ${args[0]}`
                            });
                        }
                    }
                    break;

                case '/tools':
                    await this.handleToolsCommand(args);
                    break;

                case '/show':
                case '/cat':
                    await this.handleShowCommand(args);
                    break;

                case '/cd':
                    await this.handleCdCommand(args);
                    break;

                case '/pwd':
                    await this.handlePwdCommand();
                    break;

                case '/usage':
                    await this.handleUsageCommand(args);
                    break;

                case '/status':
                    const status = await this._backend.getStatus();
                    const toolsStatus = await this._backend.getToolsStatus();
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `**Status:**
• Provider: ${status.provider}
• Model: ${status.model}
• Tools: ${toolsStatus.enabled ? `enabled (${toolsStatus.tool_count} tools)` : 'disabled'}
• Messages: ${status.message_count}`
                    });
                    break;

                // Coding task commands
                case '/generate':
                    await this.handleCodingTaskCommand('generate', args.join(' '));
                    break;

                case '/explain':
                    await this.handleCodingTaskCommand('explain', args.join(' '));
                    break;

                case '/test':
                    await this.handleCodingTaskCommand('test', args.join(' '));
                    break;

                case '/docs':
                    await this.handleCodingTaskCommand('docs', args.join(' '));
                    break;

                case '/debug':
                    await this.handleCodingTaskCommand('debug', args.join(' '));
                    break;

                case '/implement':
                    await this.handleCodingTaskCommand('implement', args.join(' '));
                    break;

                case '/spec':
                    await this.handleSpecCommand(args.join(' '));
                    break;

                case '/convert':
                    await this.handleConvertCommand(args);
                    break;

                case '/agent':
                    await this.handleAgentCommand(args);
                    break;

                case '/checkpoint':
                    await this.handleCheckpointCommand(args);
                    break;

                case '/context':
                    await this.handleContextCommand(args);
                    break;

                default:
                    this._view.webview.postMessage({
                        type: 'error',
                        content: `Unknown command: ${command}\nType /help for available commands.`
                    });
            }
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Command error: ${error}`
            });
        }
    }

    private async handleToolsCommand(args: string[]) {
        if (!this._view) { return; }

        const subcommand = args[0]?.toLowerCase() || 'status';

        switch (subcommand) {
            case 'enable':
                await this._backend.enableTools();
                const tools = await this._backend.listTools();
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `✓ Tools enabled (${tools.length} tools available)`
                });
                await this.updateStatus();
                break;

            case 'disable':
                await this._backend.disableTools();
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: '✓ Tools disabled'
                });
                await this.updateStatus();
                break;

            case 'list':
                const toolsList = await this._backend.listTools();
                if (toolsList.length === 0) {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: 'No tools available. Use `/tools enable` first.'
                    });
                } else {
                    const list = toolsList.map(t => `• **${t.name}**: ${t.description}`).join('\n');
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `**Available Tools:**\n${list}`
                    });
                }
                break;

            case 'config':
                if (args.length >= 3) {
                    const setting = args[1];
                    const value = args[2];
                    await this._backend.setToolConfig(setting, value);
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `✓ Set ${setting} = ${value}`
                    });
                } else {
                    // Show current config (matches TUI behavior)
                    const configStatus = await this._backend.getToolsStatus();
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `**Tool Configuration:**
• max_iterations: ${configStatus.max_iterations}

Usage: \`/tools config <setting> <value>\`
Available settings:
  max_iterations <number> - Max tool calls per query (1-50)`
                    });
                }
                break;

            case 'set':
                // v1.11.9: Add /tools set verbose on|off (matches TUI)
                if (args.length >= 3) {
                    const setting = args[1]?.toLowerCase();
                    const value = args[2]?.toLowerCase();
                    if (setting === 'verbose') {
                        const enabled = ['on', 'true', '1', 'yes'].includes(value);
                        await this._backend.setToolConfig('verbose', enabled ? 'on' : 'off');
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: enabled
                                ? '✓ Verbose tool logging enabled\n*Tool inputs and outputs will be displayed during execution*'
                                : '✓ Verbose tool logging disabled'
                        });
                    } else {
                        this._view.webview.postMessage({
                            type: 'error',
                            content: `Unknown setting: ${setting}\nAvailable: verbose`
                        });
                    }
                } else {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `**Tool Settings:**
• verbose: off

Usage: \`/tools set <setting> <value>\`
Available settings:
  verbose on|off - Show tool inputs and outputs`
                    });
                }
                break;

            case 'agent':
                // v1.11.9: Add /tools agent on|off (matches TUI)
                if (args.length >= 2) {
                    const action = args[1]?.toLowerCase();
                    if (['on', 'enable'].includes(action)) {
                        await this._backend.enableAgentMode();
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: '✓ Agent mode enabled\n*Tools auto-enabled. Use `/agent <task>` to start autonomous execution.*'
                        });
                        await this.updateAgentStatus();
                        await this.updateStatus();
                    } else if (['off', 'disable'].includes(action)) {
                        await this._backend.disableAgentMode();
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: '✓ Agent mode disabled'
                        });
                        await this.updateAgentStatus();
                    } else {
                        this._view.webview.postMessage({
                            type: 'error',
                            content: `Unknown action: ${action}\nUsage: /tools agent on|off`
                        });
                    }
                } else {
                    // Show current agent status
                    const agentStatus = await this._backend.getAgentStatus();
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `**Agent Mode:** ${agentStatus.agent_mode ? 'ON' : 'OFF'}

Usage: \`/tools agent on|off\`
       \`/agent <task>\` - Run autonomous task`
                    });
                }
                break;

            case 'help':
                if (args[1] === 'editing') {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: this.getFileEditingHelp()
                    });
                } else if (args[1]) {
                    // v1.11.9: Show help for specific tool (matches TUI)
                    await this.showToolHelp(args[1]);
                } else {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `**Tool Help:**
Usage: \`/tools help <tool-name>\` - Show help for a specific tool
       \`/tools help editing\` - Show file editing guide

Use \`/tools list\` to see available tool names.`
                    });
                }
                break;

            case 'status':
            default:
                const status = await this._backend.getToolsStatus();
                const available = status.enabled ? await this._backend.listTools() : [];
                const agentMode = await this._backend.getAgentStatus();
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `**Tools Status:**
• Enabled: ${status.enabled ? 'yes' : 'no'}
• Agent mode: ${agentMode.agent_mode ? 'ON' : 'OFF'}
• Available: ${available.length} tools
• Max iterations: ${status.max_iterations}
• Consent mode: ${status.consent_mode || 'default'}

Use \`/tools enable\` to enable tools, \`/tools list\` to see available tools.`
                });
                break;
        }
    }

    /**
     * Show help for a specific tool (v1.11.9)
     */
    private async showToolHelp(toolName: string) {
        if (!this._view) { return; }

        try {
            const toolsList = await this._backend.listTools();
            const tool = toolsList.find(t => t.name.toLowerCase() === toolName.toLowerCase());

            if (!tool) {
                this._view.webview.postMessage({
                    type: 'error',
                    content: `Tool not found: ${toolName}\nUse \`/tools list\` to see available tools.`
                });
                return;
            }

            // Format parameters if available
            let paramsInfo = '';
            if (tool.parameters && Object.keys(tool.parameters).length > 0) {
                const params = Object.entries(tool.parameters)
                    .map(([name, schema]: [string, any]) => {
                        const required = schema.required ? ' (required)' : '';
                        const desc = schema.description || '';
                        return `  • **${name}**${required}: ${desc}`;
                    })
                    .join('\n');
                paramsInfo = `\n\n**Parameters:**\n${params}`;
            }

            this._view.webview.postMessage({
                type: 'systemMessage',
                content: `**Tool: ${tool.name}**

${tool.description}${paramsInfo}`
            });
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Failed to get tool help: ${error}`
            });
        }
    }

    /**
     * Handle /agent command for autonomous task execution (v1.11.9)
     * Matches TUI behavior with iterative agent loop
     */
    private async handleAgentCommand(args: string[]) {
        if (!this._view) { return; }

        const task = args.join(' ').trim();

        // Handle /agent on|off as toggle commands (v1.11.9)
        if (task.toLowerCase() === 'on' || task.toLowerCase() === 'enable') {
            await this._backend.enableAgentMode();
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: '✓ Agent mode enabled\n*Tools auto-enabled. Use `/agent <task>` to start autonomous execution.*'
            });
            await this.updateAgentStatus();
            await this.updateStatus();
            return;
        }

        if (task.toLowerCase() === 'off' || task.toLowerCase() === 'disable') {
            await this._backend.disableAgentMode();
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: '✓ Agent mode disabled'
            });
            await this.updateAgentStatus();
            return;
        }

        if (!task) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Usage: /agent <task description>
       /agent on|off - Toggle agent mode
Example: /agent Fix the bug in auth.py
         /agent Review @git changes and fix issues`
            });
            return;
        }

        // v1.11.9: Get agent config from server
        const agentConfig = await this._backend.getAgentConfig();
        const minWords = agentConfig.min_task_words;
        const maxIterations = agentConfig.max_iterations;

        // v1.11.9: Reject vague/ambiguous single-word tasks for safety
        const words = task.split(/\s+/).filter(w => w.length > 0);
        if (words.length < minWords) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Task too vague: "${task}"

Agent tasks should be specific and descriptive (at least ${minWords} words).
Vague tasks can lead to unexpected AI interpretations.

Examples:
  ✓ /agent Fix the authentication bug in login.py
  ✓ /agent Review @git changes and suggest improvements
  ✗ /agent fix bug
  ✗ /agent do it`
            });
            return;
        }

        // Ensure agent mode is enabled (auto-enables tools)
        try {
            const agentStatus = await this._backend.getAgentStatus();
            if (!agentStatus.agent_mode) {
                await this._backend.enableAgentMode();
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: '✓ Agent mode enabled (tools auto-enabled)'
                });
                await this.updateAgentStatus();
            }
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Failed to enable agent mode: ${error}`
            });
            return;
        }

        this._view.webview.postMessage({
            type: 'systemMessage',
            content: `🤖 **Starting autonomous agent**
• Task: ${task}
• Max iterations: ${maxIterations}
• Press Escape to interrupt`
        });

        // Process @file references in task
        const { message: augmentedTask } = await this.processFileReferences(task);

        // Run agent loop
        for (let iteration = 1; iteration <= maxIterations; iteration++) {
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: `━━━ **Iteration ${iteration}/${maxIterations}** ━━━`
            });

            // Build prompt for this iteration
            const prompt = iteration === 1
                ? this.buildAgentPrompt(augmentedTask, iteration)
                : this.buildContinuationPrompt(augmentedTask, iteration);

            // Start streaming response
            this._view.webview.postMessage({ type: 'startResponse' });

            let response = '';
            let taskComplete = false;

            try {
                await this._backend.chat(
                    prompt,
                    (event: StreamEvent) => {
                        this.handleStreamEvent(event);
                        if (event.type === 'chunk' && event.content) {
                            response += event.content;
                        }
                    }
                );

                // Check for completion signal
                if (response.includes('TASK_COMPLETE:')) {
                    taskComplete = true;
                    const summaryParts = response.split('TASK_COMPLETE:');
                    const summary = summaryParts[1]?.trim().slice(0, 200) || 'Done';
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `✅ **Task completed!**
Summary: ${summary}${summary.length >= 200 ? '...' : ''}`
                    });
                    break;
                }
            } catch (error) {
                this._view.webview.postMessage({
                    type: 'error',
                    content: `Agent error: ${error}`
                });
                break;
            }

            if (taskComplete) break;
        }

        // If we exhausted iterations
        this._view.webview.postMessage({
            type: 'systemMessage',
            content: `⚠️ Max iterations (${maxIterations}) reached. Task may be incomplete.`
        });
    }

    /**
     * Build initial agent prompt (v1.11.9)
     */
    private buildAgentPrompt(task: string, iteration: number): string {
        return `You are an autonomous AI agent. Complete this task step by step:

**Task:** ${task}

**Instructions:**
1. Analyze what needs to be done
2. Use available tools to complete the task
3. When finished, respond with "TASK_COMPLETE: <brief summary>"
4. If you need more steps, explain what you did and what's next

**Iteration:** ${iteration}

Begin working on the task.`;
    }

    /**
     * Build continuation prompt for subsequent iterations (v1.11.9)
     */
    private buildContinuationPrompt(task: string, iteration: number): string {
        return `Continue working on the task.

**Original Task:** ${task}
**Iteration:** ${iteration}

Review your previous actions and continue. If the task is complete, respond with "TASK_COMPLETE: <brief summary>".`;
    }

    private async handleCodingTaskCommand(taskType: string, content: string) {
        if (!this._view) { return; }

        if (!content.trim()) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Usage: /${taskType} <content>\nExample: /${taskType} What does this function do?`
            });
            return;
        }

        // Process @file references in content
        const { message: augmentedContent } = await this.processFileReferences(content);

        // Get current editor context if available
        const editor = vscode.window.activeTextEditor;
        const language = editor?.document.languageId;
        const filename = editor?.document.fileName;

        // Start streaming response
        this._view.webview.postMessage({ type: 'startResponse' });

        try {
            await this._backend.codingTask(
                taskType,
                augmentedContent,
                language,
                filename,
                (event: StreamEvent) => this.handleStreamEvent(event)
            );
        } catch (error) {
            // Don't show interrupt as error - user initiated it
            if (error instanceof Error && error.message === 'Interrupted by user') {
                // Silent interrupt handling
                this._view.webview.postMessage({ type: 'endResponse' });
                await this.updateStatus();  // v1.12.0: Update usage badge after response
                return;
            }
            this._view.webview.postMessage({
                type: 'error',
                content: String(error)
            });
        }

        this._view.webview.postMessage({ type: 'endResponse' });
        await this.updateStatus();  // v1.12.0: Update usage badge after response
    }

    private async handleSpecCommand(specType: string) {
        if (!this._view) { return; }

        const SPEC_TEMPLATES: Record<string, string> = {
            'api': '**REST API Endpoint Specification Template:**\n\n**Endpoint**: [HTTP_METHOD] /api/v1/resource\n**Purpose**: [What this endpoint does]\n\n**Authentication**: [Required/Optional, type]\n\n**Request:**\n- Headers: [Content-Type, Authorization, etc.]\n- Body Schema:\n  ```json\n  {\n    "field1": "type (description)",\n    "field2": "type (description)"\n  }\n  ```\n\n**Response:**\n- Success (200):\n  ```json\n  {\n    "data": {},\n    "message": "Success"\n  }\n  ```\n- Error (4xx/5xx):\n  ```json\n  {\n    "error": "Error message"\n  }\n  ```\n\n**Validation Rules**: [List validation requirements]\n**Business Logic**: [Describe the processing steps]\n**Error Handling**: [How to handle specific errors]\n\n**Example Request:**\n```bash\ncurl -X POST /api/v1/resource \\\\\n  -H "Content-Type: application/json" \\\\\n  -d \'{"field1": "value"}\'\n```',
            'cli': '**CLI Tool Specification Template:**\n\n**Command**: program-name [command] [options] [arguments]\n**Purpose**: [What this tool does]\n\n**Commands:**\n- `command1` - [Description]\n- `command2` - [Description]\n\n**Options:**\n- `-f, --flag`: [Description, default value]\n- `-o, --option <value>`: [Description]\n\n**Arguments:**\n- `arg1`: [Description, required/optional]\n\n**Input/Output:**\n- Input: [stdin, files, arguments]\n- Output: [stdout, files, exit codes]\n\n**Error Handling:**\n- Exit code 0: Success\n- Exit code 1: [Error type]\n- Exit code 2: [Error type]\n\n**Examples:**\n```bash\nprogram-name command1 --flag value arg1\nprogram-name command2 -o option < input.txt > output.txt\n```\n\n**Dependencies**: [Required libraries, system tools]\n**Configuration**: [Config files, environment variables]',
            'lib': '**Library/Module Specification Template:**\n\n**Module Name**: module_name\n**Purpose**: [What this library provides]\n**Language**: [Python, JavaScript, Go, etc.]\n\n**Public API:**\n\n1. **Function/Class**: `name(param1, param2)`\n   - Purpose: [What it does]\n   - Parameters:\n     - `param1` (type): [Description]\n     - `param2` (type): [Description]\n   - Returns: [Type and description]\n   - Raises: [Exceptions/errors]\n   - Example:\n     ```python\n     result = name(value1, value2)\n     ```\n\n2. **Function/Class**: [Repeat for each public interface]\n\n**Internal Architecture:**\n- [Key components and their relationships]\n\n**Dependencies**: [External libraries needed]\n**Thread Safety**: [If applicable]\n**Performance Characteristics**: [Time/space complexity]\n\n**Usage Example:**\n```python\nfrom module_name import ClassName\n\nobj = ClassName(config)\nresult = obj.method(args)\n```',
            'algo': '**Algorithm Specification Template:**\n\n**Algorithm Name**: [Name or description]\n**Purpose**: [Problem it solves]\n**Language**: [Preferred language]\n\n**Input:**\n- Type: [Array, tree, graph, etc.]\n- Constraints: [Size limits, value ranges]\n- Format: [Specific structure]\n\n**Output:**\n- Type: [What the algorithm returns]\n- Format: [Structure of the result]\n\n**Requirements:**\n- Time Complexity: [Target: O(n log n), etc.]\n- Space Complexity: [Target: O(1), O(n), etc.]\n- Special Constraints: [In-place, iterative vs recursive]\n\n**Algorithm Approach:**\n[High-level description of the approach]\n- Step 1: [Description]\n- Step 2: [Description]\n- Step 3: [Description]\n\n**Edge Cases to Handle:**\n- Empty input\n- Single element\n- Duplicate values\n- [Other specific cases]\n\n**Test Cases:**\n```\nInput: [1, 2, 3]\nOutput: [expected]\n\nInput: []\nOutput: [expected]\n\nInput: [edge case]\nOutput: [expected]\n```',
            'ui': '**UI Component Specification Template:**\n\n**Component Name**: ComponentName\n**Purpose**: [What this component displays/does]\n**Framework**: [React, Vue, Angular, etc.]\n\n**Props/Inputs:**\n- `prop1` (type, required/optional): [Description, default]\n- `prop2` (type, required/optional): [Description, default]\n\n**State Management:**\n- [Internal state needed]\n- [External state/store]\n\n**Events/Callbacks:**\n- `onEvent1`: [When triggered, parameters]\n- `onEvent2`: [When triggered, parameters]\n\n**Visual Design:**\n- Layout: [Describe structure]\n- Styling: [CSS approach, theme]\n- Responsive: [Mobile/desktop behavior]\n\n**Behavior:**\n- User Interactions: [Click, hover, etc.]\n- Loading States: [How to show loading]\n- Error States: [How to display errors]\n\n**Accessibility:**\n- ARIA labels\n- Keyboard navigation\n- Screen reader support\n\n**Example Usage:**\n```jsx\n<ComponentName\n  prop1="value"\n  prop2={data}\n  onEvent1={handler}\n/>\n```'
        };

        const SPEC_GUIDELINES = '# Specification Guidelines for Best Outcomes\n\nWriting clear, detailed specifications helps generate better code implementations. Follow this structure:\n\n## 1. Overview\n- **What**: Brief description of what you\'re building\n- **Why**: Purpose and problem it solves\n- **Language/Framework**: Specify the technology stack\n\n## 2. Requirements\n### Functional Requirements\n- List specific features and behaviors\n- Define input/output expectations\n- Specify data structures and formats\n\n### Non-Functional Requirements\n- Performance expectations\n- Security considerations\n- Scalability needs\n- Error handling requirements\n\n## 3. Technical Details\n- API signatures or interfaces\n- Data models/schemas\n- External dependencies\n- Configuration needs\n\n## 4. Constraints & Assumptions\n- Platform limitations\n- Library/version constraints\n- Assumptions about the environment\n\n## 5. Examples\n- Sample inputs and expected outputs\n- Usage scenarios\n- Edge cases to consider\n\n---\n\n## Quick Templates\n\nUse `/spec <type>` to see templates for specific implementation types:\n- `/spec api` - REST API endpoint\n- `/spec cli` - Command-line tool\n- `/spec lib` - Library/module\n- `/spec algo` - Algorithm implementation\n- `/spec ui` - UI component';

        const type = specType.trim().toLowerCase();

        if (!type) {
            // Show guidelines
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: SPEC_GUIDELINES
            });
        } else if (type in SPEC_TEMPLATES) {
            // Show specific template
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: SPEC_TEMPLATES[type]
            });
        } else {
            this._view.webview.postMessage({
                type: 'error',
                content: `Unknown spec type: ${type}\n\nAvailable types: api, cli, lib, algo, ui\nOr use /spec without arguments for guidelines.`
            });
        }
    }

    private async handleConvertCommand(args: string[]) {
        if (!this._view) { return; }

        if (args.length < 3) {
            this._view.webview.postMessage({
                type: 'error',
                content: 'Usage: /convert <source-lang> <target-lang> <code or @file>\n\nExamples:\n  /convert python javascript @utils.py\n  /convert go rust \'func hello() { fmt.Println("Hi") }\''
            });
            return;
        }

        const sourceLang = args[0];
        const targetLang = args[1];
        const codeOrFile = args.slice(2).join(' ');

        // Process @file references
        const { message: augmentedContent } = await this.processFileReferences(codeOrFile);

        const taskMessage = `Convert the following ${sourceLang} code to ${targetLang}:\n\n\`\`\`${sourceLang}\n${augmentedContent}\n\`\`\``;

        // Start streaming response
        this._view.webview.postMessage({ type: 'startResponse' });

        try {
            await this._backend.codingTask(
                'convert',
                taskMessage,
                undefined,
                undefined,
                (event: StreamEvent) => this.handleStreamEvent(event)
            );
        } catch (error) {
            // Don't show interrupt as error - user initiated it
            if (error instanceof Error && error.message === 'Interrupted by user') {
                this._view.webview.postMessage({ type: 'endResponse' });
                await this.updateStatus();  // v1.12.0: Update usage badge after response
                return;
            }
            this._view.webview.postMessage({
                type: 'error',
                content: String(error)
            });
        }

        this._view.webview.postMessage({ type: 'endResponse' });
        await this.updateStatus();  // v1.12.0: Update usage badge after response
    }

    /**
     * Handle /checkpoint command for checkpoint management (v1.12.4)
     */
    private async handleCheckpointCommand(args: string[]) {
        if (!this._view) { return; }

        const subcommand = args[0]?.toLowerCase() || 'status';

        try {
            switch (subcommand) {
                case 'status':
                    const status = await this._backend.getCheckpointStatus();
                    let statusMsg = '**Checkpoint Status**\n';
                    const backendDisplay = status.backend === 'git' ? '🟢 git (atomic)' :
                                          status.backend === 'file' ? '🟡 file (snapshot)' :
                                          '🔴 none (disabled)';
                    statusMsg += `• Backend: ${backendDisplay}\n`;
                    statusMsg += `• Enabled: ${status.enabled ? 'Yes' : 'No'}\n`;
                    if (status.last_checkpoint) {
                        const cpId = status.last_checkpoint.substring(0, 8);
                        const validity = status.is_valid ? '✓ valid' : '⚠ stale';
                        statusMsg += `• Last checkpoint: \`${cpId}\` (${validity})\n`;
                        if (!status.is_valid) {
                            statusMsg += `  ${status.validity_reason}\n`;
                        }
                    } else {
                        statusMsg += '• Last checkpoint: None\n';
                    }
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: statusMsg
                    });
                    break;

                case 'list':
                    const result = await this._backend.listCheckpoints(10);
                    if (result.checkpoints.length === 0) {
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: 'No checkpoints found.\nRun an `/agent` task to create checkpoints.'
                        });
                    } else {
                        let listMsg = '**Recent Checkpoints**\n';
                        result.checkpoints.forEach((cp, i) => {
                            const cpId = cp.id.substring(0, 8);
                            const ts = cp.timestamp.substring(0, 19);
                            const desc = cp.description.substring(0, 50);
                            listMsg += `${i + 1}. \`${cpId}\`  ${ts}  ${desc}\n`;
                        });
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: listMsg
                        });
                    }
                    break;

                case 'backend':
                    const backend = args[1]?.toLowerCase() as 'git' | 'file' | 'auto' | 'none';
                    if (!backend) {
                        const currentStatus = await this._backend.getCheckpointStatus();
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: `Current backend: **${currentStatus.backend}**\n\nUsage: \`/checkpoint backend <git|file|auto|none>\``
                        });
                    } else if (!['git', 'file', 'auto', 'none'].includes(backend)) {
                        this._view.webview.postMessage({
                            type: 'error',
                            content: `Invalid backend: ${backend}\nValid options: git, file, auto, none`
                        });
                    } else {
                        const backendResult = await this._backend.setCheckpointBackend(backend);
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: `✓ Checkpoint backend set to: **${backendResult.backend}**`
                        });
                    }
                    break;

                case 'clear':
                    const clearStatus = await this._backend.getCheckpointStatus();
                    if (clearStatus.backend !== 'file') {
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: `Clear only applies to file-based checkpoints.\nCurrent backend: ${clearStatus.backend}`
                        });
                    } else {
                        const confirm = await vscode.window.showWarningMessage(
                            'Clear all file-based checkpoints?',
                            { modal: true },
                            'Clear'
                        );
                        if (confirm === 'Clear') {
                            const clearResult = await this._backend.clearFileCheckpoints(0);
                            this._view.webview.postMessage({
                                type: 'systemMessage',
                                content: `✓ Cleared ${clearResult.removed} checkpoint(s)`
                            });
                        }
                    }
                    break;

                case 'info':
                    const cpId = args[1];
                    if (!cpId) {
                        this._view.webview.postMessage({
                            type: 'error',
                            content: 'Usage: `/checkpoint info <checkpoint_id>`\nUse `/checkpoint list` to see available checkpoints.'
                        });
                    } else {
                        const checkpoints = await this._backend.listCheckpoints(20);
                        const matching = checkpoints.checkpoints.find(cp => cp.id.startsWith(cpId));
                        if (!matching) {
                            this._view.webview.postMessage({
                                type: 'error',
                                content: `Checkpoint not found: ${cpId}\nUse \`/checkpoint list\` to see available checkpoints.`
                            });
                        } else {
                            let infoMsg = '**Checkpoint Details**\n';
                            infoMsg += `• ID: \`${matching.id}\`\n`;
                            infoMsg += `• Description: ${matching.description}\n`;
                            infoMsg += `• Timestamp: ${matching.timestamp}\n`;
                            this._view.webview.postMessage({
                                type: 'systemMessage',
                                content: infoMsg
                            });
                        }
                    }
                    break;

                case 'undo':
                    // Delegate to existing undo functionality
                    const undoResult = await this._backend.undoCheckpoint();
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: undoResult.success
                            ? `✓ ${undoResult.message}`
                            : `✗ ${undoResult.message}`
                    });
                    break;

                default:
                    this._view.webview.postMessage({
                        type: 'error',
                        content: `Unknown subcommand: ${subcommand}\nAvailable: status, list, backend, clear, info, undo`
                    });
            }
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Checkpoint error: ${error}`
            });
        }
    }

    /**
     * Handle /context command - show context usage and injected files (v1.13.9)
     */
    private async handleContextCommand(args: string[]) {
        if (!this._view) { return; }

        const subcommand = args[0]?.toLowerCase();

        try {
            if (subcommand === 'clear') {
                // Clear injected contexts
                const result = await this._backend.clearContextInjections();
                if (result.removed_count > 0) {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `✓ Cleared ${result.removed_count} injected context(s) from conversation.`
                    });
                } else {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: 'No injected contexts to clear.'
                    });
                }
                // Update status to refresh context badge
                await this.updateStatus();
            } else {
                // Show context usage info
                const info = await this._backend.getContextInfo();

                // Build progress bar
                const percent = info.usage_percent;
                const barLength = 30;
                const filled = Math.min(barLength, Math.round(barLength * Math.min(percent, 100) / 100));
                const bar = '█'.repeat(filled) + '░'.repeat(barLength - filled);

                // Color indicator
                let colorIcon = '🟢';
                if (percent >= 100) { colorIcon = '🔴'; }
                else if (percent >= 80) { colorIcon = '🟡'; }

                let contextMsg = '**Context Usage:**\n';
                contextMsg += `  Estimated: ~${info.estimated_tokens.toLocaleString()} / ${info.context_limit.toLocaleString()} tokens (${percent.toFixed(1)}%)\n`;
                contextMsg += `  Model: ${info.model} (${info.provider})\n`;
                contextMsg += `  Messages: ${info.message_count}\n`;
                contextMsg += `  ${colorIcon} [${bar}] ${percent.toFixed(0)}%\n`;

                // Show injected files
                if (info.injected_contexts && info.injected_contexts.length > 0) {
                    contextMsg += `\n**Injected Contexts:** (${info.injected_tokens.toLocaleString()} tokens)\n`;
                    info.injected_contexts.forEach((ctx: { source: string; size: number; truncated: boolean }) => {
                        const sizeKB = (ctx.size / 1024).toFixed(1);
                        const truncated = ctx.truncated ? ' ⚠ truncated' : '';
                        contextMsg += `  • ${ctx.source} (${sizeKB} KB${truncated})\n`;
                    });
                    contextMsg += '\n*Tip: `/context clear` removes injected files, keeps chat*';
                }

                // Show tips if over limit
                if (percent >= 100) {
                    contextMsg += '\n\n**⚠ Over context limit!** Tips:\n';
                    contextMsg += '  • `/clear` - Start fresh session\n';
                    contextMsg += '  • `/save` - Save session before clearing\n';
                    contextMsg += '  • Consider a model with larger context\n';
                }

                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: contextMsg
                });
            }
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Context error: ${error}`
            });
        }
    }

    private async showHelp() {
        if (!this._view) { return; }

        // Use shared help generator for consistent output across Web App and VSCode
        let helpText = generateHelpText();

        // Add VSCode-specific keyboard shortcuts
        helpText += '\n**Keyboard Shortcuts:**\n';
        helpText += '- `Esc` - Stop streaming\n';
        helpText += '- `↑/↓` - Command history\n';
        helpText += '- `@file` - Reference a file\n';
        helpText += '- `@git` - Include git diff\n';
        helpText += '- `@tree` - Include project structure\n';

        this._view.webview.postMessage({
            type: 'systemMessage',
            content: helpText
        });
    }

    private async handleToggleTools(enable: boolean) {
        if (!this._view) { return; }

        try {
            if (enable) {
                await this._backend.enableTools();
                const tools = await this._backend.listTools();
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `✓ Tools enabled (${tools.length} tools available)`
                });
            } else {
                await this._backend.disableTools();
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: '✓ Tools disabled'
                });
            }

            // Save the setting to persist across restarts
            const config = vscode.workspace.getConfiguration('ppxai');
            await config.update('enableTools', enable, vscode.ConfigurationTarget.Global);

            await this.updateStatus();
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Failed to toggle tools: ${error}`
            });
        }
    }

    /**
     * Handle clear context request from webview badge click (v1.13.9)
     */
    private async handleClearContext() {
        if (!this._view) { return; }

        try {
            const result = await this._backend.clearContextInjections();
            if (result.removed_count > 0) {
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `✓ Cleared ${result.removed_count} injected context(s)`
                });
            } else {
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: 'No injected contexts to clear'
                });
            }
            // Update the context badge
            await this.updateContextBadge();
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Failed to clear context: ${error}`
            });
        }
    }

    /**
     * Update context badge with current usage (v1.13.9)
     */
    private async updateContextBadge() {
        if (!this._view) { return; }

        try {
            const info = await this._backend.getContextInfo();
            const percent = info.usage_percent || 0;

            // Determine badge state
            let badgeClass = '';
            let suffix = '';
            if (percent >= 100) {
                badgeClass = 'critical';
                suffix = '!';
            } else if (percent >= 80) {
                badgeClass = 'warning';
                suffix = '~';
            }

            this._view.webview.postMessage({
                type: 'updateContext',
                percent: percent,
                badgeClass: badgeClass,
                suffix: suffix
            });
        } catch (error) {
            // Silently ignore errors
        }
    }

    private async handleToggleDebugLog(enable: boolean) {
        if (!this._view) { return; }

        try {
            const status = await this._backend.setDebugLog(enable);

            this._view.webview.postMessage({
                type: 'systemMessage',
                content: `✓ Debug logging ${enable ? 'enabled' : 'disabled'}${status.log_file ? `\nLog file: ${status.log_file}` : ''}`
            });

            // Update the UI indicator
            this._view.webview.postMessage({
                type: 'debugLogStatus',
                enabled: status.enabled
            });
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Failed to toggle debug log: ${error}`
            });
        }
    }

    /**
     * Handle server start/stop toggle (v1.13.1)
     */
    private async handleToggleServer(stop: boolean) {
        if (!this._view) { return; }

        // Show connecting state
        this._view.webview.postMessage({
            type: 'serverStatus',
            connected: false,
            connecting: true
        });

        try {
            if (stop) {
                await stopServer();
                this._view.webview.postMessage({
                    type: 'serverStatus',
                    connected: false,
                    connecting: false
                });
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: '✓ Server stopped'
                });
            } else {
                const started = await startServer();
                this._view.webview.postMessage({
                    type: 'serverStatus',
                    connected: started,
                    connecting: false
                });
                if (started) {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: '✓ Server started successfully'
                    });
                    // Re-initialize after server starts
                    await this.initializeBackend();
                }
            }
        } catch (error) {
            this._view.webview.postMessage({
                type: 'serverStatus',
                connected: false,
                connecting: false
            });
            this._view.webview.postMessage({
                type: 'error',
                content: `Failed to toggle server: ${error}`
            });
        }
    }

    /**
     * Update server status in webview (v1.13.1)
     */
    public updateServerStatus(connected: boolean) {
        if (!this._view) { return; }
        this._view.webview.postMessage({
            type: 'serverStatus',
            connected: connected,
            connecting: false
        });
    }

    private async updateDebugLogStatus() {
        if (!this._view) { return; }

        try {
            const status = await this._backend.getDebugLogStatus();
            this._view.webview.postMessage({
                type: 'debugLogStatus',
                enabled: status.enabled
            });
        } catch (error) {
            // Silently fail - server might not support this endpoint yet
            console.error('Failed to get debug log status:', error);
        }
    }

    /**
     * Handle agent mode toggle (v1.11.8, v1.12.0: added checkpoint notification)
     */
    private async handleToggleAgent(enable: boolean) {
        if (!this._view) { return; }

        try {
            if (enable) {
                await this._backend.enableAgentMode();

                // Get updated status with checkpoint info
                const agentStatus = await this._backend.getAgentStatus();
                const checkpoint = agentStatus.checkpoint;

                // Build notification message based on checkpoint backend
                let message = '✓ Agent mode enabled (tools auto-enabled)\n*Use natural language to assign autonomous tasks*';

                if (checkpoint) {
                    if (checkpoint.backend === 'git') {
                        message = '🔒 Agent Mode enabled with Git checkpoints\n• Changes will be auto-committed before each task\n• Use Undo button to revert the last agent task atomically';
                    } else if (checkpoint.backend === 'file') {
                        message = '⚠️  Agent Mode enabled with File checkpoints\n• Snapshots will be saved to ~/.ppxai/checkpoints\n• Use Undo button to restore from snapshot\n• Tip: Initialize git repo for atomic commits';
                    } else {
                        message = '⚠️  Agent Mode enabled WITHOUT checkpoints\n• Changes CANNOT be undone\n• Initialize git repo or enable file backend for safety';
                    }
                }

                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: message
                });
            } else {
                await this._backend.disableAgentMode();
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: '✓ Agent mode disabled'
                });
            }

            // Update the UI indicator with checkpoint status
            await this.updateAgentStatus();

            // Also update status since agent mode affects tools
            await this.updateStatus();
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Failed to toggle agent mode: ${error}`
            });
        }
    }

    /**
     * Update agent mode status in UI (v1.11.8, v1.12.0: added checkpoint info)
     */
    private async updateAgentStatus() {
        if (!this._view) { return; }

        try {
            const status = await this._backend.getAgentStatus();
            this._view.webview.postMessage({
                type: 'agentStatus',
                enabled: status.agent_mode,
                checkpoint: status.checkpoint || null
            });
        } catch (error) {
            // Silently fail - server might not support this endpoint yet
            console.error('Failed to get agent status:', error);
        }
    }

    /**
     * Handle streaming interrupt (v1.12.0: added checkpoint recovery)
     */
    private async handleInterrupt() {
        if (!this._view) { return; }

        try {
            // Interrupt the stream first
            await this._backend.interrupt();

            // Check if agent mode is active and has checkpoint
            const agentStatus = await this._backend.getAgentStatus();
            if (!agentStatus.agent_mode || !agentStatus.checkpoint || !agentStatus.checkpoint.last_checkpoint) {
                // Not in agent mode or no checkpoint - just interrupt silently
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: '⚠️  Streaming interrupted by user'
                });
                return;
            }

            const checkpoint = agentStatus.checkpoint;
            const shortId = checkpoint.last_checkpoint && checkpoint.last_checkpoint.length > 8
                ? checkpoint.last_checkpoint.substring(0, 8)
                : checkpoint.last_checkpoint || '';

            // Show interrupt recovery prompt
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: '⚠️  Agent interrupted by user'
            });

            const action = await vscode.window.showWarningMessage(
                `Agent Task Interrupted\n\nAgent task incomplete due to interrupt.\n\nCheckpoint: ${shortId}\nBackend: ${checkpoint.backend}\n\nRollback all changes from this task?`,
                { modal: true },
                'Rollback to Checkpoint',
                'Keep Partial Changes'
            );

            if (action === 'Rollback to Checkpoint') {
                // Perform rollback
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: 'Rolling back changes...'
                });

                const result = await this._backend.undoCheckpoint();

                if (result.success) {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `✓ Checkpoint reverted successfully`
                    });

                    // For git backend, offer cleanup of uncommitted changes
                    if (checkpoint.backend === 'git') {
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: '⚠️  Note: Any uncommitted changes from the interrupted task may remain.\nReview your working directory and run git status.'
                        });
                    }

                    // Update status
                    await this.updateAgentStatus();
                } else {
                    this._view.webview.postMessage({
                        type: 'error',
                        content: `✗ Rollback failed: ${result.message}`
                    });
                }
            } else {
                // User chose to keep partial changes
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: '⚠️  Partial changes preserved\nUse /undo command or Undo button to rollback if needed'
                });
            }
        } catch (error) {
            // Silently handle interrupt errors - user initiated
            console.error('Interrupt handling error:', error);
        }
    }

    /**
     * Handle checkpoint undo (v1.12.0, v1.12.1: validity check)
     */
    private async handleUndoCheckpoint() {
        if (!this._view) { return; }

        try {
            // Get current checkpoint status first
            const agentStatus = await this._backend.getAgentStatus();
            const checkpoint = agentStatus.checkpoint;

            if (!checkpoint || !checkpoint.last_checkpoint) {
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: '⚠️  No checkpoint to undo'
                });
                return;
            }

            // v1.12.1: Check if checkpoint is still valid (not stale)
            if (checkpoint.is_valid === false) {
                const shortId = checkpoint.last_checkpoint.substring(0, 8);
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `⚠️  Cannot undo: ${checkpoint.validity_reason || 'Checkpoint is stale'}\n\nNew commits have been made since the agent task.\nUse 'git revert ${shortId}' manually if you still want to revert.`
                });
                return;
            }

            // Show confirmation prompt
            const confirmed = await vscode.window.showWarningMessage(
                `Undo Last Agent Task?\n\nThis will revert all changes made by the last agent task.\n\nBackend: ${checkpoint.backend}\nCheckpoint: ${checkpoint.last_checkpoint.substring(0, 8)}`,
                { modal: true },
                'Undo'
            );

            if (confirmed !== 'Undo') {
                return;
            }

            // Perform undo
            const result = await this._backend.undoCheckpoint();

            if (result.success) {
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `✓ ${result.message}`
                });

                // Check if git backend with uncommitted changes
                if (checkpoint.backend === 'git') {
                    // TODO: Add second prompt for git cleanup if needed
                    // For now, just show success
                }

                // Update status
                await this.updateAgentStatus();
            } else {
                this._view.webview.postMessage({
                    type: 'error',
                    content: `✗ Undo failed: ${result.message}`
                });
            }
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Failed to undo checkpoint: ${error}`
            });
        }
    }

    /**
     * Get workspace context for AI awareness (v1.11.2)
     * Injects workspace information so AI knows where it's working
     */
    private async getWorkspaceContext(): Promise<string> {
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (!workspaceFolders || workspaceFolders.length === 0) {
            return "";  // No context if no workspace open
        }

        const workspaceRoot = workspaceFolders[0].uri.fsPath;
        const workspaceName = workspaceFolders[0].name;

        return `[Context: Working in VSCode workspace "${workspaceName}" at ${workspaceRoot}]\n\n`;
    }

    /**
     * Update workspace display in UI (v1.11.2)
     */
    private async updateWorkspaceDisplay() {
        if (!this._view) { return; }

        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (!workspaceFolders || workspaceFolders.length === 0) {
            // No workspace - hide display
            this._view.webview.postMessage({
                type: 'workspaceInfo',
                hasWorkspace: false
            });
            return;
        }

        const workspaceRoot = workspaceFolders[0].uri.fsPath;
        const workspaceName = workspaceFolders[0].name;

        this._view.webview.postMessage({
            type: 'workspaceInfo',
            hasWorkspace: true,
            path: workspaceRoot,
            name: workspaceName
        });
    }

    private async handleSaveAnswer(content: string) {
        if (!this._view) { return; }

        try {
            // Generate filename with timestamp
            const now = new Date();
            const timestamp = now.toISOString().replace(/[:.]/g, '-').slice(0, -5);
            const filename = `answer_${timestamp}.md`;

            // Save to ~/.ppxai/exports/
            const homeDir = require('os').homedir();
            const exportsDir = vscode.Uri.file(`${homeDir}/.ppxai/exports`);

            // Ensure exports directory exists
            try {
                await vscode.workspace.fs.createDirectory(exportsDir);
            } catch (error) {
                // Directory may already exist, ignore error
            }

            const uri = vscode.Uri.joinPath(exportsDir, filename);

            // Write content to file
            await vscode.workspace.fs.writeFile(uri, Buffer.from(content, 'utf-8'));

            // Show success message with option to open
            const action = await vscode.window.showInformationMessage(
                `Answer exported to ${uri.fsPath}`,
                'Open File'
            );

            if (action === 'Open File') {
                const doc = await vscode.workspace.openTextDocument(uri);
                await vscode.window.showTextDocument(doc);
            }
        } catch (error) {
            vscode.window.showErrorMessage(`Failed to export answer: ${error}`);
        }
    }

    private async searchFiles(query: string, maxResults: number = 10): Promise<vscode.Uri[]> {
        // Remove @ prefix if present
        query = query.replace(/^@/, '').trim();

        // Build glob pattern from query
        const parts = query.toLowerCase().replace(/[-_]/g, ' ').split(/\s+/).filter(p => p);

        // Search using VS Code's findFiles
        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (!workspaceFolders) { return []; }

        try {
            // Try exact match first
            const exactMatches = await vscode.workspace.findFiles(`**/${query}`, '**/node_modules/**', 5);
            if (exactMatches.length > 0) {
                return exactMatches;
            }

            // Try glob pattern with wildcards
            const globPattern = `**/*${parts.join('*')}*`;
            const matches = await vscode.workspace.findFiles(globPattern, '**/node_modules/**', maxResults);

            // Sort by relevance (prefer shorter paths and exact filename matches)
            const queryLower = query.toLowerCase();
            matches.sort((a, b) => {
                const aName = a.path.split('/').pop()?.toLowerCase() || '';
                const bName = b.path.split('/').pop()?.toLowerCase() || '';
                // Exact filename match wins
                if (aName === queryLower && bName !== queryLower) { return -1; }
                if (bName === queryLower && aName !== queryLower) { return 1; }
                // Prefer shorter paths
                return a.path.length - b.path.length;
            });

            return matches;
        } catch {
            return [];
        }
    }

    /**
     * Handle /usage command with sub-commands (v1.12.3)
     *
     * Sub-commands:
     *   /usage              - Show session usage with per-model breakdown
     *   /usage 24h          - Show usage for last 24 hours (v1.12.3)
     *   /usage week         - Show usage for last 7 days (v1.12.3)
     *   /usage month        - Show usage for last 30 days (v1.12.3)
     *   /usage year         - Show usage for last 365 days (v1.12.3)
     *   /usage all          - Show all-time usage (v1.12.3)
     *   /usage show session - Status shows session totals (default)
     *   /usage show provider - Status shows current provider totals
     *   /usage show model   - Status shows current model totals
     *   /usage show off     - Hide usage from status
     *   /usage reset        - Reset all usage counters
     */
    private async handleUsageCommand(args: string[]) {
        if (!this._view) { return; }

        const subCommand = args[0]?.toLowerCase();

        // Time-based period arguments (v1.12.3)
        const timePeriods = ['24h', 'week', 'month', 'year', 'all'];
        if (subCommand && timePeriods.includes(subCommand)) {
            await this.handleGlobalUsageReport(subCommand);
            return;
        }

        if (!subCommand) {
            // Default: show session usage with per-model breakdown
            const usage = await this._backend.getUsage();
            let content = `**Session Usage Statistics:**

- Total tokens: ${usage.total_tokens.toLocaleString()} (${usage.prompt_tokens.toLocaleString()}↓ / ${usage.completion_tokens.toLocaleString()}↑)
- Estimated cost: $${usage.estimated_cost.toFixed(4)}`;

            // Add per-model breakdown as table if available
            if (usage.by_model && Object.keys(usage.by_model).length > 0) {
                content += '\n\n**Usage by Model:**\n\n';
                content += '| Provider | Model | In | Out | Cost |\n';
                content += '|:---------|:------|---:|----:|-----:|\n';
                for (const [key, stats] of Object.entries(usage.by_model).sort()) {
                    const [provider, model] = key.split('/', 2);
                    content += `| ${provider} | ${model} | ${stats.prompt_tokens.toLocaleString()} | ${stats.completion_tokens.toLocaleString()} | $${stats.estimated_cost.toFixed(4)} |\n`;
                }
                // Add totals row
                content += `| **TOTAL** | | **${usage.prompt_tokens.toLocaleString()}** | **${usage.completion_tokens.toLocaleString()}** | **$${usage.estimated_cost.toFixed(4)}** |\n`;
            }

            // Show current display mode
            content += `\nDisplay mode: \`${usage.display_mode || 'session'}\`
Use \`/usage show <session|provider|model|off>\` to change.`;

            this._view.webview.postMessage({ type: 'systemMessage', content });
            return;
        }

        if (subCommand === 'show') {
            const mode = args[1]?.toLowerCase();
            const validModes = ['session', 'provider', 'model', 'off'];

            if (!mode) {
                const currentMode = await this._backend.getUsageDisplayMode();
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `Usage: \`/usage show <session|provider|model|off>\`\nCurrent mode: \`${currentMode.mode}\``
                });
                return;
            }

            if (!validModes.includes(mode)) {
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `Invalid mode: \`${mode}\`\nValid modes: ${validModes.join(', ')}`
                });
                return;
            }

            try {
                await this._backend.setUsageDisplayMode(mode);
                const modeDescriptions: Record<string, string> = {
                    'session': 'session totals',
                    'provider': 'current provider totals',
                    'model': 'current model totals',
                    'off': 'hidden'
                };
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `Usage display set to: **${modeDescriptions[mode]}**`
                });
            } catch (error) {
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `Failed to set display mode: ${error}`
                });
            }
            return;
        }

        if (subCommand === 'reset') {
            try {
                await this._backend.resetUsage();
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: 'Usage counters reset to zero.'
                });
            } catch (error) {
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `Failed to reset usage: ${error}`
                });
            }
            return;
        }

        // Unknown sub-command
        this._view.webview.postMessage({
            type: 'systemMessage',
            content: `Unknown sub-command: \`${subCommand}\`\nAvailable: \`24h\`, \`week\`, \`month\`, \`year\`, \`all\`, \`show\`, \`reset\``
        });
    }

    /**
     * Display global usage report for a time period (v1.12.3)
     */
    private async handleGlobalUsageReport(period: string) {
        if (!this._view) { return; }

        const periodLabels: Record<string, string> = {
            '24h': 'Last 24 Hours',
            'week': 'Last 7 Days',
            'month': 'Last 30 Days',
            'year': 'Last 365 Days',
            'all': 'All Time'
        };

        try {
            const report = await this._backend.getUsageReport(period);

            let content = `**Usage Report: ${periodLabels[period] || period}**\n`;
            if (report.start_date) {
                content += `*Period: ${report.start_date} to ${report.end_date}*\n\n`;
            } else {
                content += `*Period: All recorded sessions*\n\n`;
            }

            content += `• Sessions: ${report.session_count}\n`;
            content += `• Total tokens: ${report.total_tokens.toLocaleString()}\n`;
            content += `• Estimated cost: $${report.total_cost.toFixed(4)}\n`;

            // By provider breakdown
            if (report.by_provider && Object.keys(report.by_provider).length > 0) {
                content += '\n**By Provider:**\n\n';
                content += '| Provider | Tokens | Cost | Sessions |\n';
                content += '|:---------|-------:|-----:|---------:|\n';
                for (const [provider, stats] of Object.entries(report.by_provider).sort()) {
                    content += `| ${provider} | ${stats.total_tokens.toLocaleString()} | $${stats.estimated_cost.toFixed(4)} | ${stats.session_count} |\n`;
                }
            }

            // By model breakdown
            if (report.by_model && Object.keys(report.by_model).length > 0) {
                content += '\n**By Model:**\n\n';
                content += '| Provider | Model | In | Out | Cost |\n';
                content += '|:---------|:------|---:|----:|-----:|\n';
                for (const [key, stats] of Object.entries(report.by_model).sort()) {
                    const [provider, model] = key.split('/', 2);
                    content += `| ${provider} | ${model || key} | ${stats.prompt_tokens.toLocaleString()} | ${stats.completion_tokens.toLocaleString()} | $${stats.estimated_cost.toFixed(4)} |\n`;
                }
            }

            // Recent sessions (limit to 5)
            if (report.sessions && report.sessions.length > 0) {
                content += '\n**Recent Sessions:**\n';
                for (const session of report.sessions.slice(0, 5)) {
                    const ended = session.ended_at?.substring(0, 16).replace('T', ' ') || 'unknown';
                    content += `• ${ended} - ${session.total_tokens.toLocaleString()} tokens, $${session.total_cost.toFixed(4)}\n`;
                }
            }

            this._view.webview.postMessage({ type: 'systemMessage', content });
        } catch (error) {
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: `Failed to get usage report: ${error}`
            });
        }
    }

    private async handleShowCommand(args: string[]) {
        if (!this._view) { return; }

        if (args.length === 0) {
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: 'Usage: `/show <filepath>` or `/show @<search>`\n\nExamples:\n- `/show README.md`\n- `/show @architecture` (searches for files)\n- `/show docs/README.md`'
            });
            return;
        }

        const startTime = Date.now();
        let query = args.join(' ');
        const workspaceFolders = vscode.workspace.workspaceFolders;

        // Extract @reference if present (ignore trailing words like "file", "in docs", etc.)
        const atMatch = query.match(/@([\w.\-\/]+)/);
        if (atMatch) {
            query = atMatch[1];  // Use just the reference without @
        }

        const fs = require('fs');
        const pathModule = require('path');

        let fullPath: string | undefined;

        // Check if it's a direct path first
        if (query.startsWith('/') || query.startsWith('~')) {
            fullPath = query;
        } else if (workspaceFolders && workspaceFolders.length > 0) {
            const directPath = vscode.Uri.joinPath(workspaceFolders[0].uri, query).fsPath;
            if (fs.existsSync(directPath)) {
                fullPath = directPath;
            }
        }

        // If not found, search for files
        if (!fullPath || !fs.existsSync(fullPath)) {
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: `*Searching for '${query}'...*`
            });

            const matches = await this.searchFiles(query);

            if (matches.length === 0) {
                this._view.webview.postMessage({
                    type: 'error',
                    content: `No files found matching: ${query}`
                });
                return;
            }

            if (matches.length === 1) {
                fullPath = matches[0].fsPath;
                const relPath = workspaceFolders
                    ? pathModule.relative(workspaceFolders[0].uri.fsPath, fullPath)
                    : matches[0].path.split('/').pop();
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `*Found: ${relPath}*`
                });
            } else {
                // Multiple matches - show list
                const list = matches.slice(0, 10).map((m, i) => {
                    const relPath = workspaceFolders
                        ? pathModule.relative(workspaceFolders[0].uri.fsPath, m.fsPath)
                        : m.path;
                    return `${i + 1}. \`${relPath}\``;
                }).join('\n');

                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `**Multiple files found (${matches.length}):**\n${list}\n\n*Use exact path: /show <path>*`
                });
                return;
            }
        }

        try {
            if (!fs.existsSync(fullPath)) {
                this._view.webview.postMessage({
                    type: 'error',
                    content: `File not found: ${query}`
                });
                return;
            }

            const stats = fs.statSync(fullPath);
            if (!stats.isFile()) {
                this._view.webview.postMessage({
                    type: 'error',
                    content: `Not a file: ${query}`
                });
                return;
            }

            // Open file in VSCode editor (beside current editor)
            const uri = vscode.Uri.file(fullPath);
            const doc = await vscode.workspace.openTextDocument(uri);
            await vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside);

            const filename = pathModule.basename(fullPath);
            const sizeKB = (stats.size / 1024).toFixed(1);
            const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);

            this._view.webview.postMessage({
                type: 'systemMessage',
                content: `📂 Opened **${filename}** (${sizeKB} KB) in editor • *${elapsed}s*`
            });
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Error opening file: ${error}`
            });
        }
    }

    private async handleCdCommand(args: string[]) {
        if (!this._view) { return; }

        if (args.length === 0) {
            // No args - show current directory (same as /pwd)
            await this.handlePwdCommand();
            return;
        }

        const targetPath = args.join(' ');

        try {
            const result = await this._backend.setWorkingDir(targetPath);
            if (result.success) {
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `Working directory changed to: \`${result.path}\``
                });
                // Update the workspace display badge
                this._view.webview.postMessage({
                    type: 'workingDirChanged',
                    path: result.path
                });
            } else {
                this._view.webview.postMessage({
                    type: 'error',
                    content: `Failed to change directory: ${result.error || 'Unknown error'}`
                });
            }
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Failed to change directory: ${error}`
            });
        }
    }

    private async handlePwdCommand() {
        if (!this._view) { return; }

        try {
            const path = await this._backend.getWorkingDir();
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: `Current working directory: \`${path}\``
            });
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Failed to get working directory: ${error}`
            });
        }
    }

    public async sendCodingTask(
        taskType: string,
        content: string,
        language?: string,
        filename?: string
    ) {
        if (!this._view) {
            // Focus the view first
            await vscode.commands.executeCommand('ppxai.chatView.focus');
        }

        // Wait for view to be ready
        await new Promise(resolve => setTimeout(resolve, 500));

        if (!this._view) { return; }

        // Build task description
        const taskDescriptions: Record<string, string> = {
            explain: 'Explain this code',
            test: 'Generate tests for this code',
            docs: 'Generate documentation for this code',
            debug: 'Debug this error',
            implement: 'Implement this'
        };

        const taskMessage = taskDescriptions[taskType] || taskType;
        const contextInfo = filename ? ` (${filename.split('/').pop()})` : '';

        // Show user message
        this._view.webview.postMessage({
            type: 'userMessage',
            // v1.11.9: Increased from 500 to 2000 chars for better context
            content: `${taskMessage}${contextInfo}:\n\`\`\`${language || ''}\n${content.slice(0, 2000)}${content.length > 2000 ? '...' : ''}\n\`\`\``
        });

        // Start streaming response
        this._view.webview.postMessage({ type: 'startResponse' });

        try {
            await this._backend.codingTask(taskType, content, language, filename, (event) => {
                this.handleStreamEvent(event);
            });
        } catch (error) {
            // Don't show interrupt as error - user initiated it
            if (error instanceof Error && error.message === 'Interrupted by user') {
                // Silent interrupt handling
                this._view.webview.postMessage({ type: 'endResponse' });
                await this.updateStatus();  // v1.12.0: Update usage badge after response
                return;
            }
            this._view?.webview.postMessage({
                type: 'error',
                content: String(error)
            });
        }

        this._view.webview.postMessage({ type: 'endResponse' });
        await this.updateStatus();  // v1.12.0: Update usage badge after response
    }

    public async updateStatus() {
        if (!this._view) { return; }

        try {
            const status = await this._backend.getStatus();
            const toolsStatus = await this._backend.getToolsStatus();
            const usage = await this._backend.getUsage();

            this._view.webview.postMessage({
                type: 'status',
                provider: status.provider,
                model: status.model,
                toolsEnabled: toolsStatus.enabled,
                toolCount: toolsStatus.tool_count,
                usage: {
                    promptTokens: usage.prompt_tokens || 0,
                    completionTokens: usage.completion_tokens || 0,
                    totalTokens: usage.total_tokens || 0,
                    estimatedCost: usage.estimated_cost || 0
                }
            });
        } catch (error) {
            // Backend may not be ready yet
            this._view.webview.postMessage({
                type: 'status',
                provider: 'Not connected',
                model: '...',
                toolsEnabled: false,
                toolCount: 0,
                usage: { promptTokens: 0, completionTokens: 0, totalTokens: 0, estimatedCost: 0 }
            });
        }

        // v1.13.9: Also update context badge
        await this.updateContextBadge();
    }

    public async refreshHistory() {
        if (!this._view) { return; }

        try {
            const history = await this._backend.getHistory();
            this._view.webview.postMessage({
                type: 'history',
                messages: history
            });
        } catch (error) {
            // Backend may not be ready
        }
    }

    private _getNonce(): string {
        let text = '';
        const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
        for (let i = 0; i < 32; i++) {
            text += possible.charAt(Math.floor(Math.random() * possible.length));
        }
        return text;
    }

    private getFileEditingHelp(): string {
        return `# File Editing Tools Guide 🎯

## Overview
ppxai can now **autonomously edit files** during conversations! All edits require your **explicit consent** before any changes are made.

## Quick Start
1. **Enable tools**: \`/tools enable\`
2. **Ask AI to edit**: Just request file changes naturally!
3. **Grant consent**: Choose y/n/always/never when prompted

## Consent System

When AI wants to edit a file, you'll see a modal dialog with 4 options:

| Option | Behavior | Use When |
|--------|----------|----------|
| **y** (yes) | Allow editing this file (this session) | You want this specific edit |
| **n** (no) | Deny editing this file | You don't trust this specific edit |
| **always** | Allow all file edits (this session) | You trust the AI completely |
| **never** | Block all file edits (this session) | You want read-only mode |

**Session-Scoped:** Your consent persists for the current session only.

## Available Tools

### 1. apply_patch
Apply unified diff patches (like git patches).

**Example:**
\`\`\`
Apply this patch to fix the bug in auth.py:
[paste unified diff]
\`\`\`

### 2. replace_block
Find and replace exact text blocks.

**Example:**
\`\`\`
In config.py, replace "database = 'test.db'" with "database = 'production.db'"
\`\`\`

### 3. insert_text
Insert text at specific line numbers.

**Example:**
\`\`\`
Add a print statement at line 42 in debug.py: print("Debug checkpoint")
\`\`\`

### 4. delete_lines
Delete line ranges from files.

**Example:**
\`\`\`
Delete lines 10-15 from old_code.py
\`\`\`

## Pro Tips 💡

✅ **Do:**
- Start with small, focused edits
- Review consent prompts carefully
- Use "y" for individual edits when learning
- Use "always" when you fully trust the AI

❌ **Don't:**
- Grant "always" consent without understanding
- Edit files you haven't backed up
- Use with critical system files

## Safety Features ✅

- **User consent required** - Every file edit needs your approval
- **Atomic operations** - Edits rollback automatically on failure
- **Session-scoped** - Consent resets when you restart
- **File existence checks** - Won't edit non-existent files

## Troubleshooting

**Q: AI keeps asking for consent?**
A: Use "always" mode if you trust it for this session.

**Q: Edit failed?**
A: Check file permissions, file exists, and exact text matches.

**Q: How do I disable?**
A: Use \`/tools disable\` or choose "never" when prompted.

## Commands Reference

- \`/tools enable\` - Enable file editing tools
- \`/tools status\` - Check current consent mode
- \`/tools list\` - Show all available tools
- \`/tools help editing\` - Show this help

---

**Ready to try?** Type \`/tools enable\` and ask the AI to edit a file!`;
    }

    private _getHtmlForWebview(webview: vscode.Webview): string {
        // Get URIs for local resources
        const mediaPath = vscode.Uri.joinPath(this._context.extensionUri, 'media');
        const highlightCssUri = webview.asWebviewUri(vscode.Uri.joinPath(mediaPath, 'highlight.css'));
        const highlightJsUri = webview.asWebviewUri(vscode.Uri.joinPath(mediaPath, 'highlight.min.js'));
        const markedJsUri = webview.asWebviewUri(vscode.Uri.joinPath(mediaPath, 'marked.min.js'));

        // Generate nonce for CSP
        const nonce = this._getNonce();

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}' ${webview.cspSource}; font-src ${webview.cspSource};">
    <title>ppxai Chat</title>
    <!-- Highlight.js for syntax highlighting -->
    <link rel="stylesheet" href="${highlightCssUri}">
    <script nonce="${nonce}" src="${highlightJsUri}"></script>
    <!-- Marked for markdown parsing -->
    <script nonce="${nonce}" src="${markedJsUri}"></script>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: var(--vscode-font-family);
            font-size: var(--vscode-font-size);
            color: var(--vscode-foreground);
            background: var(--vscode-editor-background);
            height: 100vh;
            display: flex;
            flex-direction: column;
        }

        .header {
            padding: 8px 12px;
            border-bottom: 1px solid var(--vscode-panel-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: var(--vscode-sideBar-background);
            flex-shrink: 0;
        }

        .status {
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .version-badge {
            font-size: 10px;
            padding: 2px 6px;
            background: var(--vscode-badge-background);
            color: var(--vscode-badge-foreground);
            border-radius: 3px;
            font-weight: 500;
        }

        /* Server status badge - v1.13.1 */
        .server-badge {
            background: var(--vscode-badge-background);
            color: var(--vscode-badge-foreground);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 10px;
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 0.15s ease;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }

        .server-badge:hover {
            background: var(--vscode-button-hoverBackground);
            border-color: var(--vscode-focusBorder);
        }

        .server-badge.disconnected {
            background: var(--vscode-inputValidation-errorBackground, #5a1d1d);
            color: var(--vscode-inputValidation-errorForeground, #f48771);
        }

        .server-badge.connected {
            background: var(--vscode-testing-iconPassed, #89d185);
            color: var(--vscode-editor-background);
        }

        .server-badge.connecting {
            animation: pulse 1.5s ease-in-out infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        .server-indicator {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: currentColor;
        }

        .workspace-info {
            font-size: 10px;
            color: var(--vscode-descriptionForeground);
            display: flex;
            align-items: center;
            gap: 6px;
            max-width: 40%;
            overflow: hidden;
            flex-shrink: 1;
        }

        .workspace-icon {
            flex-shrink: 0;
        }

        .workspace-path {
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            flex-shrink: 1;
        }

        .workspace-name {
            flex-shrink: 0;
            opacity: 0.8;
        }

        .tools-badge {
            background: var(--vscode-badge-background);
            color: var(--vscode-badge-foreground);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 10px;
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .tools-badge:hover {
            background: var(--vscode-button-hoverBackground);
            border-color: var(--vscode-focusBorder);
        }

        .tools-badge.disabled {
            opacity: 0.6;
        }

        .tools-badge.enabled {
            background: var(--vscode-testing-iconPassed, #89d185);
            color: var(--vscode-editor-background);
        }

        /* Agent badge - v1.11.8, v1.12.0: checkpoint indicators */
        .agent-badge {
            background: var(--vscode-badge-background);
            color: var(--vscode-badge-foreground);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 10px;
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .agent-badge:hover {
            background: var(--vscode-button-hoverBackground);
            border-color: var(--vscode-focusBorder);
        }

        .agent-badge.disabled {
            opacity: 0.6;
        }

        .agent-badge.enabled {
            background: var(--vscode-editorInfo-foreground, #3794ff);
            color: var(--vscode-editor-background);
        }

        /* Checkpoint indicators - v1.12.0 */
        .agent-badge.enabled.checkpoint-git {
            background: var(--vscode-testing-iconPassed, #89d185);
            color: var(--vscode-editor-background);
        }

        .agent-badge.enabled.checkpoint-file {
            background: var(--vscode-editorWarning-foreground, #ff9800);
            color: var(--vscode-editor-background);
        }

        .agent-badge.enabled.checkpoint-none {
            background: var(--vscode-errorForeground, #f44336);
            color: var(--vscode-editor-background);
        }

        /* Undo badge - v1.12.0 */
        .undo-badge {
            background: var(--vscode-badge-background);
            color: var(--vscode-badge-foreground);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 10px;
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 0.15s ease;
            display: none;
        }

        .undo-badge:hover {
            background: var(--vscode-button-hoverBackground);
            border-color: var(--vscode-focusBorder);
        }

        .undo-badge.visible {
            display: inline-block;
        }

        .undo-badge.enabled {
            background: var(--vscode-editorInfo-foreground, #3794ff);
            color: var(--vscode-editor-background);
        }

        .undo-badge.disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* v1.12.1: Stale checkpoint - red disabled state */
        .undo-badge.stale {
            background: var(--vscode-errorForeground, #f44336);
            color: var(--vscode-editor-background);
            opacity: 0.7;
            cursor: not-allowed;
        }

        /* Usage badge - v1.12.0 */
        .usage-badge {
            background: var(--vscode-badge-background);
            color: var(--vscode-badge-foreground);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 10px;
            opacity: 0.8;
            cursor: help;
        }

        .usage-badge.has-cost {
            color: var(--vscode-charts-green, #89d185);
        }

        /* v1.13.9: Context usage badge */
        .context-badge {
            background: var(--vscode-badge-background);
            color: var(--vscode-badge-foreground);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 10px;
            border: none;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .context-badge:hover {
            opacity: 0.8;
        }
        .context-badge.warning {
            background: var(--vscode-editorWarning-foreground, #cca700);
            color: var(--vscode-editor-background, #1e1e1e);
            animation: pulse 1.5s ease-in-out infinite;
        }
        .context-badge.critical {
            background: var(--vscode-errorForeground, #f48771);
            color: white;
            animation: pulse 1s ease-in-out infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }

        /* v1.12.0: Tool messages with collapsible details */
        .tool-title {
            font-size: 13px;
            user-select: none;
        }
        .tool-title.clickable {
            cursor: pointer;
        }
        .tool-title.clickable:hover {
            opacity: 0.8;
        }
        /* Expand/collapse indicator */
        .tool-title.clickable::before {
            content: '▼ ';
            font-size: 10px;
            opacity: 0.6;
        }
        .tool-title.clickable.collapsed::before {
            content: '▶ ';
        }
        .tool-details-content {
            margin: 4px 0 4px 8px;
            padding: 8px;
            background: var(--vscode-editor-background);
            border-radius: 4px;
            font-size: 11px;
            max-height: 200px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-word;
            transition: max-height 0.2s ease-out, padding 0.2s ease-out, opacity 0.2s ease-out;
        }
        .tool-details-content.collapsed {
            max-height: 0;
            padding: 0 8px;
            opacity: 0;
            overflow: hidden;
        }

        .streaming-badge {
            background: var(--vscode-editorWarning-foreground, #ff9800);
            color: var(--vscode-editor-background);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 10px;
            border: none;
            cursor: pointer;
            animation: pulse 1.5s ease-in-out infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
        }

        .streaming-badge:hover {
            background: var(--vscode-errorForeground, #f44336);
        }

        .header-buttons {
            display: flex;
            gap: 4px;
        }

        .header-btn {
            background: transparent;
            border: none;
            color: var(--vscode-foreground);
            cursor: pointer;
            padding: 4px 8px;
            font-size: 11px;
            border-radius: 3px;
        }

        .header-btn:hover {
            background: var(--vscode-toolbar-hoverBackground);
        }

        .menu-container {
            position: relative;
        }

        .menu-btn {
            background: transparent;
            border: none;
            color: var(--vscode-foreground);
            cursor: pointer;
            padding: 4px 8px;
            font-size: 16px;
            border-radius: 3px;
            line-height: 1;
        }

        .menu-btn:hover {
            background: var(--vscode-toolbar-hoverBackground);
        }

        .menu-dropdown {
            display: none;
            position: absolute;
            right: 0;
            top: 100%;
            margin-top: 4px;
            background: var(--vscode-dropdown-background);
            border: 1px solid var(--vscode-dropdown-border);
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
            z-index: 1000;
            min-width: 180px;
        }

        .menu-dropdown.visible {
            display: block;
        }

        .menu-item {
            padding: 8px 12px;
            cursor: pointer;
            font-size: 12px;
            display: flex;
            align-items: center;
            gap: 8px;
            color: var(--vscode-foreground);
        }

        .menu-item:hover {
            background: var(--vscode-list-hoverBackground);
        }

        .menu-indicator {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--vscode-descriptionForeground);
        }

        .menu-indicator.active {
            background: #4caf50;
            box-shadow: 0 0 4px #4caf50;
        }

        .menu-separator {
            height: 1px;
            background: var(--vscode-dropdown-border);
            margin: 4px 0;
        }

        .messages {
            flex: 1;
            overflow-y: auto;
            padding: 12px;
        }

        .message {
            margin-bottom: 16px;
            padding: 12px 14px;
            border-radius: 8px;
            max-width: 95%;
            line-height: 1.5;
            position: relative;  /* Required for timestamp absolute positioning */
            overflow-x: auto;  /* v1.12.0: Prevent table overflow */
        }

        .message-timestamp {
            position: absolute;
            top: 4px;
            right: 8px;
            font-size: 10px;
            opacity: 1;
            color: var(--vscode-foreground);
            z-index: 10;
            background: var(--vscode-badge-background);
            padding: 1px 4px;
            border-radius: 3px;
        }

        .message.user .message-timestamp {
            color: rgba(255, 255, 255, 0.8);
        }

        .message.assistant .message-timestamp,
        .message.system .message-timestamp,
        .message.command .message-timestamp,
        .message.error .message-timestamp,
        .message.tool-call .message-timestamp,
        .message.tool-result .message-timestamp {
            color: var(--vscode-descriptionForeground);
        }

        .message-content {
            padding-right: 50px; /* Space for timestamp */
        }

        .message.user {
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            margin-left: auto;
            white-space: pre-wrap;
        }

        .message.assistant {
            background: var(--vscode-editor-inactiveSelectionBackground);
        }

        .message.system {
            background: var(--vscode-textBlockQuote-background);
            border-left: 3px solid var(--vscode-textBlockQuote-border);
            font-size: 12px;
        }

        .message.command {
            background: var(--vscode-textCodeBlock-background);
            font-family: var(--vscode-editor-font-family);
            font-size: 12px;
            color: var(--vscode-textPreformat-foreground);
            white-space: pre-wrap;
        }

        .message.error {
            background: var(--vscode-inputValidation-errorBackground);
            border: 1px solid var(--vscode-inputValidation-errorBorder);
            white-space: pre-wrap;
        }

        .message.tool-call {
            background: var(--vscode-editorInfo-background, rgba(0, 122, 204, 0.1));
            border-left: 3px solid var(--vscode-editorInfo-foreground, #007acc);
            font-size: 12px;
        }

        .message.tool-result {
            background: var(--vscode-editorHint-background, rgba(238, 238, 238, 0.1));
            border-left: 3px solid var(--vscode-editorHint-foreground, #6c6c6c);
            font-size: 12px;
            max-height: 200px;
            overflow-y: auto;
        }

        /* v1.13.9: Reasoning section for DeepSeek R1, GPT-OSS 120B */
        .reasoning-section {
            margin-bottom: 12px;
            border: 1px solid var(--vscode-panel-border);
            border-radius: 4px;
            background: var(--vscode-textBlockQuote-background);
            overflow: hidden;
        }

        .reasoning-header {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 10px;
            cursor: pointer;
            user-select: none;
            -webkit-user-select: none;
            color: var(--vscode-descriptionForeground);
            font-size: 12px;
        }

        .reasoning-header:hover {
            background: var(--vscode-list-hoverBackground);
        }

        .reasoning-icon {
            font-size: 14px;
        }

        .reasoning-title {
            flex: 1;
            font-style: italic;
        }

        .reasoning-section[open] .reasoning-header {
            border-bottom: 1px solid var(--vscode-panel-border);
        }

        .reasoning-content {
            padding: 10px;
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            font-style: italic;
            white-space: pre-wrap;
            word-wrap: break-word;
            max-height: 250px;
            overflow-y: auto;
            line-height: 1.4;
        }

        /* VSCode-style Markdown rendering */
        .message h1, .message h2, .message h3, .message h4, .message h5, .message h6 {
            margin-top: 24px;
            margin-bottom: 16px;
            font-weight: 600;
            line-height: 1.25;
            color: var(--vscode-foreground);
        }

        .message h1 {
            font-size: 2em;
            border-bottom: 1px solid var(--vscode-panel-border);
            padding-bottom: 0.3em;
            margin-bottom: 16px;
        }
        .message h2 {
            font-size: 1.5em;
            border-bottom: 1px solid var(--vscode-panel-border);
            padding-bottom: 0.3em;
        }
        .message h3 {
            font-size: 1.25em;
        }
        .message h4 {
            font-size: 1em;
        }
        .message h5 {
            font-size: 0.875em;
        }
        .message h6 {
            font-size: 0.85em;
            color: var(--vscode-descriptionForeground);
        }

        .message h1:first-child, .message h2:first-child, .message h3:first-child {
            margin-top: 0;
        }

        .message p {
            margin-bottom: 12px;
        }

        .message p:last-child {
            margin-bottom: 0;
        }

        .message ul, .message ol {
            margin-top: 0;
            margin-bottom: 16px;
            padding-left: 2em;
        }

        .message ul {
            list-style-type: disc;
        }

        .message ol {
            list-style-type: decimal;
        }

        .message li {
            margin-bottom: 4px;
            line-height: 1.6;
        }

        .message li > p {
            margin-bottom: 8px;
        }

        .message li > ul, .message li > ol {
            margin-top: 8px;
            margin-bottom: 8px;
        }

        .message ul ul {
            list-style-type: circle;
        }

        .message ul ul ul {
            list-style-type: square;
        }

        .message blockquote {
            margin: 12px 0;
            padding: 8px 16px;
            border-left: 4px solid var(--vscode-textBlockQuote-border);
            background: var(--vscode-textBlockQuote-background);
            color: var(--vscode-textBlockQuote-foreground);
        }

        .message blockquote p:last-child {
            margin-bottom: 0;
        }

        .message hr {
            border: none;
            border-top: 1px solid var(--vscode-panel-border);
            margin: 16px 0;
        }

        .message table {
            border-collapse: collapse;
            margin: 12px 0;
            width: 100%;
            display: block;
            overflow-x: auto;  /* v1.12.0: Horizontal scroll for wide tables */
        }

        .message th, .message td {
            border: 1px solid var(--vscode-panel-border);
            padding: 6px 12px;
            text-align: left;
            white-space: nowrap;  /* v1.12.0: Prevent cell content wrapping */
        }

        .message th {
            background: var(--vscode-editor-inactiveSelectionBackground);
            font-weight: 600;
        }

        .message tr:nth-child(even) td {
            background: var(--vscode-list-hoverBackground);
        }

        /* Code styling */
        .message code {
            font-family: var(--vscode-editor-font-family, 'Menlo', 'Monaco', 'Courier New', monospace);
            font-size: 0.9em;
        }

        .message code:not(pre code) {
            background: var(--vscode-textCodeBlock-background);
            padding: 2px 6px;
            border-radius: 4px;
            color: var(--vscode-textPreformat-foreground);
        }

        .message pre {
            background: var(--vscode-textCodeBlock-background);
            border-radius: 6px;
            margin: 12px 0;
            overflow-x: auto;
            position: relative;
        }

        .message pre code {
            display: block;
            padding: 12px 14px;
            overflow-x: auto;
            line-height: 1.4;
            font-size: 12px;
        }

        /* Override highlight.js background to use VSCode colors */
        .message pre code.hljs {
            background: transparent;
            padding: 12px 14px;
        }

        /* Links */
        .message a {
            color: var(--vscode-textLink-foreground);
            text-decoration: underline;
            cursor: pointer;
        }

        .message a:hover {
            text-decoration: underline;
            color: var(--vscode-textLink-activeForeground, var(--vscode-textLink-foreground));
        }

        .message-content a {
            color: var(--vscode-textLink-foreground);
            text-decoration: underline;
            cursor: pointer;
        }

        /* URL links (from backtick-wrapped URLs) */
        .message a.url-link {
            color: var(--vscode-textLink-foreground);
            text-decoration: underline;
            word-break: break-all;
        }

        /* Strong and emphasis */
        .message strong {
            font-weight: 600;
        }

        .message em {
            font-style: italic;
        }

        /* Images */
        .message img {
            max-width: 100%;
            border-radius: 4px;
            margin: 8px 0;
        }

        .response-time {
            font-size: 10px;
            color: var(--vscode-descriptionForeground);
            text-align: right;
            margin-top: 8px;
            opacity: 0.7;
        }

        .input-container {
            padding: 12px;
            border-top: 1px solid var(--vscode-panel-border);
            background: var(--vscode-sideBar-background);
            flex-shrink: 0;
        }

        .input-hint {
            font-size: 10px;
            color: var(--vscode-descriptionForeground);
            margin-bottom: 6px;
        }

        .input-wrapper {
            display: flex;
            gap: 8px;
        }

        #messageInput {
            flex: 1;
            background: var(--vscode-input-background);
            color: var(--vscode-input-foreground);
            border: 1px solid var(--vscode-input-border);
            border-radius: 4px;
            padding: 8px 12px;
            font-family: inherit;
            font-size: inherit;
            resize: none;
            min-height: 36px;
            max-height: 120px;
        }

        #messageInput:focus {
            outline: none;
            border-color: var(--vscode-focusBorder);
        }

        /* v1.12.0: Disabled input state during streaming/consent */
        #messageInput:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            background: var(--vscode-input-background);
        }

        #sendBtn {
            background: var(--vscode-button-background);
            color: var(--vscode-button-foreground);
            border: none;
            border-radius: 4px;
            padding: 8px 16px;
            cursor: pointer;
            font-weight: 500;
        }

        #sendBtn:hover {
            background: var(--vscode-button-hoverBackground);
        }

        #sendBtn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        .typing-indicator {
            display: none;
            padding: 8px 12px;
            color: var(--vscode-descriptionForeground);
            font-style: italic;
            align-items: center;
            gap: 8px;
        }

        .typing-indicator.visible {
            display: flex;
        }

        /* v1.13.2: Animated dots for typing indicator */
        .typing-indicator::before {
            content: '';
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--vscode-progressBar-background);
            animation: typingPulse 1.4s ease-in-out infinite;
        }

        @keyframes typingPulse {
            0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; }
            40% { transform: scale(1); opacity: 1; }
        }

        /* Autocomplete dropdown */
        .autocomplete-container {
            position: relative;
        }

        .autocomplete-dropdown {
            display: none;
            position: absolute;
            bottom: 100%;
            left: 0;
            right: 60px;
            max-height: 200px;
            overflow-y: auto;
            background: var(--vscode-editorWidget-background);
            border: 1px solid var(--vscode-editorWidget-border);
            border-radius: 6px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            margin-bottom: 4px;
            z-index: 100;
        }

        .autocomplete-dropdown.visible {
            display: block;
        }

        .autocomplete-item {
            padding: 8px 12px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 8px;
            border-bottom: 1px solid var(--vscode-editorWidget-border);
        }

        .autocomplete-item:last-child {
            border-bottom: none;
        }

        .autocomplete-item:hover,
        .autocomplete-item.selected {
            background: var(--vscode-list-hoverBackground);
        }

        .autocomplete-item .icon {
            font-size: 14px;
            opacity: 0.8;
        }

        .autocomplete-item .name {
            font-weight: 500;
            color: var(--vscode-foreground);
        }

        .autocomplete-item .path {
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            margin-left: auto;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 200px;
        }

        .autocomplete-item .description {
            font-size: 11px;
            color: var(--vscode-descriptionForeground);
            margin-left: auto;
        }

        .autocomplete-header {
            padding: 6px 12px;
            font-size: 10px;
            color: var(--vscode-descriptionForeground);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            background: var(--vscode-editorWidget-background);
            border-bottom: 1px solid var(--vscode-editorWidget-border);
        }

        /* Time/date dividers between messages */
        .time-divider {
            display: flex;
            align-items: center;
            margin: 16px 0 12px 0;
            gap: 12px;
        }

        .time-divider::before,
        .time-divider::after {
            content: '';
            flex: 1;
            height: 1px;
            background: var(--vscode-panel-border);
            opacity: 0.5;
        }

        .time-divider-label {
            font-size: 10px;
            color: var(--vscode-descriptionForeground);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            white-space: nowrap;
            padding: 2px 8px;
            background: var(--vscode-editor-background);
            border-radius: 10px;
            border: 1px solid var(--vscode-panel-border);
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="status">
            <span class="version-badge" title="Extension version">v${this._context.extension.packageJSON.version}</span>
            <button class="server-badge disconnected" id="serverBadge" title="Click to start/stop server">
                <span class="server-indicator"></span>
                <span id="serverStatus">Disconnected</span>
            </button>
            <span><span id="provider">Loading...</span> / <span id="model">...</span></span>
            <button class="tools-badge disabled" id="toolsBadge" title="Click to toggle tools">Tools: off</button>
            <button class="agent-badge disabled" id="agentBadge" title="Click to toggle agent mode">Agent: off</button>
            <button class="undo-badge" id="undoBadge" title="No checkpoint to undo">↶ Undo</button>
            <button class="streaming-badge" id="streamingBadge" style="display: none;" title="Press Esc to stop">⏹ Streaming...</button>
            <span class="usage-badge" id="usageBadge" title="Session token usage and cost">0↓/0↑</span>
            <button class="context-badge" id="contextBadge" title="Context window usage - Click to clear injected files">
                <span id="contextUsage">Ctx: 0%</span>
            </button>
        </div>
        <div class="workspace-info" id="workspaceInfo" style="display: none;">
            <span class="workspace-icon">📁</span>
            <span id="workspacePath" class="workspace-path"></span>
            <span class="workspace-name">(<span id="workspaceName"></span>)</span>
        </div>
        <div class="header-buttons">
            <button class="header-btn" id="clearBtn" title="Clear history">Clear</button>
            <div class="menu-container">
                <button class="menu-btn" id="menuBtn" title="More options">⋮</button>
                <div class="menu-dropdown" id="menuDropdown">
                    <div class="menu-item" id="saveSessionMenuItem">
                        <span>💾 Save Session</span>
                    </div>
                    <div class="menu-item" id="saveAnswerMenuItem">
                        <span>📄 Save Answer</span>
                    </div>
                    <div class="menu-separator"></div>
                    <div class="menu-item" id="debugLogMenuItem">
                        <span class="menu-indicator" id="debugLogIndicator"></span>
                        <span>Debug Log</span>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="messages" id="messages">
        <div class="typing-indicator" id="typingIndicator">Thinking... (Press Esc to stop)</div>
    </div>

    <div class="input-container">
        <div class="input-hint">Type /help for commands • @file to reference • ↑/↓ for history</div>
        <div class="autocomplete-container">
            <div class="autocomplete-dropdown" id="autocompleteDropdown"></div>
            <div class="input-wrapper">
                <textarea
                    id="messageInput"
                    placeholder="Ask anything or type / for commands..."
                    rows="1"
                ></textarea>
                <button id="sendBtn">Send</button>
            </div>
        </div>
    </div>

    <script nonce="${nonce}">
        const vscode = acquireVsCodeApi();
        const messagesContainer = document.getElementById('messages');
        let typingIndicator = document.getElementById('typingIndicator');
        const messageInput = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendBtn');
        const providerSpan = document.getElementById('provider');
        const modelSpan = document.getElementById('model');
        const serverBadge = document.getElementById('serverBadge');
        const serverStatus = document.getElementById('serverStatus');
        const toolsBadge = document.getElementById('toolsBadge');
        const streamingBadge = document.getElementById('streamingBadge');
        const usageBadge = document.getElementById('usageBadge');
        const contextBadge = document.getElementById('contextBadge');
        const contextUsage = document.getElementById('contextUsage');
        const clearBtn = document.getElementById('clearBtn');
        const menuBtn = document.getElementById('menuBtn');
        const menuDropdown = document.getElementById('menuDropdown');
        const saveSessionMenuItem = document.getElementById('saveSessionMenuItem');
        const saveAnswerMenuItem = document.getElementById('saveAnswerMenuItem');
        const debugLogMenuItem = document.getElementById('debugLogMenuItem');
        const debugLogIndicator = document.getElementById('debugLogIndicator');

        let currentResponseEl = null;
        let currentResponseContent = '';
        let lastAssistantMessage = '';  // Track last assistant response
        let renderPending = false;
        let lastRenderTime = 0;
        let responseStartTime = 0; // Track when response started
        const RENDER_THROTTLE_MS = 100; // Render at most every 100ms during streaming
        const MAX_HIGHLIGHT_SIZE = 10000; // Skip syntax highlighting for code blocks > 10KB

        // Command history
        const commandHistory = [];
        const MAX_HISTORY = 100;
        let historyIndex = -1;
        let currentInput = '';

        // Time divider tracking
        let lastMessageTime = null;
        const TIME_GAP_THRESHOLD_MS = 5 * 60 * 1000; // 5 minutes - show divider after this gap

        // Autocomplete state
        const autocompleteDropdown = document.getElementById('autocompleteDropdown');
        let autocompleteItems = [];
        let autocompleteSelectedIndex = -1;
        let autocompleteMode = null; // 'file', 'command', or null
        let autocompleteQuery = '';
        let autocompleteStartPos = 0;
        let autocompleteDisabled = false; // Disabled for special providers (@git, @tree)

        // Slash commands for autocomplete
        const slashCommands = [
            { name: '/help', description: 'Show available commands' },
            { name: '/clear', description: 'Clear conversation history' },
            { name: '/save', description: 'Save session to JSON' },
            { name: '/export', description: 'Export last answer to markdown' },
            { name: '/load', description: 'Load a saved session' },
            { name: '/sessions', description: 'List saved sessions' },
            { name: '/model', description: 'Switch model' },
            { name: '/provider', description: 'Switch provider' },
            { name: '/tools', description: 'Manage AI tools (enable|disable|list)' },
            { name: '/show', description: 'Display file contents' },
            { name: '/usage', description: 'Show token usage stats' },
            { name: '/status', description: 'Show current status' },
            { name: '/generate', description: 'Generate code from description' },
            { name: '/explain', description: 'Explain code or concept' },
            { name: '/test', description: 'Generate tests for code' },
            { name: '/docs', description: 'Generate documentation' },
            { name: '/debug', description: 'Debug an error message' },
            { name: '/implement', description: 'Implement from description' },
        ];

        // Configure marked for GFM
        // Check if marked library loaded
        let parseMarkdown;
        if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
            marked.setOptions({
                breaks: true,
                gfm: true
            });
            // Wrap marked.parse to pre-process backtick-wrapped URLs and markdown code blocks
            parseMarkdown = function(text) {
                if (!text) return '';

                // BUGFIX: Unwrap markdown code blocks BEFORE marked processes them
                // Some models (Gemini 2.0 Flash, Gemini 3 Pro) wrap output in triple-backtick markdown blocks
                // which would cause syntax highlighting instead of rendering
                // Simply extract the content and let marked parse it normally
                // Use \\x60 hex escape for backticks to avoid template literal parsing issues
                text = text.replace(/\\x60\\x60\\x60(?:markdown|md)\\s*\\n([\\s\\S]*?)\\x60\\x60\\x60/g, '$1');

                // Convert backtick-wrapped URLs to links BEFORE marked processes them
                text = text.replace(/\\x60(https?:\\/\\/[^\\x60]+)\\x60/g, '<a href="$1" target="_blank" rel="noopener" class="url-link">$1</a>');

                // Parse with marked
                return marked.parse(text);
            };
            console.log('Marked library loaded successfully');
        } else {
            console.error('Marked library not loaded! typeof marked =', typeof marked);
            // Fallback: basic markdown parsing
            parseMarkdown = function(text) {
                if (!text) return '';
                // Code blocks first (before escaping HTML)
                text = text.replace(/\`\`\`(\\w*)\\n([\\s\\S]*?)\`\`\`/g, function(m, lang, code) {
                    code = code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                    return '<pre><code class="' + lang + '">' + code + '</code></pre>';
                });
                // Inline code - but convert URL-only code to links instead
                text = text.replace(/\`(https?:\\/\\/[^\`]+)\`/g, '<a href="$1" target="_blank" rel="noopener" class="url-link">$1</a>');
                text = text.replace(/\`([^\`]+)\`/g, function(m, code) {
                    code = code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                    return '<code>' + code + '</code>';
                });
                // Escape remaining HTML
                text = text.replace(/&(?!amp;|lt;|gt;)/g, '&amp;');
                text = text.replace(/<(?!\\/?(pre|code|h[1-6]|strong|em|ul|ol|li|p|blockquote)[ >])/g, '&lt;');
                // Headers
                text = text.replace(/^###### (.+)$/gm, '<h6>$1</h6>');
                text = text.replace(/^##### (.+)$/gm, '<h5>$1</h5>');
                text = text.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
                text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>');
                text = text.replace(/^## (.+)$/gm, '<h2>$1</h2>');
                text = text.replace(/^# (.+)$/gm, '<h1>$1</h1>');
                // Bold
                text = text.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
                // Italic
                text = text.replace(/\\*([^*]+)\\*/g, '<em>$1</em>');
                // Links [text](url)
                text = text.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
                // Bare URLs (http/https) - convert to clickable links
                text = text.replace(/(^|[^"'>])(https?:\\/\\/[^\\s<)\\]]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
                // Lists
                text = text.replace(/^- (.+)$/gm, '<li>$1</li>');
                text = text.replace(/(<li>.*<\\/li>\\n?)+/g, '<ul>$&</ul>');
                // Paragraphs
                var lines = text.split('\\n');
                text = lines.map(function(line) {
                    if (line.trim() === '' || line.match(/^<(pre|h[1-6]|ul|ol|li|blockquote)/)) return line;
                    if (!line.match(/^<[a-z]/)) return '<p>' + line + '</p>';
                    return line;
                }).join('\\n');
                return text;
            };
        }

        // Throttled render function for streaming
        function scheduleRender() {
            if (renderPending) return;

            const now = Date.now();
            const timeSinceLastRender = now - lastRenderTime;

            if (timeSinceLastRender >= RENDER_THROTTLE_MS) {
                // Render immediately
                doRender();
            } else {
                // Schedule render
                renderPending = true;
                setTimeout(() => {
                    renderPending = false;
                    doRender();
                }, RENDER_THROTTLE_MS - timeSinceLastRender);
            }
        }

        function doRender() {
            if (!currentResponseEl || !currentResponseContent) return;
            lastRenderTime = Date.now();
            // Use simple escaping during streaming for speed
            const contentEl = currentResponseEl.querySelector('.message-content') || currentResponseEl;
            contentEl.innerHTML = simpleFormat(currentResponseContent);
            scrollToBottom();
        }

        // Simple formatting for streaming (fast)
        function simpleFormat(text) {
            if (!text) return '';
            // Escape HTML
            text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            // Basic code blocks
            text = text.replace(/\`\`\`(\\w*)\\n([\\s\\S]*?)\`\`\`/g, '<pre><code>$2</code></pre>');
            // Inline code - but convert URL-only code to links instead
            text = text.replace(/\`(https?:\\/\\/[^\`]+)\`/g, '<a href="$1" target="_blank" rel="noopener" class="url-link">$1</a>');
            text = text.replace(/\`([^\`]+)\`/g, '<code>$1</code>');
            // Bold
            text = text.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
            // Headers (basic support during streaming)
            text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>');
            text = text.replace(/^## (.+)$/gm, '<h2>$1</h2>');
            text = text.replace(/^# (.+)$/gm, '<h1>$1</h1>');
            // Links [text](url)
            text = text.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
            // Bare URLs (convert https://... to clickable links)
            text = text.replace(/(^|[^"'>])(https?:\\/\\/[^\\s<)\\]]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
            // Line breaks
            text = text.replace(/\\n/g, '<br>');
            return text;
        }

        // Full markdown render (at end of streaming)
        function fullRender(showTime = false) {
            if (!currentResponseEl || !currentResponseContent) return;
            const contentEl = currentResponseEl.querySelector('.message-content') || currentResponseEl;
            try {
                contentEl.innerHTML = parseMarkdown(currentResponseContent);
                // parseMarkdown() already unwraps markdown code blocks before parsing
                // Just apply syntax highlighting to code blocks
                contentEl.querySelectorAll('pre code').forEach((block) => {
                    if (block.textContent.length <= MAX_HIGHLIGHT_SIZE) {
                        hljs.highlightElement(block);
                    }
                });
                // Add response time if requested
                if (showTime && responseStartTime > 0) {
                    const elapsed = ((Date.now() - responseStartTime) / 1000).toFixed(1);
                    const timeEl = document.createElement('div');
                    timeEl.className = 'response-time';
                    timeEl.textContent = elapsed + 's';
                    contentEl.appendChild(timeEl);
                }
            } catch (e) {
                console.error('Full render error:', e);
                contentEl.innerHTML = simpleFormat(currentResponseContent);
            }
            scrollToBottom();
        }

        // Autocomplete functions
        function showAutocomplete(items, mode) {
            autocompleteItems = items;
            autocompleteMode = mode;
            autocompleteSelectedIndex = items.length > 0 ? 0 : -1;
            renderAutocomplete();
        }

        function hideAutocomplete() {
            autocompleteDropdown.classList.remove('visible');
            autocompleteItems = [];
            autocompleteMode = null;
            autocompleteSelectedIndex = -1;
        }

        function renderAutocomplete() {
            if (autocompleteItems.length === 0) {
                hideAutocomplete();
                return;
            }

            const header = autocompleteMode === 'file' ? 'Files' : 'Commands';
            let html = '<div class="autocomplete-header">' + header + '</div>';

            autocompleteItems.forEach((item, index) => {
                const selectedClass = index === autocompleteSelectedIndex ? ' selected' : '';
                if (autocompleteMode === 'file') {
                    html += '<div class="autocomplete-item' + selectedClass + '" data-index="' + index + '">' +
                        '<span class="icon">📄</span>' +
                        '<span class="name">' + item.name + '</span>' +
                        '<span class="path">' + (item.path || '') + '</span>' +
                    '</div>';
                } else {
                    html += '<div class="autocomplete-item' + selectedClass + '" data-index="' + index + '">' +
                        '<span class="icon">⌘</span>' +
                        '<span class="name">' + item.name + '</span>' +
                        '<span class="description">' + item.description + '</span>' +
                    '</div>';
                }
            });

            autocompleteDropdown.innerHTML = html;
            autocompleteDropdown.classList.add('visible');

            // Add click handlers
            autocompleteDropdown.querySelectorAll('.autocomplete-item').forEach(el => {
                el.addEventListener('click', () => {
                    const idx = parseInt(el.dataset.index);
                    selectAutocompleteItem(idx);
                });
            });
        }

        function selectAutocompleteItem(index) {
            if (index < 0 || index >= autocompleteItems.length) return;

            const item = autocompleteItems[index];
            const value = messageInput.value;
            const beforeTrigger = value.substring(0, autocompleteStartPos);
            const afterCursor = value.substring(messageInput.selectionStart);

            let insertText;
            if (autocompleteMode === 'file') {
                // v1.13.8: Don't add @ prefix if name already has it (e.g., @git, @tree)
                insertText = item.name.startsWith('@') ? item.name : '@' + item.name;
            } else {
                insertText = item.name;
            }

            messageInput.value = beforeTrigger + insertText + ' ' + afterCursor;
            const newPos = beforeTrigger.length + insertText.length + 1;
            messageInput.setSelectionRange(newPos, newPos);
            hideAutocomplete();
            messageInput.focus();
        }

        function handleAutocompleteNavigation(e) {
            if (!autocompleteDropdown.classList.contains('visible')) return false;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                autocompleteSelectedIndex = Math.min(autocompleteSelectedIndex + 1, autocompleteItems.length - 1);
                renderAutocomplete();
                return true;
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                autocompleteSelectedIndex = Math.max(autocompleteSelectedIndex - 1, 0);
                renderAutocomplete();
                return true;
            } else if (e.key === 'Enter' || e.key === 'Tab') {
                e.preventDefault();
                selectAutocompleteItem(autocompleteSelectedIndex);
                return true;
            } else if (e.key === 'Escape') {
                e.preventDefault();
                hideAutocomplete();
                return true;
            }
            return false;
        }

        function checkAutocomplete() {
            const value = messageInput.value;
            const cursorPos = messageInput.selectionStart;
            const textBeforeCursor = value.substring(0, cursorPos);

            // Check for @ file reference
            const atMatch = textBeforeCursor.match(/@([\\w.\\-\\/]*)$/);
            if (atMatch) {
                autocompleteStartPos = cursorPos - atMatch[0].length;
                autocompleteQuery = atMatch[1];
                autocompleteDisabled = false;
                // v1.13.8: Request file suggestions (now includes @git, @tree)
                vscode.postMessage({ type: 'searchFiles', query: autocompleteQuery || '' });
                return;
            }

            // Check for / command at start of line
            const cmdMatch = textBeforeCursor.match(/^(\\/[\\w]*)$/);
            if (cmdMatch) {
                autocompleteStartPos = 0;
                autocompleteQuery = cmdMatch[1].toLowerCase();
                // Filter commands locally
                const filtered = slashCommands.filter(cmd =>
                    cmd.name.toLowerCase().startsWith(autocompleteQuery)
                );
                showAutocomplete(filtered, 'command');
                return;
            }

            // No autocomplete trigger found
            hideAutocomplete();
        }

        // Auto-resize textarea
        messageInput.addEventListener('input', () => {
            messageInput.style.height = 'auto';
            messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
            // Check for autocomplete triggers
            checkAutocomplete();
        });

        // v1.13.2: Flag-based input control (matches web app pattern)
        // This prevents out-of-order messages while keeping input focused
        let isStreaming = false;
        let isSending = false;

        // Send message
        function sendMessage() {
            const content = messageInput.value.trim();
            // v1.13.2: Use flags instead of disabled state to prevent concurrent requests
            if (!content || isStreaming || isSending) return;

            // Set sending flag immediately to prevent double-sends
            isSending = true;

            // Add to history
            if (commandHistory.length === 0 || commandHistory[commandHistory.length - 1] !== content) {
                commandHistory.push(content);
                if (commandHistory.length > MAX_HISTORY) {
                    commandHistory.shift();
                }
            }
            historyIndex = -1;
            currentInput = '';

            vscode.postMessage({ type: 'chat', content });
            messageInput.value = '';
            messageInput.style.height = 'auto';
            hideAutocomplete(); // v1.13.8: Hide autocomplete when sending
            // Input stays enabled but flags prevent sending - focus is preserved
        }

        sendBtn.addEventListener('click', sendMessage);
        messageInput.addEventListener('keydown', (e) => {
            // Check autocomplete navigation first
            if (handleAutocompleteNavigation(e)) {
                return;
            }

            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            } else if (e.key === 'ArrowUp' && commandHistory.length > 0) {
                // Navigate to older command
                e.preventDefault();
                if (historyIndex === -1) {
                    // Save current input before navigating
                    currentInput = messageInput.value;
                    historyIndex = commandHistory.length - 1;
                } else if (historyIndex > 0) {
                    historyIndex--;
                }
                messageInput.value = commandHistory[historyIndex];
                // Move cursor to end
                messageInput.setSelectionRange(messageInput.value.length, messageInput.value.length);
            } else if (e.key === 'ArrowDown' && historyIndex !== -1) {
                // Navigate to newer command
                e.preventDefault();
                if (historyIndex < commandHistory.length - 1) {
                    historyIndex++;
                    messageInput.value = commandHistory[historyIndex];
                } else {
                    // Back to current input
                    historyIndex = -1;
                    messageInput.value = currentInput;
                }
                // Move cursor to end
                messageInput.setSelectionRange(messageInput.value.length, messageInput.value.length);
            }
        });

        clearBtn.addEventListener('click', () => {
            vscode.postMessage({ type: 'clear' });
        });

        // Menu button click handler - toggle dropdown
        menuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            menuDropdown.classList.toggle('visible');
        });

        // Close menu when clicking outside
        document.addEventListener('click', (e) => {
            if (!menuBtn.contains(e.target) && !menuDropdown.contains(e.target)) {
                menuDropdown.classList.remove('visible');
            }
        });

        // Save Session menu item click handler
        saveSessionMenuItem.addEventListener('click', () => {
            vscode.postMessage({ type: 'save' });
            menuDropdown.classList.remove('visible');
        });

        // Save Answer menu item click handler
        saveAnswerMenuItem.addEventListener('click', () => {
            if (lastAssistantMessage) {
                vscode.postMessage({ type: 'saveAnswer', content: lastAssistantMessage });
            } else {
                vscode.postMessage({ type: 'error', message: 'No answer to save yet' });
            }
            menuDropdown.classList.remove('visible');
        });

        // Debug Log menu item click handler
        debugLogMenuItem.addEventListener('click', () => {
            const isActive = debugLogIndicator.classList.contains('active');
            vscode.postMessage({ type: 'toggleDebugLog', enable: !isActive });
            menuDropdown.classList.remove('visible');
        });

        // Tools badge click handler - toggle tools on/off
        // Server badge click handler - toggle server on/off (v1.13.1)
        serverBadge.addEventListener('click', () => {
            const isConnected = serverBadge.classList.contains('connected');
            vscode.postMessage({ type: 'toggleServer', stop: isConnected });
        });

        // Function to update server status (v1.13.1)
        function updateServerStatus(connected, connecting = false) {
            serverBadge.classList.remove('connected', 'disconnected', 'connecting');
            if (connecting) {
                serverBadge.classList.add('connecting');
                serverStatus.textContent = 'Connecting...';
                serverBadge.title = 'Connecting to server...';
            } else if (connected) {
                serverBadge.classList.add('connected');
                serverStatus.textContent = 'Connected';
                serverBadge.title = 'Click to stop server';
            } else {
                serverBadge.classList.add('disconnected');
                serverStatus.textContent = 'Disconnected';
                serverBadge.title = 'Click to start server';
            }
        }

        toolsBadge.addEventListener('click', () => {
            const isEnabled = toolsBadge.classList.contains('enabled');
            vscode.postMessage({ type: 'toggleTools', enable: !isEnabled });
        });

        // Agent badge click handler - toggle agent mode on/off (v1.11.8)
        const agentBadge = document.getElementById('agentBadge');
        agentBadge.addEventListener('click', () => {
            const isEnabled = agentBadge.classList.contains('enabled');
            vscode.postMessage({ type: 'toggleAgent', enable: !isEnabled });
        });

        // Undo badge click handler - undo last checkpoint (v1.12.0, v1.12.1: stale check)
        const undoBadge = document.getElementById('undoBadge');
        undoBadge.addEventListener('click', () => {
            // Block clicks on disabled (no checkpoint) or stale checkpoints
            if (!undoBadge.classList.contains('disabled') && !undoBadge.classList.contains('stale')) {
                vscode.postMessage({ type: 'undoCheckpoint' });
            }
        });

        // Streaming badge click handler - interrupt streaming
        streamingBadge.addEventListener('click', () => {
            vscode.postMessage({ type: 'interrupt' });
        });

        // Context badge click handler - clear injected contexts (v1.13.9)
        contextBadge.addEventListener('click', () => {
            vscode.postMessage({ type: 'clearContext' });
        });

        // Handle link clicks - open external URLs
        messagesContainer.addEventListener('click', (e) => {
            // Use closest() to catch clicks on elements inside links
            const link = e.target.closest('a');
            if (link && link.href) {
                e.preventDefault();
                e.stopPropagation();
                console.log('Opening link:', link.href);
                vscode.postMessage({ type: 'openLink', url: link.href });
            }
        });

        // Handle Esc key - interrupt current streaming
        // Inspired by Claude Code's interrupt functionality (https://claude.ai/code)
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                e.preventDefault();
                vscode.postMessage({ type: 'interrupt' });
            }
        });

        // Handle messages from extension
        window.addEventListener('message', (event) => {
            const message = event.data;

            switch (message.type) {
                case 'userMessage':
                    addMessage('user', message.content, false);
                    break;

                case 'commandMessage':
                    addMessage('command', message.content, false);
                    break;

                case 'systemMessage':
                    addMessage('system', message.content, true);
                    // v1.13.2: Reset flags after system message (e.g., /help, /status)
                    isStreaming = false;
                    isSending = false;
                    break;

                case 'toolCall':
                    typingIndicator.textContent = 'Using tool: ' + message.tool + '...';
                    typingIndicator.classList.add('visible');
                    // v1.12.0: Use collapsible tool message
                    addToolMessage('tool-call', '🔧 Calling tool: ' + message.tool, JSON.stringify(message.arguments, null, 2), message.verbose);

                    // BUGFIX: Strip tool call JSON from current response content
                    // When Gemini includes tool JSON in its response, remove it from display
                    if (currentResponseContent) {
                        // Remove trailing JSON code blocks that match tool call pattern
                        // Pattern: \\\`\\\`\\\`json\\n{\\n  "tool": "...",\\n  "arguments": {...}\\n}\\n\\\`\\\`\\\`
                        const toolJsonPattern = /\\\`\\\`\\\`(?:json)?\\s*\\{[^\\\`]*?"tool"\\s*:\\s*"[^"]+?"[^\\\`]*?\\}\\s*\\\`\\\`\\\`\\s*$/;
                        const beforeStrip = currentResponseContent;
                        currentResponseContent = currentResponseContent.replace(toolJsonPattern, '').trimEnd();

                        // If we stripped something, re-render to remove the JSON from UI
                        if (beforeStrip !== currentResponseContent && currentResponseEl) {
                            const contentEl = currentResponseEl.querySelector('.message-content') || currentResponseEl;
                            contentEl.innerHTML = simpleFormat(currentResponseContent);
                        }
                    }
                    break;

                case 'toolResult':
                    typingIndicator.textContent = 'Processing tool result...';
                    // v1.12.0: Use collapsible tool message with verbose support
                    const resultPreview = typeof message.result === 'string'
                        ? (message.result.length > 2000 ? message.result.slice(0, 2000) + '...' : message.result)
                        : JSON.stringify(message.result, null, 2);
                    addToolMessage('tool-result', '📋 Result from ' + message.tool, resultPreview, message.verbose);
                    break;

                case 'contextInjected':
                    const sizeStr = formatFileSize(message.size);
                    const truncNote = message.truncated ? ' (truncated)' : '';
                    addMessage('system', '📎 Attached: \`' + message.source + '\` (' + sizeStr + ')' + truncNote, true);
                    break;

                case 'startResponse':
                    typingIndicator.textContent = 'Thinking... (Press Esc to stop)';
                    typingIndicator.classList.add('visible');
                    streamingBadge.style.display = 'block';  // Show streaming indicator
                    // v1.13.2: Set streaming flag, clear sending flag (matches web app pattern)
                    isStreaming = true;
                    isSending = false;
                    currentResponseEl = null;
                    currentResponseContent = '';
                    responseStartTime = Date.now();
                    break;

                case 'thinking':
                    // Backend received request or iteration progress
                    typingIndicator.textContent = message.content || 'Processing...';
                    typingIndicator.classList.add('visible');
                    break;

                case 'started':
                    // API call started, waiting for first token
                    typingIndicator.textContent = 'Waiting for response...';
                    break;

                case 'reasoning_chunk':
                    // v1.13.9: Reasoning tokens from DeepSeek R1, GPT-OSS 120B
                    typingIndicator.classList.remove('visible');
                    if (!currentResponseEl) {
                        currentResponseEl = addMessage('assistant', '', false);
                    }
                    // Append to reasoning section (collapsible)
                    appendReasoningChunk(currentResponseEl, message.content);
                    break;

                case 'chunk':
                    if (!currentResponseEl) {
                        currentResponseEl = addMessage('assistant', '', false);
                        typingIndicator.classList.remove('visible');
                    }
                    // v1.13.9: Close reasoning section when content starts
                    closeReasoningSection(currentResponseEl);
                    currentResponseContent += message.content;
                    scheduleRender(); // Throttled simple render during streaming
                    break;

                case 'fullResponse':
                    // Handle complete response from stream_end (used when tools are called)
                    // This arrives BEFORE endResponse with the full content
                    if (!currentResponseEl) {
                        currentResponseEl = addMessage('assistant', '', false);
                        typingIndicator.classList.remove('visible');
                    }
                    currentResponseContent = message.content;
                    scheduleRender();
                    break;

                case 'emptyResponse':
                    // v1.13.2: Handle empty responses (common with GPT-OSS 120B after tool iterations)
                    typingIndicator.classList.remove('visible');
                    if (!currentResponseEl) {
                        currentResponseEl = addMessage('assistant', '', false);
                    }
                    // Show placeholder message for empty response
                    if (!currentResponseContent) {
                        currentResponseContent = '*Task completed. (No additional response from AI)*';
                        scheduleRender();
                    }
                    break;

                case 'endResponse':
                    typingIndicator.classList.remove('visible');
                    streamingBadge.style.display = 'none';  // Hide streaming indicator
                    // v1.13.2: Reset flags after response (matches web app pattern)
                    isStreaming = false;
                    isSending = false;
                    // Full markdown render with syntax highlighting at the end
                    fullRender(true);
                    // Save last assistant message for export
                    lastAssistantMessage = currentResponseContent;
                    currentResponseEl = null;
                    currentResponseContent = '';
                    responseStartTime = 0;
                    break;

                case 'error':
                    typingIndicator.classList.remove('visible');
                    streamingBadge.style.display = 'none';  // Hide streaming indicator
                    addMessage('error', message.content, false);
                    // v1.13.2: Reset flags after error (matches web app pattern)
                    isStreaming = false;
                    isSending = false;
                    break;

                case 'status':
                    providerSpan.textContent = message.provider;
                    modelSpan.textContent = message.model;
                    if (message.toolsEnabled) {
                        toolsBadge.textContent = 'Tools: ' + message.toolCount;
                        toolsBadge.classList.remove('disabled');
                        toolsBadge.classList.add('enabled');
                        toolsBadge.title = 'Click to disable tools';
                    } else {
                        toolsBadge.textContent = 'Tools: off';
                        toolsBadge.classList.add('disabled');
                        toolsBadge.classList.remove('enabled');
                        toolsBadge.title = 'Click to enable tools';
                    }
                    // Update usage badge (v1.12.0)
                    if (message.usage && usageBadge) {
                        const formatTokens = (count) => count >= 1000 ? (count/1000).toFixed(1) + 'K' : count.toString();
                        const promptStr = formatTokens(message.usage.promptTokens);
                        const completionStr = formatTokens(message.usage.completionTokens);
                        const cost = message.usage.estimatedCost;
                        if (cost > 0) {
                            usageBadge.textContent = promptStr + '↓/' + completionStr + '↑ $' + cost.toFixed(4);
                            usageBadge.classList.add('has-cost');
                        } else {
                            usageBadge.textContent = promptStr + '↓/' + completionStr + '↑';
                            usageBadge.classList.remove('has-cost');
                        }
                        usageBadge.title = 'Session: ' + message.usage.totalTokens.toLocaleString() + ' tokens, $' + cost.toFixed(4);
                    }
                    break;

                case 'debugLogStatus':
                    if (message.enabled) {
                        debugLogIndicator.classList.add('active');
                    } else {
                        debugLogIndicator.classList.remove('active');
                    }
                    break;

                case 'agentStatus':
                    // v1.11.8, v1.12.0: Handle agent mode + checkpoint status updates
                    const agentBadgeEl = document.getElementById('agentBadge');
                    const undoBadgeEl = document.getElementById('undoBadge');

                    if (message.enabled) {
                        // Agent mode is ON
                        agentBadgeEl.classList.remove('disabled');
                        agentBadgeEl.classList.add('enabled');

                        // Remove all checkpoint classes first
                        agentBadgeEl.classList.remove('checkpoint-git', 'checkpoint-file', 'checkpoint-none');

                        // Update based on checkpoint backend (v1.12.0)
                        if (message.checkpoint) {
                            const backend = message.checkpoint.backend;
                            const lastCheckpoint = message.checkpoint.last_checkpoint;

                            if (backend === 'git') {
                                agentBadgeEl.classList.add('checkpoint-git');
                                agentBadgeEl.textContent = 'Agent 🔒';
                                agentBadgeEl.title = 'Agent mode ON (Checkpoints: git)\\n• Auto-commits before tasks\\n• Use Undo button to revert';
                            } else if (backend === 'file') {
                                agentBadgeEl.classList.add('checkpoint-file');
                                agentBadgeEl.textContent = 'Agent ⚠️';
                                agentBadgeEl.title = 'Agent mode ON (Checkpoints: file)\\n• Snapshots saved to ~/.ppxai/checkpoints\\n• Use Undo button to revert\\n• Tip: Init git repo for atomic commits';
                            } else {
                                agentBadgeEl.classList.add('checkpoint-none');
                                agentBadgeEl.textContent = 'Agent ⚠️';
                                agentBadgeEl.title = 'Agent mode ON (Checkpoints: DISABLED)\\n• Changes CANNOT be undone\\n• Initialize git repo to enable checkpoints';
                            }

                            // Update undo button (v1.12.1: validity-aware styling)
                            const isValid = message.checkpoint.is_valid !== false;  // Default true for backward compat
                            undoBadgeEl.classList.remove('enabled', 'disabled', 'stale');

                            if (lastCheckpoint) {
                                const shortId = lastCheckpoint.length > 8 ? lastCheckpoint.substring(0, 8) : lastCheckpoint;
                                undoBadgeEl.classList.add('visible');

                                if (isValid) {
                                    // Valid checkpoint: blue enabled
                                    undoBadgeEl.classList.add('enabled');
                                    undoBadgeEl.title = \`Undo Last Agent Task\\nCheckpoint: \${shortId} (\${backend})\`;
                                } else {
                                    // Stale checkpoint: red disabled
                                    undoBadgeEl.classList.add('stale');
                                    const reason = message.checkpoint.validity_reason || 'Checkpoint is stale';
                                    undoBadgeEl.title = \`Cannot Undo: \${reason}\\nCheckpoint: \${shortId} (STALE)\\nUse 'git revert \${shortId}' manually if needed\`;
                                }
                            } else {
                                // No checkpoint: grey disabled
                                undoBadgeEl.classList.add('visible', 'disabled');
                                undoBadgeEl.title = 'No checkpoint to undo';
                            }
                        } else {
                            // No checkpoint info (old server or disabled)
                            agentBadgeEl.textContent = 'Agent: on';
                            agentBadgeEl.title = 'Agent mode enabled - click to disable';
                            undoBadgeEl.classList.remove('visible');
                        }
                    } else {
                        // Agent mode is OFF
                        agentBadgeEl.textContent = 'Agent: off';
                        agentBadgeEl.classList.add('disabled');
                        agentBadgeEl.classList.remove('enabled', 'checkpoint-git', 'checkpoint-file', 'checkpoint-none');
                        agentBadgeEl.title = 'Click to enable agent mode';

                        // Hide undo button when agent is off (v1.12.1: also clear stale class)
                        undoBadgeEl.classList.remove('visible', 'enabled', 'stale');
                        undoBadgeEl.classList.add('disabled');
                    }
                    break;

                case 'workspaceInfo':
                    const workspaceInfoEl = document.getElementById('workspaceInfo');
                    const workspacePathEl = document.getElementById('workspacePath');
                    const workspaceNameEl = document.getElementById('workspaceName');

                    if (message.hasWorkspace) {
                        workspacePathEl.textContent = message.path;
                        workspacePathEl.title = message.path;  // Show full path on hover
                        workspaceNameEl.textContent = message.name;
                        workspaceInfoEl.style.display = 'flex';
                    } else {
                        workspaceInfoEl.style.display = 'none';
                    }
                    break;

                case 'workingDirChanged':
                    // v1.13.2: Update workspace display when AI changes working directory
                    const wdInfoEl = document.getElementById('workspaceInfo');
                    const wdPathEl = document.getElementById('workspacePath');
                    const wdNameEl = document.getElementById('workspaceName');

                    if (message.path && wdInfoEl && wdPathEl && wdNameEl) {
                        const parts = message.path.split('/');
                        const name = parts[parts.length - 1] || message.path;
                        wdPathEl.textContent = message.path;
                        wdPathEl.title = message.path;
                        wdNameEl.textContent = name;
                        wdInfoEl.style.display = 'flex';
                    }
                    break;

                case 'updateContext':
                    // v1.13.9: Update context usage badge
                    if (contextBadge && contextUsage) {
                        const percent = message.percent || 0;
                        contextUsage.textContent = 'Ctx: ' + percent.toFixed(0) + '%' + (message.suffix || '');
                        contextBadge.classList.remove('warning', 'critical');
                        if (message.badgeClass) {
                            contextBadge.classList.add(message.badgeClass);
                        }
                        contextBadge.title = 'Context: ' + percent.toFixed(1) + '% used - Click to clear injected files';
                    }
                    break;

                case 'serverStatus':
                    // Update server status badge (v1.13.1)
                    updateServerStatus(message.connected, message.connecting);
                    break;

                case 'history':
                    // Clear existing messages except typing indicator
                    messagesContainer.innerHTML = '';
                    typingIndicator = document.createElement('div');
                    typingIndicator.className = 'typing-indicator';
                    typingIndicator.id = 'typingIndicator';
                    typingIndicator.textContent = 'Thinking... (Press Esc to stop)';
                    messagesContainer.appendChild(typingIndicator);
                    lastMessageTime = null; // Reset time tracking for history

                    message.messages.forEach(msg => {
                        if (msg.role !== 'system') {
                            addMessage(msg.role, msg.content, msg.role === 'assistant');
                        }
                    });
                    break;

                case 'cleared':
                    messagesContainer.innerHTML = '';
                    typingIndicator = document.createElement('div');
                    typingIndicator.className = 'typing-indicator';
                    typingIndicator.id = 'typingIndicator';
                    typingIndicator.textContent = 'Thinking... (Press Esc to stop)';
                    messagesContainer.appendChild(typingIndicator);
                    lastMessageTime = null; // Reset time tracking
                    break;

                case 'fileSuggestions':
                    // Received file suggestions for autocomplete
                    // v1.13.8: Don't show if input was cleared (message sent during async request)
                    if (!messageInput.value.includes('@')) {
                        break;
                    }
                    // Don't show if autocomplete is disabled (e.g., @git, @tree special providers)
                    if (!autocompleteDisabled && (autocompleteMode === 'file' || message.files.length > 0)) {
                        showAutocomplete(message.files, 'file');
                    }
                    break;
            }
        });

        function formatFileSize(bytes) {
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
        }

        function formatTimestamp() {
            const now = new Date();
            const h = now.getHours().toString().padStart(2, '0');
            const m = now.getMinutes().toString().padStart(2, '0');
            const s = now.getSeconds().toString().padStart(2, '0');
            const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                           'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
            const mon = months[now.getMonth()];
            const day = now.getDate();
            return h + ':' + m + ':' + s + ' ' + mon + ' ' + day;
        }

        function formatDividerLabel(date) {
            const now = new Date();
            const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
            const msgDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
            const diffDays = Math.floor((today - msgDate) / (1000 * 60 * 60 * 24));

            const timeStr = date.getHours().toString().padStart(2, '0') + ':' +
                           date.getMinutes().toString().padStart(2, '0');

            if (diffDays === 0) {
                return 'Today ' + timeStr;
            } else if (diffDays === 1) {
                return 'Yesterday ' + timeStr;
            } else if (diffDays < 7) {
                const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
                return days[date.getDay()] + ' ' + timeStr;
            } else {
                const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
                return months[date.getMonth()] + ' ' + date.getDate() + ' ' + timeStr;
            }
        }

        function shouldShowTimeDivider(currentTime) {
            if (!lastMessageTime) return true; // First message always shows divider

            const lastDate = new Date(lastMessageTime.getFullYear(), lastMessageTime.getMonth(), lastMessageTime.getDate());
            const currDate = new Date(currentTime.getFullYear(), currentTime.getMonth(), currentTime.getDate());

            // Always show if date changed
            if (lastDate.getTime() !== currDate.getTime()) return true;

            // Show if gap is more than threshold
            return (currentTime - lastMessageTime) >= TIME_GAP_THRESHOLD_MS;
        }

        function addTimeDivider(date) {
            const divider = document.createElement('div');
            divider.className = 'time-divider';
            const label = document.createElement('span');
            label.className = 'time-divider-label';
            label.textContent = formatDividerLabel(date);
            divider.appendChild(label);
            messagesContainer.insertBefore(divider, typingIndicator);
        }

        function addMessage(role, content, useMarkdown = true) {
            const now = new Date();

            // Check if we should show a time divider before this message
            // Only show dividers for user messages (start of new interaction)
            if (role === 'user' && shouldShowTimeDivider(now)) {
                addTimeDivider(now);
            }

            const el = document.createElement('div');
            el.className = 'message ' + role;

            // Add timestamp
            const timestamp = document.createElement('span');
            timestamp.className = 'message-timestamp';
            timestamp.textContent = formatTimestamp();
            el.appendChild(timestamp);

            // Update last message time
            lastMessageTime = now;

            // Add content
            const contentEl = document.createElement('div');
            contentEl.className = 'message-content';
            if (useMarkdown && content) {
                try {
                    contentEl.innerHTML = parseMarkdown(content);
                    // parseMarkdown() already extracts and renders markdown code blocks
                    // Just apply syntax highlighting to regular code blocks (skip rendered markdown content)
                    contentEl.querySelectorAll('pre code').forEach((block) => {
                        // Skip code blocks inside rendered markdown divs
                        if (block.closest('.rendered-markdown-content')) return;

                        hljs.highlightElement(block);
                    });
                } catch (e) {
                    console.error('Markdown parse error:', e);
                    contentEl.textContent = content;
                }
            } else {
                contentEl.textContent = content;
            }
            el.appendChild(contentEl);

            messagesContainer.insertBefore(el, typingIndicator);
            scrollToBottom();
            return el;
        }

        // v1.13.9: Append reasoning chunk to collapsible section
        function appendReasoningChunk(messageEl, chunk) {
            if (!messageEl || !chunk) return;

            const contentEl = messageEl.querySelector('.message-content');
            if (!contentEl) return;

            // Find or create reasoning section
            let reasoningSection = contentEl.querySelector('.reasoning-section');
            if (!reasoningSection) {
                reasoningSection = document.createElement('details');
                reasoningSection.className = 'reasoning-section';
                reasoningSection.open = true; // Start open while streaming
                reasoningSection.innerHTML = \`
                    <summary class="reasoning-header">
                        <span class="reasoning-icon">💭</span>
                        <span class="reasoning-title">Thinking...</span>
                    </summary>
                    <div class="reasoning-content"></div>
                \`;
                contentEl.insertBefore(reasoningSection, contentEl.firstChild);
            }

            // Append chunk to reasoning content
            const reasoningContent = reasoningSection.querySelector('.reasoning-content');
            if (reasoningContent) {
                reasoningContent.textContent += chunk;
            }
            scrollToBottom();
        }

        // v1.13.9: Close reasoning section when main content starts
        function closeReasoningSection(messageEl) {
            if (!messageEl) return;
            const contentEl = messageEl.querySelector('.message-content');
            if (!contentEl) return;

            const reasoningSection = contentEl.querySelector('.reasoning-section');
            if (reasoningSection) {
                // Update title to show it's complete
                const title = reasoningSection.querySelector('.reasoning-title');
                if (title) {
                    title.textContent = 'Thought process';
                }
                // Collapse the section
                reasoningSection.open = false;
            }
        }

        // v1.12.0: Add tool message with collapsible details
        function addToolMessage(role, title, details, verbose) {
            const now = new Date();
            const el = document.createElement('div');
            el.className = 'message ' + role;

            // Add timestamp
            const timestamp = document.createElement('span');
            timestamp.className = 'message-timestamp';
            timestamp.textContent = formatTimestamp();
            el.appendChild(timestamp);

            // Update last message time
            lastMessageTime = now;

            // Tool title (clickable to toggle details)
            const titleEl = document.createElement('div');
            const isCollapsed = verbose !== true;
            titleEl.className = 'tool-title' + (details ? ' clickable' : '') + (isCollapsed ? ' collapsed' : '');
            titleEl.textContent = title;
            el.appendChild(titleEl);

            // Details (always created, collapsed by default unless verbose ON)
            if (details) {
                const contentEl = document.createElement('pre');
                contentEl.className = 'tool-details-content' + (isCollapsed ? ' collapsed' : '');
                const codeEl = document.createElement('code');
                codeEl.textContent = details;
                contentEl.appendChild(codeEl);
                el.appendChild(contentEl);

                // Click title to toggle collapse
                titleEl.addEventListener('click', () => {
                    contentEl.classList.toggle('collapsed');
                    titleEl.classList.toggle('collapsed');
                });
            }

            messagesContainer.insertBefore(el, typingIndicator);
            scrollToBottom();
            return el;
        }

        function scrollToBottom() {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }

        // Signal ready
        vscode.postMessage({ type: 'ready' });
    </script>
</body>
</html>`;
    }
}
