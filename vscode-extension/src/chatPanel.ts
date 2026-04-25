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

// Import shared modules for command definitions and formatters.
// v1.18.1 5b.2: only generateHelpText is still used here (by showHelp,
// which augments factory /help output with VSCode keyboard shortcuts).
// The legacy result formatters were superseded by CommandRenderer; the
// status/usage/provider/model/session formatters were used by handlers
// removed in 5b.2.
import { generateHelpText } from './shared/commands';

import { AppState } from './appState';

// v1.18.1 envelope dispatch: factory result + side-effects rendering.
import { CommandRenderer, RendererHost } from './commandRenderer';
import { SideEffectsHandler, SideEffectHost } from './sideEffectsHandler';

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

// Cross-language state translation lives on the AppState class itself
// (see vscode-extension/src/appState.ts :: AppState.PYTHON_TO_TS +
// updateFromPython). This file only consumes AppState via
// `this._appState.updateFromPython(pythonPayload)` — no keyMaps here.

/**
 * v1.18.1 5b.2: commands that keep using `_backend.codingTask` so the
 * active editor's language + filename are sent along (the VSCode-only
 * context advantage). The factory has equivalents for all six, but
 * routing them through the envelope path would lose the editor
 * context. Map value is the `task_type` passed to `/coding_task`.
 *
 * /convert is chat-shaped too but has special arg parsing — handled
 * separately in `handleSlashCommand`.
 */
