import * as vscode from 'vscode';
import { HttpClient, StreamEvent } from './httpClient';

// Slash command definitions
const SLASH_COMMANDS: Record<string, { description: string; usage: string }> = {
    '/help': { description: 'Show available commands', usage: '/help' },
    '/clear': { description: 'Clear conversation history', usage: '/clear' },
    '/save': { description: 'Save current session', usage: '/save' },
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
    '/explain': { description: 'Explain code or concept', usage: '/explain <code or question>' },
    '/test': { description: 'Generate tests for code', usage: '/test <code or @file>' },
    '/docs': { description: 'Generate documentation', usage: '/docs <code or @file>' },
    '/debug': { description: 'Debug an error message', usage: '/debug <error message>' },
    '/implement': { description: 'Implement from description', usage: '/implement <description>' },
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
                case 'ready':
                    await this.initializeBackend();
                    break;
                case 'toggleTools':
                    await this.handleToggleTools(message.enable);
                    break;
                case 'searchFiles':
                    await this.handleSearchFilesForAutocomplete(message.query);
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

            await this.updateStatus();
            await this.refreshHistory();
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

        // Start streaming response
        this._view.webview.postMessage({ type: 'startResponse' });

        try {
            await this._backend.chat(augmentedMessage, (event) => {
                this.handleStreamEvent(event);
            });
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Error: ${error}`
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
            case 'error':
                this._view.webview.postMessage({
                    type: 'error',
                    content: event.content
                });
                break;
            case 'done':
                // Handled by endResponse
                break;
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
        this._view.webview.postMessage({ type: 'startStreaming' });

        try {
            await this._backend.codingTask(
                taskType,
                augmentedContent,
                language,
                filename,
                (event: StreamEvent) => this.handleStreamEvent(event)
            );
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Coding task error: ${error}`
            });
        }

        this._view.webview.postMessage({ type: 'endStreaming' });
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
            await this.updateStatus();
        } catch (error) {
            this._view.webview.postMessage({
                type: 'error',
                content: `Failed to toggle tools: ${error}`
            });
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
            this._view?.webview.postMessage({
                type: 'error',
                content: `Error: ${error}`
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
            text-decoration: none;
        }

        .message a:hover {
            text-decoration: underline;
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
    </style>
</head>
<body>
    <div class="header">
        <div class="status">
            <span><span id="provider">Loading...</span> / <span id="model">...</span></span>
            <button class="tools-badge disabled" id="toolsBadge" title="Click to toggle tools">Tools: off</button>
        </div>
        <div class="header-buttons">
            <button class="header-btn" id="saveBtn" title="Save session">Save</button>
            <button class="header-btn" id="clearBtn" title="Clear history">Clear</button>
        </div>
    </div>

    <div class="messages" id="messages">
        <div class="typing-indicator" id="typingIndicator">Thinking...</div>
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
        const saveBtn = document.getElementById('saveBtn');
        const clearBtn = document.getElementById('clearBtn');

        let currentResponseEl = null;
        let currentResponseContent = '';
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
            { name: '/save', description: 'Save current session' },
            { name: '/load', description: 'Load a saved session' },
            { name: '/sessions', description: 'List saved sessions' },
            { name: '/model', description: 'Switch model' },
            { name: '/provider', description: 'Switch provider' },
            { name: '/tools', description: 'Manage AI tools (enable|disable|list)' },
            { name: '/show', description: 'Display file contents' },
            { name: '/usage', description: 'Show token usage stats' },
            { name: '/status', description: 'Show current status' },
        ];

        // Configure marked for GFM
        // Check if marked library loaded
        let parseMarkdown;
        if (typeof marked !== 'undefined' && typeof marked.parse === 'function') {
            parseMarkdown = marked.parse.bind(marked);
            marked.setOptions({
                breaks: true,
                gfm: true
            });
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
                // Inline code (before escaping HTML)
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
            currentResponseEl.innerHTML = simpleFormat(currentResponseContent);
            scrollToBottom();
        }

        // Simple formatting for streaming (fast)
        function simpleFormat(text) {
            if (!text) return '';
            // Escape HTML
            text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            // Basic code blocks
            text = text.replace(/\`\`\`(\\w*)\\n([\\s\\S]*?)\`\`\`/g, '<pre><code>$2</code></pre>');
            // Inline code
            text = text.replace(/\`([^\`]+)\`/g, '<code>$1</code>');
            // Bold
            text = text.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
            // Headers (basic support during streaming)
            text = text.replace(/^### (.+)$/gm, '<h3>$1</h3>');
            text = text.replace(/^## (.+)$/gm, '<h2>$1</h2>');
            text = text.replace(/^# (.+)$/gm, '<h1>$1</h1>');
            // Line breaks
            text = text.replace(/\\n/g, '<br>');
            return text;
        }

        // Full markdown render (at end of streaming)
        function fullRender(showTime = false) {
            if (!currentResponseEl || !currentResponseContent) return;
            try {
                currentResponseEl.innerHTML = parseMarkdown(currentResponseContent);
                // Apply syntax highlighting to code blocks (skip large ones for performance)
                currentResponseEl.querySelectorAll('pre code').forEach((block) => {
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
                    currentResponseEl.appendChild(timeEl);
                }
            } catch (e) {
                console.error('Full render error:', e);
                currentResponseEl.innerHTML = simpleFormat(currentResponseContent);
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

        saveBtn.addEventListener('click', () => {
            vscode.postMessage({ type: 'save' });
        });

        clearBtn.addEventListener('click', () => {
            vscode.postMessage({ type: 'clear' });
        });

        // Tools badge click handler - toggle tools on/off
        toolsBadge.addEventListener('click', () => {
            const isEnabled = toolsBadge.classList.contains('enabled');
            vscode.postMessage({ type: 'toggleTools', enable: !isEnabled });
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
                    addMessage('tool-call', '🔧 **Calling tool:** \`' + message.tool + '\`\\n\`\`\`json\\n' + JSON.stringify(message.arguments, null, 2) + '\\n\`\`\`', true);
                    break;

                case 'toolResult':
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
                    typingIndicator.textContent = 'Thinking...';
                    typingIndicator.classList.add('visible');
                    currentResponseEl = null;
                    currentResponseContent = '';
                    responseStartTime = Date.now();
                    break;

                case 'thinking':
                    // Backend received request
                    typingIndicator.textContent = 'Processing...';
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

                case 'endResponse':
                    typingIndicator.classList.remove('visible');
                    sendBtn.disabled = false;
                    // Full markdown render with syntax highlighting at the end
                    fullRender(true);
                    currentResponseEl = null;
                    currentResponseContent = '';
                    responseStartTime = 0;
                    break;

                case 'error':
                    typingIndicator.classList.remove('visible');
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

                case 'history':
                    // Clear existing messages except typing indicator
                    messagesContainer.innerHTML = '';
                    typingIndicator = document.createElement('div');
                    typingIndicator.className = 'typing-indicator';
                    typingIndicator.id = 'typingIndicator';
                    typingIndicator.textContent = 'Thinking...';
                    messagesContainer.appendChild(typingIndicator);

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
                    typingIndicator.textContent = 'Thinking...';
                    messagesContainer.appendChild(typingIndicator);
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

        function addMessage(role, content, useMarkdown = true) {
            const el = document.createElement('div');
            el.className = 'message ' + role;
            if (useMarkdown && content) {
                try {
                    el.innerHTML = parseMarkdown(content);
                    // Apply syntax highlighting
                    el.querySelectorAll('pre code').forEach((block) => {
                        hljs.highlightElement(block);
                    });
                } catch (e) {
                    console.error('Markdown parse error:', e);
                    el.textContent = content;
                }
            } else {
                el.textContent = content;
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
