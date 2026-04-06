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
import { openHtmlPreview, closeHtmlPreview } from './previewPanel';

// Import shared modules for command definitions and formatters
import {
    generateHelpText
} from './shared/commands';
import {
    formatCheckpointInfo,
    formatCheckpointBackendHelp,
    formatUsageStats,
    formatUsageDisplayHelp,
    formatStatus,
    formatProvidersList,
    formatModelsList,
    formatSessionsList,
    formatTableResult,
    formatKeyValueResult,
    CommandResultData
} from './shared/formatters';

import { AppState } from './appState';

// Import extracted handlers (Phase 2-4 refactoring)
import {
    HandlerContext,
    handleToolsCommand as toolsHandler,
    handleCheckpointCommand as checkpointHandler,
    handleLsCommand as lsHandler,
    handleTreeCommand as treeHandler,
    ChatEventBus,
    processStreamEvent,
    AgentStateMachine,
    handleFileConsent,
    handleShellConsent,
    ConsentContext
} from './handlers';

export class ChatViewProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'ppxai.chatView';

    private _view?: vscode.WebviewView;
    private _backend: HttpClient;
    private _context: vscode.ExtensionContext;

    // Phase 3a: EventBus for decoupled event handling
    private _eventBus: ChatEventBus = new ChatEventBus();

    // v1.17.3: Canonical application state
    private _appState: AppState = new AppState();

    // Phase 4a: Agent state machine (initialized lazily after backend available)
    private _agentStateMachine?: AgentStateMachine;

    constructor(
        context: vscode.ExtensionContext,
        backend: HttpClient
    ) {
        this._context = context;
        this._backend = backend;
    }

    /**
     * Create handler context for dependency injection (IoC pattern).
     * Provides extracted handlers with necessary dependencies without
     * exposing ChatViewProvider internals.
     */
    private getHandlerContext(): HandlerContext | null {
        if (!this._view) { return null; }

        const view = this._view;
        return {
            postMessage: (msg) => {
                view.webview.postMessage(msg);
                if (msg?.content && (msg.type === 'systemMessage' || msg.type === 'error')) {
                    const level = msg.type === 'error' ? 'error' : 'info';
                    this._backend.logClientEvent(level, msg.content);
                }
            },
            backend: this._backend,
            updateStatus: () => this.updateStatus(),
            updateAgentStatus: () => this.updateAgentStatus(),
            dialogs: {
                showWarningMessage: (message, options, ...actions) =>
                    vscode.window.showWarningMessage(message, options, ...actions)
            }
        };
    }

    /**
     * Create consent context for dependency injection (Phase 4b).
     * Bridges VSCode-agnostic consent handlers with VSCode APIs.
     */
    private getConsentContext(): ConsentContext {
        return {
            backend: this._backend,
            eventBus: this._eventBus,
            runInTerminal: this.runCommandInTerminal.bind(this),  // v1.14.2
            dialogs: {
                showQuickPick: async (items, options) => {
                    const result = await vscode.window.showQuickPick(items, options);
                    return result as { label: string; detail: string; value: 'y' | 'n' | 'always' | 'never' | 'terminal' } | undefined;
                }
            }
        };
    }

    /**
     * Run a command in VSCode integrated terminal (v1.14.2).
     * Used for interactive commands like kubectl exec -it, python REPL, etc.
     *
     * @param command The shell command to execute
     * @param workingDir Working directory for the command
     */
    private runCommandInTerminal(command: string, workingDir: string): void {
        // Create a unique terminal name based on command
        const shortCmd = command.length > 30 ? command.substring(0, 30) + '...' : command;
        const terminalName = `ppxai: ${shortCmd}`;

        // Create terminal with working directory
        const terminal = vscode.window.createTerminal({
            name: terminalName,
            cwd: workingDir !== '.' ? workingDir : undefined,
            iconPath: new vscode.ThemeIcon('terminal')
        });

        // Show terminal and send command
        terminal.show();
        terminal.sendText(command);

        // Notify webview that command is running in terminal
        this._view?.webview.postMessage({
            type: 'terminalExecuted',
            command: command,
            workingDir: workingDir
        });
    }

    /**
     * Get or create the agent state machine (Phase 4a).
     * Lazy initialization to ensure backend is available.
     */
    private getAgentStateMachine(): AgentStateMachine {
        if (!this._agentStateMachine) {
            this._agentStateMachine = new AgentStateMachine(this._eventBus, this._backend);
        }
        return this._agentStateMachine;
    }

    /**
     * Wire up EventBus subscriptions for UI updates.
     * Phase 3c: Translates EventBus events to webview postMessage calls.
     *
     * This decouples event producers (stream handlers, consent handlers)
     * from UI rendering, enabling isolated testing of each component.
     */
    private wireUISubscriptions(): void {
        const postMessage = (msg: unknown) => {
            this._view?.webview.postMessage(msg);
            // Forward system messages and errors to server debug log
            const m = msg as { type?: string; content?: string };
            if (m?.content && (m.type === 'systemMessage' || m.type === 'error')) {
                const level = m.type === 'error' ? 'error' : 'info';
                this._backend.logClientEvent(level, m.content);
            }
        };

        // Stream events -> webview messages
        this._eventBus.on('stream:thinking', (content) => {
            postMessage({ type: 'thinking', content });
        });

        this._eventBus.on('stream:started', (content) => {
            postMessage({ type: 'started', content });
        });

        this._eventBus.on('stream:chunk', (content) => {
            postMessage({ type: 'chunk', content });
        });

        this._eventBus.on('stream:reasoning', (content) => {
            postMessage({ type: 'reasoning_chunk', content });
        });

        this._eventBus.on('stream:tool_group_start', (data) => {
            postMessage({ type: 'toolGroupStart', data });
        });

        this._eventBus.on('stream:tool_group_end', (data) => {
            postMessage({ type: 'toolGroupEnd', data });
        });

        this._eventBus.on('stream:tool_call', (data) => {
            postMessage({
                type: 'toolCall',
                tool: data.tool,
                arguments: data.arguments,
                verbose: this._backend.toolsVerbose
            });
        });

        this._eventBus.on('stream:tool_result', (data) => {
            postMessage({
                type: 'toolResult',
                tool: data.tool,
                result: data.result,
                verbose: this._backend.toolsVerbose
            });
        });

        this._eventBus.on('stream:context_injected', (data) => {
            postMessage({
                type: 'contextInjected',
                source: data.source,
                language: data.language,
                size: data.size,
                truncated: data.truncated
            });
        });

        // v1.15.2: Handle display_file event - open file in VSCode editor
        this._eventBus.on('stream:display_file', async (filepath) => {
            try {
                const uri = vscode.Uri.file(filepath);
                const doc = await vscode.workspace.openTextDocument(uri);
                await vscode.window.showTextDocument(doc, vscode.ViewColumn.Beside);
            } catch (error) {
                console.error(`Failed to open file from display_file event: ${filepath}`, error);
                // Silently fail - the AI tool already reported the action in chat
            }
        });

        this._eventBus.on('stream:done', (content) => {
            if (content && content.trim()) {
                postMessage({ type: 'fullResponse', content });
            } else {
                postMessage({ type: 'emptyResponse' });
            }
        });

        this._eventBus.on('stream:error', (content) => {
            postMessage({ type: 'error', content });
        });

        this._eventBus.on('stream:status', (content) => {
            postMessage({ type: 'systemMessage', content });
        });

        // Agent events -> webview messages
        this._eventBus.on('agent:iteration', (n, max) => {
            postMessage({
                type: 'systemMessage',
                content: `━━━ Iteration ${n}/${max} ━━━`
            });
        });

        this._eventBus.on('agent:complete', (summary) => {
            let message = '✅ Task completed!';
            if (summary) {
                message += `\nSummary: ${summary}`;
            }
            postMessage({ type: 'systemMessage', content: message });
        });

        this._eventBus.on('agent:max_iterations', (iterations) => {
            postMessage({
                type: 'systemMessage',
                content: `⚠️  Max iterations (${iterations}) reached\nTask may be incomplete. Review output above.`
            });
        });

        this._eventBus.on('agent:error', (message) => {
            postMessage({ type: 'error', content: message });
        });

        // State sync — engine pushes AppState field changes via SSE
        this._eventBus.on('state:sync', (changes: Record<string, any>) => {
            // Python snake_case → TS camelCase
            const keyMap: Record<string, string> = {
                provider: 'currentProvider',
                model: 'currentModel',
                tools_enabled: 'toolsEnabled',
                tools_verbose: 'toolsVerbose',
                agent_mode: 'agentMode',
                auto_route: 'autoRoute',
                working_dir: 'workingDir',
                session_name: 'sessionName',
                debug_log: 'debugLog',
                context_attachments: 'contextAttachments',  // v1.17.4 Phase 6.3
            };
            const mapped: Record<string, any> = {};
            for (const [pyKey, value] of Object.entries(changes)) {
                const tsKey = keyMap[pyKey] || pyKey;
                mapped[tsKey] = value;
            }
            this._appState.update(mapped as any);
            postMessage({ type: 'stateSync', changes: mapped });
        });

        // UI events
        this._eventBus.on('ui:working_dir_changed', (path) => {
            postMessage({ type: 'workingDirChanged', path });
        });

        this._eventBus.on('ui:status_update', () => {
            this.updateStatus();
        });

        this._eventBus.on('ui:clear', () => {
            postMessage({ type: 'cleared' });
        });

        // Consent events -> VSCode dialogs (Phase 4b: uses extracted handlers)
        const consentCtx = this.getConsentContext();
        this._eventBus.on('consent:file_request', async (data, metadata) => {
            await handleFileConsent(consentCtx, data, metadata);
        });

        this._eventBus.on('consent:shell_request', async (data) => {
            await handleShellConsent(consentCtx, data);
        });
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

        // Phase 3c: Wire up EventBus subscriptions for decoupled UI updates
        try {
            console.log('[ppxai] Wiring UI subscriptions...');
            this.wireUISubscriptions();
            console.log('[ppxai] UI subscriptions wired successfully');
        } catch (e) {
            console.error('[ppxai] Error wiring UI subscriptions:', e);
        }

        // Handle messages from the webview
        console.log('[ppxai] Setting up webview message handler...');
        webviewView.webview.onDidReceiveMessage(async (message) => {
            console.log('[ppxai] Received message from webview:', message.type);
            switch (message.type) {
                case 'chat':
                    // v1.17.4 Phase 6.1: webview may include files[] for multimodal
                    await this.handleChat(message.content, message.files);
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
                case 'toggleVerboseTools':
                    await this.handleToggleVerboseTools(message.enable);
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

    private async handleChat(content: string, files?: Array<{name: string; media_type: string; data: string}>) {
        if (!this._view) { return; }

        const trimmed = content.trim();

        // Check if it's a slash command
        if (trimmed.startsWith('/')) {
            await this.handleSlashCommand(trimmed);
            return;
        }

        // Regular chat message
        // Show user message (include attachment hint if files present)
        const displayContent = files && files.length > 0
            ? `${content}\n\n[Attached: ${files.map(f => f.name).join(', ')}]`
            : content;
        this._view.webview.postMessage({
            type: 'userMessage',
            content: displayContent
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
            // v1.17.4 Phase 6.1: pass files array to the backend
            // chat method so they get included in the POST /chat body.
            // When no files are attached, behavior is unchanged.
            await this._backend.chat(finalMessage, (event) => {
                this.handleStreamEvent(event);
            }, files);
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

        // All event handling via EventBus (v1.15.4: removed legacy switch)
        // See wireUISubscriptions() for all event subscribers
        processStreamEvent(event, this._eventBus);
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
                                await this.updateStatus();  // v1.15.3: Update provider/model from restored session
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
                            await this.updateStatus();  // v1.15.3: Update provider/model from restored session
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
                            const result = await this._backend.setModel((selected as any).id);
                            await this.updateStatus();
                            let msg = `✓ Switched to model: ${selected.label}`;
                            if (result.contextReset > 0) {
                                msg += ` (${result.contextReset} messages cleared from context)`;
                            }
                            this._view.webview.postMessage({
                                type: 'systemMessage',
                                content: msg
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
                        const result = await this._backend.setModel(args[0]);
                        if (result.ok) {
                            await this.updateStatus();
                            let msg = `✓ Switched to model: ${args[0]}`;
                            if (result.contextReset > 0) {
                                msg += ` (${result.contextReset} messages cleared from context)`;
                            }
                            this._view.webview.postMessage({
                                type: 'systemMessage',
                                content: msg
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
                            const result = await this._backend.setProvider((selected as any).id);
                            await this.updateStatus();
                            let msg = `✓ Switched to provider: ${selected.label}`;
                            if (result.contextReset > 0) {
                                msg += ` (${result.contextReset} messages cleared from context)`;
                            }
                            this._view.webview.postMessage({
                                type: 'systemMessage',
                                content: msg
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
                        const result = await this._backend.setProvider(args[0]);
                        if (result.ok) {
                            await this.updateStatus();
                            let msg = `✓ Switched to provider: ${args[0]}`;
                            if (result.contextReset > 0) {
                                msg += ` (${result.contextReset} messages cleared from context)`;
                            }
                            this._view.webview.postMessage({
                                type: 'systemMessage',
                                content: msg
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

                case '/edit':
                    await this.handleEditCommand(args);
                    break;

                case '/cd':
                    await this.handleCdCommand(args);
                    break;

                case '/pwd':
                    await this.handlePwdCommand();
                    break;

                case '/ls':
                    await this.handleLsCommand(args);
                    break;

                case '/tree':
                    await this.handleTreeCommand(args);
                    break;

                case '/preview':
                    await this.handlePreviewCommand(args);
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

    /**
     * Handle /tools command - delegates to extracted handler (Phase 2 refactoring)
     */
    private async handleToolsCommand(args: string[]): Promise<void> {
        const ctx = this.getHandlerContext();
        if (!ctx) { return; }
        await toolsHandler(ctx, args);
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
     * Handle /checkpoint command - delegates to extracted handler (Phase 2 refactoring)
     */
    private async handleCheckpointCommand(args: string[]): Promise<void> {
        const ctx = this.getHandlerContext();
        if (!ctx) { return; }
        await checkpointHandler(ctx, args);
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
            } else if (subcommand === 'reload') {
                // Reload bootstrap context from disk (v1.14.1)
                const result = await this._backend.reloadBootstrapContext();
                if (result.success && result.loaded) {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `✓ Bootstrap context reloaded from: \`${result.source}\``
                    });
                } else if (result.success && !result.loaded) {
                    const workingDir = await this._backend.getWorkingDir();
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `No bootstrap context found in: \`${workingDir || 'current directory'}\``
                    });
                } else {
                    this._view.webview.postMessage({
                        type: 'error',
                        content: 'Failed to reload bootstrap context.'
                    });
                }
            } else if (subcommand === 'hints') {
                // Show active bootstrap hints (v1.14.0)
                const hints = await this._backend.getActiveHints();

                if (!hints.loaded) {
                    const workingDir = await this._backend.getWorkingDir();
                    let msg = '**No bootstrap context loaded.**\n';
                    msg += `Working directory: \`${workingDir || 'unknown'}\`\n`;
                    msg += '\n*Create AGENTS.md or CLAUDE.md in your project directory,*\n';
                    msg += '*or use `/wd <path>` to navigate to a directory with one.*';
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: msg
                    });
                    return;
                }

                let msg = '**Active Bootstrap Hints**\n';
                msg += `  Source: \`${hints.source}\`\n`;
                msg += `  Provider: ${hints.provider}\n`;
                msg += `  Model: ${hints.model}\n`;

                // Provider hints
                if (hints.provider_hints.length > 0) {
                    msg += `\n**Provider Hints:** (${hints.provider_hints.length} active)`;
                    if (hints.inherited_local) {
                        msg += ' *(includes inherited "local" hints)*';
                    }
                    msg += '\n';
                    for (const [source, hint] of hints.provider_hints) {
                        const displayHint = hint.length > 80 ? hint.substring(0, 80) + '...' : hint;
                        msg += `  • [${source}] ${displayHint}\n`;
                    }
                } else {
                    msg += '\n**Provider Hints:** *none active*';
                    if (hints.all_provider_keys.length > 0) {
                        msg += `\n  Available: ${hints.all_provider_keys.join(', ')}`;
                    }
                    msg += '\n';
                }

                // Model hints
                if (hints.model_hints.length > 0) {
                    msg += `\n**Model Hints:** (${hints.model_hints.length} active)`;
                    msg += `\n  Matched patterns: ${hints.matched_patterns.join(', ')}\n`;
                    for (const [pattern, hint] of hints.model_hints) {
                        const displayHint = hint.length > 80 ? hint.substring(0, 80) + '...' : hint;
                        msg += `  • [${pattern}] ${displayHint}\n`;
                    }
                } else {
                    msg += '\n**Model Hints:** *none active*';
                    if (hints.all_model_patterns.length > 0) {
                        msg += `\n  Available patterns: ${hints.all_model_patterns.join(', ')}`;
                    }
                    msg += '\n';
                }

                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: msg
                });
            } else if (subcommand === 'show') {
                // Show bootstrap context hierarchy (v1.14.2)
                const status = await this._backend.getBootstrapStatus();

                if (!status.loaded) {
                    const workingDir = await this._backend.getWorkingDir();
                    let msg = '**No bootstrap context loaded.**\n';
                    msg += `Working directory: \`${workingDir || 'unknown'}\`\n\n`;
                    msg += '*Scope search order:*\n';
                    msg += '1. `~/.ppxai/AGENTS.md` (global)\n';
                    msg += '2. `{git_root}/AGENTS.md` (project)\n';
                    msg += '3. `{cwd}/AGENTS.md` (subdir)\n\n';
                    msg += '*Create AGENTS.md or CLAUDE.md in any of these locations.*';
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: msg
                    });
                    return;
                }

                const sources = status.sources || [];
                const totalSize = status.total_size || 0;
                const charCount = status.char_count || 0;
                const estimatedTokens = Math.floor(charCount / 4);

                let msg = '**Bootstrap Context**\n\n';
                msg += `**Sources:** (${sources.length} file${sources.length !== 1 ? 's' : ''})\n`;

                const scopeBadges: Record<string, string> = {
                    'global': '🌐 global',
                    'project': '📁 project',
                    'subdir': '📂 subdir'
                };

                for (let i = 0; i < sources.length; i++) {
                    const src = sources[i];
                    const sizeKb = (src.size / 1024).toFixed(1);
                    const badge = scopeBadges[src.scope] || src.scope;
                    msg += `${i + 1}. \`${src.path}\`\n`;
                    msg += `   [${badge}] ${sizeKb} KB\n`;
                }

                const totalKb = (totalSize / 1024).toFixed(1);
                msg += `\n**Total:** ${totalKb} KB (~${estimatedTokens.toLocaleString()} tokens)\n`;

                // Hints summary
                if (status.has_hints) {
                    msg += '\n**Hints Defined:**\n';
                    if (status.provider_hints && status.provider_hints.length > 0) {
                        msg += `  Provider: ${status.provider_hints.join(', ')}\n`;
                    }
                    if (status.model_hints && status.model_hints.length > 0) {
                        msg += `  Model: ${status.model_hints.join(', ')}\n`;
                    }
                } else {
                    msg += '\n**Hints:** *none defined*\n';
                }

                msg += '\n*Tip: `/context hints` shows active hints for current provider/model*';

                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: msg
                });
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

    private async handleToggleVerboseTools(enable: boolean) {
        if (!this._view) { return; }

        try {
            await this._backend.setToolConfig('verbose', enable ? 'on' : 'off');
            this._appState.set('toolsVerbose', enable);

            this._view.webview.postMessage({
                type: 'systemMessage',
                content: `✓ Verbose tool output ${enable ? 'enabled' : 'disabled'}`
            });
            this._view.webview.postMessage({
                type: 'verboseToolsStatus',
                enabled: enable
            });
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Failed to toggle verbose tools: ${error}`
            });
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
        console.log(`[ppxai] handleToggleServer called with stop=${stop}`);
        if (!this._view) {
            console.log('[ppxai] handleToggleServer: no view, returning');
            return;
        }

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

        // v1.16.1: Delegate to shared command handler via POST /command/usage
        try {
            const result = await this._backend.executeCommand('usage', args.join(' '));
            this.renderCommandResult(result);
        } catch (error) {
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: `Failed to get usage: ${error}`
            });
        }
    }

    /**
     * Render a server-side CommandResult in the webview.
     *
     * Generic dispatcher for all command result types returned by
     * POST /command/{name}. Works for any command, not just /usage.
     *
     * v1.16.1: Added for CommandFactory server-side execution.
     */
    private renderCommandResult(result: CommandResultData) {
        if (!this._view) { return; }

        let content: string;
        switch (result.type) {
            case 'TableResult':
            case 'DirectoryListingResult':
                content = formatTableResult(result);
                break;
            case 'KeyValueResult':
                content = formatKeyValueResult(result);
                break;
            case 'ErrorResult': {
                const suggestions = result.suggestions || [];
                content = result.message +
                    (suggestions.length ? '\n' + suggestions.join('\n') : '');
                break;
            }
            case 'ConfirmationResult':
            case 'NotificationResult':
            default:
                content = result.message;
        }
        this._view.webview.postMessage({ type: 'systemMessage', content });
        this._backend.logClientEvent('info', content);
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

    /**
     * Handle /edit command - open file in VSCode native editor (v1.14.1)
     *
     * Supports line and column numbers:
     * - /edit file.py           - Opens file at line 1
     * - /edit file.py:42        - Opens file at line 42
     * - /edit file.py:42:10     - Opens file at line 42, column 10
     *
     * Unlike /show which opens beside, /edit opens in the primary editor
     * as the user likely wants to make edits.
     */
    private async handleEditCommand(args: string[]) {
        if (!this._view) { return; }

        if (args.length === 0) {
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: 'Usage: `/edit <filepath[:line[:col]]>`\n\nExamples:\n- `/edit README.md`\n- `/edit src/app.py:42`\n- `/edit config.ts:10:5`'
            });
            return;
        }

        const startTime = Date.now();
        let query = args.join(' ');

        // Parse line and column from filepath (e.g., "file.py:42:10")
        let targetLine = 1;
        let targetColumn = 1;

        // Match patterns like file.py:42 or file.py:42:10
        const lineColMatch = query.match(/^(.+?):(\d+)(?::(\d+))?$/);
        if (lineColMatch) {
            query = lineColMatch[1];  // File path without line/col
            targetLine = parseInt(lineColMatch[2], 10);
            if (lineColMatch[3]) {
                targetColumn = parseInt(lineColMatch[3], 10);
            }
        }

        const workspaceFolders = vscode.workspace.workspaceFolders;
        const fs = require('fs');
        const pathModule = require('path');

        let fullPath: string | undefined;

        // Check if it's a direct path first
        if (query.startsWith('/') || query.startsWith('~') || (query.length > 1 && query[1] === ':')) {
            // Absolute path (Unix, tilde expansion, or Windows drive letter)
            if (query.startsWith('~')) {
                const homedir = require('os').homedir();
                query = pathModule.join(homedir, query.slice(1));
            }
            fullPath = query;
        } else if (workspaceFolders && workspaceFolders.length > 0) {
            // Relative path - check workspace first
            const directPath = vscode.Uri.joinPath(workspaceFolders[0].uri, query).fsPath;
            if (fs.existsSync(directPath)) {
                fullPath = directPath;
            }
        }

        // If not found directly, try working directory
        if (!fullPath || !fs.existsSync(fullPath)) {
            const workingDir = await this._backend.getWorkingDir();
            if (workingDir) {
                const workingDirPath = pathModule.join(workingDir, query);
                if (fs.existsSync(workingDirPath)) {
                    fullPath = workingDirPath;
                }
            }
        }

        // If still not found, search
        if (!fullPath || !fs.existsSync(fullPath)) {
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: `*Searching for '${query}'...*`
            });

            const matches = await this.searchFiles(query);

            if (matches.length === 0) {
                this._view.webview.postMessage({
                    type: 'error',
                    content: `File not found: ${query}`
                });
                return;
            }

            if (matches.length === 1) {
                fullPath = matches[0].fsPath;
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
                    content: `**Multiple files found (${matches.length}):**\n${list}\n\n*Use exact path: /edit <path>*`
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

            // Open file in VSCode editor (primary editor, not beside)
            const uri = vscode.Uri.file(fullPath);
            const doc = await vscode.workspace.openTextDocument(uri);

            // Show the document with selection at the target line/column
            const editor = await vscode.window.showTextDocument(doc, {
                viewColumn: vscode.ViewColumn.One,
                preview: false  // Don't use preview mode - user wants to edit
            });

            // Jump to line/column (VSCode uses 0-based indexing)
            const position = new vscode.Position(Math.max(0, targetLine - 1), Math.max(0, targetColumn - 1));
            editor.selection = new vscode.Selection(position, position);
            editor.revealRange(
                new vscode.Range(position, position),
                vscode.TextEditorRevealType.InCenter
            );

            const filename = pathModule.basename(fullPath);
            const sizeKB = (stats.size / 1024).toFixed(1);
            const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);

            let locationInfo = '';
            if (targetLine > 1) {
                locationInfo = ` at line ${targetLine}`;
                if (targetColumn > 1) {
                    locationInfo += `:${targetColumn}`;
                }
            }

            this._view.webview.postMessage({
                type: 'systemMessage',
                content: `✏️ Editing **${filename}**${locationInfo} (${sizeKB} KB) • *${elapsed}s*`
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

    /**
     * Handle /ls command - delegates to extracted handler (v1.16.0)
     */
    private async handleLsCommand(args: string[]): Promise<void> {
        const ctx = this.getHandlerContext();
        if (!ctx) { return; }
        await lsHandler(ctx, args);
    }

    /**
     * Handle /tree command - delegates to extracted handler (v1.16.0)
     */
    private async handleTreeCommand(args: string[]): Promise<void> {
        const ctx = this.getHandlerContext();
        if (!ctx) { return; }
        await treeHandler(ctx, args);
    }

    /**
     * Handle /preview command - open live-reloading HTML preview (v1.15.4)
     */
    private async handlePreviewCommand(args: string[]) {
        if (!this._view) { return; }

        if (args.length === 0) {
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: 'Usage: `/preview <file.html>`\n\nExamples:\n- `/preview index.html`\n- `/preview close` — Close preview'
            });
            return;
        }

        const arg = args.join(' ').trim();

        // Handle /preview close
        if (arg.toLowerCase() === 'close') {
            closeHtmlPreview();
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: 'Preview closed'
            });
            return;
        }

        // Resolve filepath against workspace root
        const pathModule = require('path');
        let fullPath = arg;

        if (!pathModule.isAbsolute(arg)) {
            const workspaceFolders = vscode.workspace.workspaceFolders;
            if (workspaceFolders && workspaceFolders.length > 0) {
                fullPath = pathModule.resolve(workspaceFolders[0].uri.fsPath, arg);
            }
        }

        const success = await openHtmlPreview(fullPath);
        if (success) {
            const fileName = pathModule.basename(fullPath);
            this._view.webview.postMessage({
                type: 'systemMessage',
                content: `Preview opened: **${fileName}** (live-reload enabled)`
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

            // Sync full state to AppState
            this._appState.update({
                currentProvider: status.provider,
                currentModel: status.model,
                toolsEnabled: toolsStatus.enabled,
                toolsVerbose: status.tools_verbose || false,
                agentMode: status.agent_mode || false,
                autoRoute: status.auto_route || false,
                workingDir: status.working_dir || '',
                sessionName: status.session_name || '',
                debugLog: status.debug_log || false,
            });

            this._view.webview.postMessage({
                type: 'status',
                provider: status.provider,
                model: status.model,
                toolsEnabled: toolsStatus.enabled,
                toolsVerbose: status.tools_verbose || false,
                agentMode: status.agent_mode || false,
                debugLog: status.debug_log || false,
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

        // v1.17.3: Update hints badge
        await this.updateHintsBadge();
    }

    private async updateHintsBadge() {
        if (!this._view) { return; }
        try {
            const hints = await this._backend.getActiveHints();
            const provCount = (hints.provider_hints || []).length;
            const modelCount = (hints.model_hints || []).length;
            const total = provCount + modelCount;

            this._view.webview.postMessage({
                type: 'hintsStatus',
                loaded: hints.loaded,
                total,
                provCount,
                modelCount,
                source: hints.source || 'AGENTS.md',
            });
        } catch {
            // Hints are informational — don't block on failure
        }
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

    private _getHtmlForWebview(webview: vscode.Webview): string {
        // Get URIs for local resources
        const mediaPath = vscode.Uri.joinPath(this._context.extensionUri, 'media');
        const webviewPath = vscode.Uri.joinPath(mediaPath, 'webview');
        const highlightCssUri = webview.asWebviewUri(vscode.Uri.joinPath(mediaPath, 'highlight.css'));
        const highlightJsUri = webview.asWebviewUri(vscode.Uri.joinPath(mediaPath, 'highlight.min.js'));
        const markedJsUri = webview.asWebviewUri(vscode.Uri.joinPath(mediaPath, 'marked.min.js'));
        const webviewCssUri = webview.asWebviewUri(vscode.Uri.joinPath(webviewPath, 'styles.css'));
        const webviewJsUri = webview.asWebviewUri(vscode.Uri.joinPath(webviewPath, 'main.js'));

        // Generate nonce for CSP
        const nonce = this._getNonce();
        const version = this._context.extension.packageJSON.version;

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; script-src 'nonce-${nonce}' ${webview.cspSource}; font-src ${webview.cspSource};">
    <title>ppxai Chat</title>
    <!-- Highlight.js for syntax highlighting -->
    <link rel="stylesheet" href="${highlightCssUri}">
    <script nonce="${nonce}" src="${highlightJsUri}"></script>
    <!-- Marked for markdown parsing -->
    <script nonce="${nonce}" src="${markedJsUri}"></script>
    <!-- Webview styles -->
    <link rel="stylesheet" href="${webviewCssUri}">
</head>
<body>
    <div class="header">
        <div class="status">
            <span class="version-badge" title="Extension version">v${version}</span>
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
            <span class="hints-badge" id="hintsBadge" style="display: none;" title="No bootstrap hints loaded">
                <span id="hintsStatus">Hints</span>
            </span>
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
                    <div class="menu-item" id="verboseToolsMenuItem">
                        <span class="menu-indicator" id="verboseToolsIndicator"></span>
                        <span>Verbose Tools</span>
                    </div>
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
        <div class="input-hint">Type /help for commands • @file to reference • ↑/↓ for history • drag files to attach</div>
        <div class="attachment-badges hidden" id="attachmentBadges"></div>
        <div class="autocomplete-container">
            <div class="autocomplete-dropdown" id="autocompleteDropdown"></div>
            <div class="input-wrapper">
                <input type="file" id="fileInput" multiple style="display:none"
                       accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.xlsx,.pptx,.docx,.txt,.md,.py,.js,.ts,.json,.yaml,.yml">
                <button id="attachBtn" class="attach-btn" title="Attach files">📎</button>
                <textarea
                    id="messageInput"
                    placeholder="Ask anything or type / for commands..."
                    rows="1"
                ></textarea>
                <button id="sendBtn">Send</button>
            </div>
        </div>
    </div>

    <!-- Webview JavaScript -->
    <script nonce="${nonce}" src="${webviewJsUri}"></script>
</body>
</html>`;
    }
}