const CHAT_SHAPED_TASKS = new Map<string, string>([
    ['generate', 'generate'],
    ['explain', 'explain'],
    ['test', 'test'],
    ['docs', 'docs'],
    ['debug', 'debug'],
    ['implement', 'implement'],
]);

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

    // v1.18.1 5b: envelope dispatch helpers — render factory results +
    // translate side-effects to vscode.* APIs. Lazy because they need the
    // panel to be wired up first (postMessage / openHtmlPreview rely on
    // _view existing).
    private _commandRenderer?: CommandRenderer;
    private _sideEffectsHandler?: SideEffectsHandler;

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

    /** v1.18.1 5b: lazy renderer (CommandResult → systemMessage). */
    private getCommandRenderer(): CommandRenderer {
        if (!this._commandRenderer) {
            const host: RendererHost = {
                postSystemMessage: (content, level) => {
                    const type = level === 'error' ? 'error' : 'systemMessage';
                    this._view?.webview.postMessage({ type, content });
                    this._backend.logClientEvent(level === 'error' ? 'error' : 'info', content);
                },
                postToWebview: (msg) => {
                    this._view?.webview.postMessage(msg);
                },
            };
            this._commandRenderer = new CommandRenderer(host);
        }
        return this._commandRenderer;
    }

    /** v1.18.1 5b: lazy side-effects handler (envelope.side_effects → vscode.*). */
    private getSideEffectsHandler(): SideEffectsHandler {
        if (!this._sideEffectsHandler) {
            const host: SideEffectHost = {
                getWorkingDirHint: () => this._appState.get('workingDir') || undefined,
                openHtmlPreviewFromSideEffect: (filepath) => {
                    // Reuse the existing previewPanel — the chat-panel
                    // `/preview` UX path is identical to the side-effect
                    // path, so route both through openHtmlPreview.
                    void openHtmlPreview(filepath);
                },
                postToWebview: (msg) => {
                    this._view?.webview.postMessage(msg);
                },
                dispatchCommandFromSideEffect: async (cmd, args) => {
                    // PROMPT_QUICK_PICK resume: chosen value IS the next
                    // args (per ADR Q3 (b)). Re-issue the command via
                    // the factory dispatcher; no continuation state.
                    await this.dispatchFactoryCommand(cmd, args);
                },
            };
            this._sideEffectsHandler = new SideEffectsHandler(host);
        }
        return this._sideEffectsHandler;
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

        // State sync — engine pushes AppState field changes via SSE.
        //
        // Delegates translation and writes to the AppState facade:
        // `updateFromPython()` handles snake_case → camelCase mapping,
        // fires observers, and surfaces drift warnings for unknown
        // Python fields. See vscode-extension/src/appState.ts.
        //
        // Invariant: the server only pushes fields listed in
        // `_SSE_SYNC_FIELDS` at ppxai/engine/client.py. High-frequency
        // fields (tokens, cost, streaming flags) are excluded there
        // and reach the client via STREAM_END metadata or local state
        // writes during the SSE stream lifecycle.
        this._eventBus.on('state:sync', (changes: Record<string, any>) => {
            const mapped = this._appState.updateFromPython(changes);
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
                case 'complete':
                    await this.handleComplete(message.buffer, message.cursor);
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
                case 'previewFile':
                    await this.handlePreviewFile(message.fileId, message.name, message.data);
                    break;
            }
        });

        // v1.18.1 (state-sync Phase A): re-anchor AppState from
        // GET /state whenever the VSCode window regains focus. The
        // VSCode equivalent of the web app's `visibilitychange`
        // listener — without it, AppState drifts during long
        // idle periods (window unfocused, user switched apps) when
        // SSE state_sync events fire but no /chat is in flight to
        // drain the engine's side-channel queue.
        const focusListener = vscode.window.onDidChangeWindowState(
            (windowState) => {
                if (windowState.focused) {
                    this._reanchorFromServer();
                }
            }
        );
        webviewView.onDidDispose(() => focusListener.dispose());
    }

    /**
     * Pull the current AppState snapshot from the server and feed
     * it through the schema-driven facade.
     *
     * Called on `onDidChangeWindowState` → focused (v1.18.1
     * state-sync Phase A). Mirrors the web app's
     * `_reanchorFromServer` in ppxai/web/app.js — same shape, same
     * helper boundary, so the two clients can't drift in their
     * re-anchor behavior. Errors are swallowed because a transient
     * /state failure shouldn't break the chat panel.
     */
    private async _reanchorFromServer(): Promise<void> {
        try {
            const snapshot = await this._backend.fetchState();
            this._appState.updateFromPython(snapshot);
        } catch (e) {
            console.warn('[ppxai] state re-anchor failed:', e);
        }
    }

    /**
     * v1.17.4: Server-side autocomplete via POST /complete.
     *
     * Unified entry point for all autocomplete: slash commands +
     * aliases, subcommands (/tools, /usage, /checkpoint, /status,
     * /theme), dynamic /model + /provider name lookups, path-arg
     * completion, @file references, and @git/@tree/@clipboard/@url
     * context providers — everything goes through the engine's
     * CompletionProvider.
     *
     * The old `handleSearchFilesForAutocomplete` method was retired
     * in v1.17.4 because the engine now handles @file refs natively
     * and returns `@git` / `@tree` / `@clipboard` / `@url` alongside
     * the filesystem results.
     */
    private async handleComplete(buffer: string, cursor: number) {
        if (!this._view) { return; }
        try {
            const items = await this._backend.complete(buffer, cursor);
            this._view.webview.postMessage({
                type: 'completionItems',
                items
            });
        } catch {
            // Silently fail — autocomplete is optional
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

        // R15: Guard against empty user content. The extension auto-prepends
        // a `[Context: Working in VSCode workspace ...]` block to every chat
        // turn; if the user body is empty, the provider only sees that
        // synthetic context block, which trips Perplexity's strict
        // user/assistant alternation check and returns a 400.
        if (!trimmed && (!files || files.length === 0)) {
            this._view.webview.postMessage({
                type: 'error',
                content: 'Cannot send empty message.'
            });
            return;
        }

        // Regular chat message
        // Show user message with attachment metadata for inline thumbnails
        this._view.webview.postMessage({
            type: 'userMessage',
            content,
            files: files && files.length > 0 ? files : undefined
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

    /**
     * v1.18.1 5b.2: thin dispatcher over POST /command/<name>.
     *
     * Pre-v1.18.1 this was a 35-case switch with ~15 bespoke handlers
     * each duplicating the formatting + REST logic that the Python
     * `CommandFactory` already implements. The factory and the TS list
     * drifted; PyInstaller silently dropped 9 of 10 builtin command
     * modules at v1.17.4 (only `/usage` actually exercised the factory
     * path, so nobody noticed for six releases).
     *
     * v1.18.1 unifies dispatch:
     *   - Chat-shaped (LLM-streamed) commands keep using
     *     `_backend.codingTask` so the active editor's language +
     *     filename ride along (VSCode-only context advantage).
     *   - `/agent <task>` keeps its iteration loop here pending
     *     loop unification (see docs/TODO-v1.18.2-agent-loop-unification.md).
     *   - `/preview` keeps its own webview panel (VSCode-specific).
     *   - `/help` augments factory output with VSCode keyboard shortcuts.
     *   - `/checkpoint`, `/tools`, `/context` use already-extracted
     *     handlers (they hit bespoke REST today; full factory routing
     *     is deferred to a later phase).
     *   - Everything else flows through `dispatchFactoryCommand`,
     *     which unwraps the v1 envelope into rendered result + applied
     *     side-effects.
     */
    private async handleSlashCommand(input: string) {
        if (!this._view) { return; }

        const trimmed = input.trim();
        const parts = trimmed.split(/\s+/);
        // Strip leading slash for factory dispatch; case-insensitive.
        const command = parts[0].replace(/^\//, '').toLowerCase();
        const argsArr = parts.slice(1);
        const argsText = argsArr.join(' ');

        // Echo the user's command into the chat panel.
        this._view.webview.postMessage({
            type: 'commandMessage',
            content: input
        });

        try {
            // Chat-shaped commands keep client-side path so the active
            // editor's language + filename are sent along with the task.
            const codingTaskType = CHAT_SHAPED_TASKS.get(command);
            if (codingTaskType) {
                await this.handleCodingTaskCommand(codingTaskType, argsText);
                return;
            }

            // /convert is chat-shaped too (factory's handle_convert
            // blocks on the LLM, so we keep streaming via codingTask).
            if (command === 'convert') {
                await this.handleConvertCommand(argsArr);
                return;
            }

            // /agent: iteration loop runs client-side. Server gate
            // (added in 5b.1) validates min-words; we no longer
            // duplicate the check here.
            if (command === 'agent') {
                await this.handleAgentCommand(argsArr);
                return;
            }

            // /preview owns its own previewPanel.ts WebviewPanel —
            // VSCode-specific UX.
            if (command === 'preview') {
                await this.handlePreviewCommand(argsArr);
                return;
            }

            // /help: factory output + VSCode-specific keyboard shortcut
            // augmentation (TUI/web don't have these shortcuts).
            if (command === 'help' || command === 'h' || command === '?') {
                await this.showHelp();
                return;
            }

            // Already-extracted client-side handlers (Phase 2 refactor).
            // These hit bespoke REST today; full factory routing is a
            // later phase.
            if (command === 'tools') {
                await this.handleToolsCommand(argsArr);
                return;
            }
            if (command === 'checkpoint') {
                await this.handleCheckpointCommand(argsArr);
                return;
            }
            if (command === 'context') {
                await this.handleContextCommand(argsArr);
                return;
            }
            if (command === 'ls') {
                await this.handleLsCommand(argsArr);
                return;
            }
            if (command === 'tree') {
                await this.handleTreeCommand(argsArr);
                return;
            }

            // Everything else routes through the factory envelope.
            await this.dispatchFactoryCommand(command, argsText);
        } catch (error: any) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Command error: ${error?.message ?? error}`
            });
        }
    }

    /**
     * v1.18.1 5b.2: dispatch a command via the v1 wire envelope.
     *
     * Calls `POST /command/<name>` and translates the response:
     *   - `result`        → CommandRenderer (systemMessage / error)
     *   - `side_effects`  → SideEffectsHandler (vscode.* APIs)
     *   - `events`        → 5c will feed through state-sync (TODO)
     *
     * Per ADR Q3 (b), `prompt_quick_pick` resume happens inside the
     * side-effects handler: the chosen item's `value` becomes the next
     * `args` for the same command.
     */
    private async dispatchFactoryCommand(command: string, args: string): Promise<void> {
        if (!this._view) { return; }
        try {
            const envelope = await this._backend.executeCommand(command, args);
            this.getCommandRenderer().render(envelope.result);
            await this.getSideEffectsHandler().apply(envelope.side_effects);
            // TODO 5c: feed envelope.events through the state-sync path.
        } catch (error: any) {
            // 404 from the dispatcher: unknown command. Show the
            // friendly "type /help" message rather than the raw HTTP
            // error so the UX matches the pre-v1.18.1 default branch.
            const msg = error?.message ?? String(error);
            const isUnknown = /404|not\s*found|unknown\s*command/i.test(msg);
            this._view.webview.postMessage({
                type: 'error',
                content: isUnknown
                    ? `Unknown command: /${command}\nType /help for available commands.`
                    : `Command "/${command}" failed: ${msg}`
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
        // v1.18.1 5b.1: min-words validation now lives server-side in
        // ppxai.commands.agent.validate_agent_task — applied by both
        // the /chat route (gate) and the factory's handle_agent. The
        // duplicate client-side check that lived here is gone; if
        // /agent <task> reaches us with an under-threshold task the
        // server rejects it with a friendly NotificationResult before
        // the iteration loop ever starts.
        const agentConfig = await this._backend.getAgentConfig();
        const maxIterations = agentConfig.max_iterations;

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

    // v1.18.1 5b.2: handleSpecCommand removed.
    // Rich /spec templates now live in ppxai/commands/system.py
    // (handle_spec) and dispatch through the factory envelope, so all
    // four clients see identical content. The previous client-side
    // SPEC_TEMPLATES + SPEC_GUIDELINES blob (~50 lines per template,
    // ~200 LoC total) was the divergence point — TUI shipped a 5-line
    // stub while VSCode had the full templates inline.

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
     * Handle file preview request from webview attachment badge click (v1.17.4).
     *
     * - PPTX: fetches rendered slide PNGs from /files/preview and opens
     *   each as an image tab in VSCode.
     * - DOCX/DOC: fetches the LibreOffice-converted PDF from /files/preview
     *   and opens it in VSCode's PDF viewer.
     * - Everything else (PDF, images, text): fetches raw bytes from
     *   /files/serve and opens with VSCode's native viewer.
     */
    private async handlePreviewFile(fileId: string | undefined, name: string, data?: string) {
        if (!fileId && !data) { return; }

        const os = require('os');
        const path = require('path');
        const fs = require('fs');
        const tmpDir = path.join(os.tmpdir(), 'ppxai-preview');
        fs.mkdirSync(tmpDir, { recursive: true });
        const base = this._backend.getBaseUrl();
        const ext = path.extname(name).toLowerCase();

        try {
            // If we have inline base64 data (file just attached, no server file_id yet),
            // write it directly to a temp file and open with VSCode native viewer.
            if (!fileId && data) {
                const buffer = Buffer.from(data, 'base64');
                const tmpFile = path.join(tmpDir, name);
                fs.writeFileSync(tmpFile, buffer);
                await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(tmpFile));
                return;
            }
            // From here on we need a server-side file_id
            if (!fileId) { return; }

            // PPTX → render slides as PNG via LibreOffice, open each
            if (ext === '.pptx' || ext === '.ppt') {
                const metaResp = await fetch(`${base}/files/preview/${fileId}?total=true`);
                if (!metaResp.ok) {
                    // LibreOffice not available — fall back to raw file
                    return this._openRawFile(base, fileId, name, tmpDir, fs, path);
                }
                const meta = await metaResp.json() as { total: number; name: string };
                const total = meta.total || 1;

                // Open first slide, then the rest in background tabs
                for (let i = 1; i <= total; i++) {
                    const slideResp = await fetch(`${base}/files/preview/${fileId}?slide=${i}`);
                    if (!slideResp.ok) { continue; }
                    const buf = Buffer.from(await slideResp.arrayBuffer());
                    const slideName = `${path.basename(name, ext)}_slide${i}.png`;
                    const tmpFile = path.join(tmpDir, slideName);
                    fs.writeFileSync(tmpFile, buf);
                    const uri = vscode.Uri.file(tmpFile);
                    // First slide in active column, rest as preview tabs
                    await vscode.commands.executeCommand('vscode.open', uri,
                        { preview: i > 1 });
                }
                return;
            }

            // DOCX/DOC → convert to PDF via LibreOffice, open PDF
            if (ext === '.docx' || ext === '.doc') {
                const pdfResp = await fetch(`${base}/files/preview/${fileId}?slide=1`);
                if (pdfResp.ok) {
                    const buf = Buffer.from(await pdfResp.arrayBuffer());
                    const pdfName = `${path.basename(name, ext)}.pdf`;
                    const tmpFile = path.join(tmpDir, pdfName);
                    fs.writeFileSync(tmpFile, buf);
                    await vscode.commands.executeCommand('vscode.open',
                        vscode.Uri.file(tmpFile));
                    return;
                }
                // Fall through to raw file if conversion unavailable
            }

            // Default: serve raw bytes (PDF, images, text, etc.)
            await this._openRawFile(base, fileId, name, tmpDir, fs, path);
        } catch (error) {
            vscode.window.showWarningMessage(`Preview failed for ${name}: ${error}`);
        }
    }

    private async _openRawFile(
        base: string, fileId: string, name: string,
        tmpDir: string, fs: any, path: any
    ) {
        const resp = await fetch(`${base}/files/serve/${fileId}`);
        if (!resp.ok) {
            vscode.window.showWarningMessage(`Cannot preview ${name}: server returned ${resp.status}`);
            return;
        }
        const buffer = Buffer.from(await resp.arrayBuffer());
        const tmpFile = path.join(tmpDir, name);
        fs.writeFileSync(tmpFile, buffer);
        await vscode.commands.executeCommand('vscode.open', vscode.Uri.file(tmpFile));
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

    // v1.18.1 5b.2: handleUsageCommand and renderCommandResult removed.
    // /usage now flows through dispatchFactoryCommand; CommandRenderer
    // (vscode-extension/src/commandRenderer.ts) covers the full result
    // taxonomy that this method's switch only partially handled.

    // v1.18.1 5b.2: handleShowCommand removed.
    // Factory's handle_show (ppxai/commands/display.py) does the file
    // resolution server-side, emits OPEN_VIEWER for direct hits and
    // PROMPT_QUICK_PICK for multi-match. The SideEffectsHandler
    // translates OPEN_VIEWER → vscode.commands.executeCommand('vscode.open')
    // — preserves the "beside, preview mode" UX while letting installed
    // PDF/image extensions handle non-text files.

    // v1.18.1 5b.2: handleEditCommand removed.
    // Factory's handle_edit (ppxai/commands/display.py) parses the
    // file:line:col syntax and emits OPEN_EDITOR with line/column
    // payload. SideEffectsHandler.OPEN_EDITOR opens primary column,
    // preview=false, jumps to position — same UX as before, no
    // duplicate file-search code.
    // v1.18.1 5b.2: handleCdCommand and handlePwdCommand removed.
    // Factory's handle_cd (ppxai/commands/utility.py) emits
    // REFRESH_FILE_TREE side-effect after a successful cd; the working
    // dir mirror is pushed via state_sync (Phase A re-anchor).
    // handle_pwd returns the cwd as a NotificationResult.

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
            <span class="agent-beat-badge" id="agentBeatBadge" style="display: none;" title="Agent heartbeat (iteration · tool · elapsed)"><span id="agentBeatText">⚙ idle</span></span>
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
