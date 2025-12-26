/**
 * Chat Panel Webview Provider
 *
 * Interrupt handling (Esc key) inspired by Claude Code by Anthropic
 * https://claude.ai/code
 */

import * as vscode from 'vscode';
import { HttpClient, StreamEvent } from './httpClient';

// Slash command definitions
const SLASH_COMMANDS: Record<string, { description: string; usage: string }> = {
    '/help': { description: 'Show available commands', usage: '/help' },
    '/clear': { description: 'Clear conversation history', usage: '/clear' },
    '/save': { description: 'Save session to JSON', usage: '/save' },
    '/export': { description: 'Export last answer to markdown', usage: '/export [filename]' },
    '/load': { description: 'Load a saved session', usage: '/load [session_name]' },
    '/sessions': { description: 'List saved sessions', usage: '/sessions' },
    '/model': { description: 'Switch model or list models', usage: '/model [model_id|list]' },
    '/provider': { description: 'Switch provider or list providers', usage: '/provider [provider_id|list]' },
    '/tools': { description: 'Manage AI tools', usage: '/tools [enable|disable|status|list]' },
    '/show': { description: 'Display file contents locally (no LLM call)', usage: '/show <filepath>' },
    '/cat': { description: 'Alias for /show', usage: '/cat <filepath>' },
    '/usage': { description: 'Show token usage stats', usage: '/usage' },
    '/status': { description: 'Show current status', usage: '/status' },
    // Coding task commands
    '/generate': { description: 'Generate code from description', usage: '/generate <description>' },
    '/explain': { description: 'Explain code or concept', usage: '/explain <code or question>' },
    '/test': { description: 'Generate tests for code', usage: '/test <code or @file>' },
    '/docs': { description: 'Generate documentation', usage: '/docs <code or @file>' },
    '/debug': { description: 'Debug an error message', usage: '/debug <error message>' },
    '/implement': { description: 'Implement from description', usage: '/implement <description>' },
    '/spec': { description: 'Show specification templates', usage: '/spec [api|cli|lib|algo|ui]' },
    '/convert': { description: 'Convert code between languages', usage: '/convert <source-lang> <target-lang> <code or @file>' },
};

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
                case 'searchFiles':
                    await this.handleSearchFilesForAutocomplete(message.query);
                    break;
                case 'openLink':
                    if (message.url) {
                        vscode.env.openExternal(vscode.Uri.parse(message.url));
                    }
                    break;
                case 'interrupt':
                    await this._backend.interrupt();
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

            const files = matches.map(m => {
                const name = m.path.split('/').pop() || '';
                const relPath = workspaceFolders
                    ? pathModule.relative(workspaceFolders[0].uri.fsPath, m.fsPath)
                    : m.path;
                return { name, path: relPath };
            });

            this._view.webview.postMessage({
                type: 'fileSuggestions',
                files
            });
        } catch (error) {
            // Silently fail - autocomplete is optional
        }
    }

    private async initializeBackend() {
        try {
            // Connect to ppxai-server if not running
            if (!this._backend.isRunning()) {
                this._view?.webview.postMessage({
                    type: 'systemMessage',
                    content: 'Connecting to ppxai-server...'
                });
                const connected = await this._backend.start();
                if (!connected) {
                    this._view?.webview.postMessage({
                        type: 'error',
                        content: 'Could not connect to ppxai-server. Please start it with: uv run ppxai-server'
                    });
                    return;
                }
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
                return;
            }
            this._view.webview.postMessage({
                type: 'error',
                content: String(error)
            });
        }

        this._view.webview.postMessage({ type: 'endResponse' });
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
                        arguments: data.arguments
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
                        result: data.result
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
                        const sessionList = sessions.map(s =>
                            `• ${s.name} (${s.provider}/${s.model}, ${s.message_count} messages)`
                        ).join('\n');
                        this._view.webview.postMessage({
                            type: 'systemMessage',
                            content: `**Saved Sessions:**\n${sessionList}`
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

                case '/usage':
                    const usage = await this._backend.getUsage();
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: `**Usage Statistics:**
• Total tokens: ${usage.total_tokens.toLocaleString()}
• Prompt tokens: ${usage.prompt_tokens.toLocaleString()}
• Completion tokens: ${usage.completion_tokens.toLocaleString()}
• Estimated cost: $${usage.estimated_cost.toFixed(4)}`
                    });
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
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: 'Usage: /tools config <setting> <value>\nExample: /tools config max_iterations 20'
                    });
                }
                break;

            case 'help':
                if (args[1] === 'editing') {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: this.getFileEditingHelp()
                    });
                } else {
                    this._view.webview.postMessage({
                        type: 'systemMessage',
                        content: 'Available help topics: **editing**\nUsage: `/tools help editing`'
                    });
                }
                break;

            case 'status':
            default:
                const status = await this._backend.getToolsStatus();
                const available = status.enabled ? await this._backend.listTools() : [];
                this._view.webview.postMessage({
                    type: 'systemMessage',
                    content: `**Tools Status:**
• Enabled: ${status.enabled ? 'yes' : 'no'}
• Available: ${available.length} tools
• Max iterations: ${status.max_iterations}

Use \`/tools enable\` to enable tools, \`/tools list\` to see available tools.`
                });
                break;
        }
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
                return;
            }
            this._view.webview.postMessage({
                type: 'error',
                content: String(error)
            });
        }

        this._view.webview.postMessage({ type: 'endResponse' });
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
                return;
            }
            this._view.webview.postMessage({
                type: 'error',
                content: String(error)
            });
        }

        this._view.webview.postMessage({ type: 'endResponse' });
    }

    private async showHelp() {
        if (!this._view) { return; }

        const helpText = Object.entries(SLASH_COMMANDS)
            .map(([cmd, info]) => `**${cmd}** - ${info.description}\n  Usage: \`${info.usage}\``)
            .join('\n\n');

        this._view.webview.postMessage({
            type: 'systemMessage',
            content: `**Available Commands:**\n\n${helpText}`
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

            const content = fs.readFileSync(fullPath, 'utf-8');
            const lines = content.split('\n');
            const sizeKB = (stats.size / 1024).toFixed(1);
            const filename = pathModule.basename(fullPath);
            const ext = pathModule.extname(fullPath).toLowerCase();

            // Map extension to language for syntax highlighting
            const extToLang: Record<string, string> = {
                '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
                '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml',
                '.md': 'markdown', '.html': 'html', '.css': 'css',
                '.sh': 'bash', '.bash': 'bash', '.zsh': 'bash',
                '.rs': 'rust', '.go': 'go', '.java': 'java',
                '.c': 'c', '.cpp': 'cpp', '.h': 'c', '.hpp': 'cpp',
                '.rb': 'ruby', '.php': 'php', '.sql': 'sql',
                '.xml': 'xml', '.toml': 'toml', '.ini': 'ini',
            };
            const lang = extToLang[ext] || '';

            // Format output - render markdown files directly, wrap others in code block
            const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
            let markdown: string;
            if (ext === '.md' || ext === '.markdown') {
                // Render markdown files directly (not in code block)
                markdown = `**${filename}** (${sizeKB} KB, ${lines.length} lines)\n\n---\n\n${content}\n\n---\n\n*${elapsed}s*`;
            } else {
                // Wrap code files in code block
                markdown = `**${filename}** (${sizeKB} KB, ${lines.length} lines)\n\n\`\`\`${lang}\n${content}\n\`\`\`\n\n*${elapsed}s*`;
            }

            this._view.webview.postMessage({
                type: 'systemMessage',
                content: markdown
            });
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Error reading file: ${error}`
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
            content: `${taskMessage}${contextInfo}:\n\`\`\`${language || ''}\n${content.slice(0, 500)}${content.length > 500 ? '...' : ''}\n\`\`\``
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
                return;
            }
            this._view?.webview.postMessage({
                type: 'error',
                content: String(error)
            });
        }

        this._view.webview.postMessage({ type: 'endResponse' });
    }

    public async updateStatus() {
        if (!this._view) { return; }

        try {
            const status = await this._backend.getStatus();
            const toolsStatus = await this._backend.getToolsStatus();

            this._view.webview.postMessage({
                type: 'status',
                provider: status.provider,
                model: status.model,
                toolsEnabled: toolsStatus.enabled,
                toolCount: toolsStatus.tool_count
            });
        } catch (error) {
            // Backend may not be ready yet
            this._view.webview.postMessage({
                type: 'status',
                provider: 'Not connected',
                model: '...',
                toolsEnabled: false,
                toolCount: 0
            });
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
        }

        .message th, .message td {
            border: 1px solid var(--vscode-panel-border);
            padding: 6px 12px;
            text-align: left;
        }

        .message th {
            background: var(--vscode-editor-inactiveSelectionBackground);
            font-weight: 600;
        }

        .message tr:nth-child(even) {
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
        }

        .typing-indicator.visible {
            display: block;
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
            <span><span id="provider">Loading...</span> / <span id="model">...</span></span>
            <button class="tools-badge disabled" id="toolsBadge" title="Click to toggle tools">Tools: off</button>
            <button class="streaming-badge" id="streamingBadge" style="display: none;" title="Press Esc to stop">⏹ Streaming...</button>
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
        const toolsBadge = document.getElementById('toolsBadge');
        const streamingBadge = document.getElementById('streamingBadge');
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
                insertText = '@' + item.name;
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
                // Request file suggestions from extension
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

        // Send message
        function sendMessage() {
            const content = messageInput.value.trim();
            if (!content) return;

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
            sendBtn.disabled = true;
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
        toolsBadge.addEventListener('click', () => {
            const isEnabled = toolsBadge.classList.contains('enabled');
            vscode.postMessage({ type: 'toggleTools', enable: !isEnabled });
        });

        // Streaming badge click handler - interrupt streaming
        streamingBadge.addEventListener('click', () => {
            vscode.postMessage({ type: 'interrupt' });
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
                    sendBtn.disabled = false;
                    break;

                case 'toolCall':
                    typingIndicator.textContent = 'Using tool: ' + message.tool + '...';
                    typingIndicator.classList.add('visible');
                    addMessage('tool-call', '🔧 **Calling tool:** \`' + message.tool + '\`\\n\`\`\`json\\n' + JSON.stringify(message.arguments, null, 2) + '\\n\`\`\`', true);

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
                    const resultPreview = typeof message.result === 'string'
                        ? (message.result.length > 500 ? message.result.slice(0, 500) + '...' : message.result)
                        : JSON.stringify(message.result, null, 2);
                    addMessage('tool-result', '📋 **Result from** \`' + message.tool + '\`:\\n\`\`\`\\n' + resultPreview + '\\n\`\`\`', true);
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

                case 'chunk':
                    if (!currentResponseEl) {
                        currentResponseEl = addMessage('assistant', '', false);
                        typingIndicator.classList.remove('visible');
                    }
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

                case 'endResponse':
                    typingIndicator.classList.remove('visible');
                    streamingBadge.style.display = 'none';  // Hide streaming indicator
                    sendBtn.disabled = false;
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
                    sendBtn.disabled = false;
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
                    break;

                case 'debugLogStatus':
                    if (message.enabled) {
                        debugLogIndicator.classList.add('active');
                    } else {
                        debugLogIndicator.classList.remove('active');
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
                    if (autocompleteMode === 'file' || message.files.length > 0) {
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
