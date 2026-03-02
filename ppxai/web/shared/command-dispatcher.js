/**
 * CommandDispatcher — slash command routing for the ppxai web app.
 *
 * Extracted from app.js v1.16.2.
 * Contains all slash command handlers. The app instance is passed
 * in the constructor so handlers can access app state and methods.
 *
 * Usage:
 *   this.commandDispatcher = new CommandDispatcher(app);
 *   await this.commandDispatcher.dispatch(input);
 */

class CommandDispatcher {
    /** @param {PpxaiApp} app */
    constructor(app) {
        this.app = app;
    }

    async dispatch(input) {
        // Prevent recursive/repeated calls
        if (this.app.state.isHandlingCommand) {
            console.warn('handleSlashCommand called while already handling:', input);
            return;
        }
        this.app.state.isHandlingCommand = true;

        try {
            const parts = input.trim().split(/\s+/);
            const cmd = parts[0].toLowerCase();
            const args = parts.slice(1).join(' ');

            this.app.showSystemMessage(`> ${input}`);

        switch (cmd) {
            case '/help':
                this.showHelp();
                break;

            case '/clear':
                await this.app.clearConversation();
                break;

            case '/save':
                await this.app.saveSession(args);
                break;

            case '/export':
                await this.app.exportAnswer(args);
                break;

            case '/load':
                await this.app.loadSession(args);
                break;

            case '/sessions':
                await this.app.listSessions();
                break;

            case '/model':
                await this.handleModelCommand(args);
                break;

            case '/provider':
                await this.handleProviderCommand(args);
                break;

            case '/tools':
                await this.handleToolsCommand(args);
                break;

            case '/agent':
                if (args === 'on') {
                    if (!this.app.state.agentMode) await this.app.toggleAgent();
                } else if (args === 'off') {
                    if (this.app.state.agentMode) await this.app.toggleAgent();
                } else if (args) {
                    // Run agent task
                    this.app.addMessage('user', input);
                    await this.app.streamChat(`/agent ${args}`);
                } else {
                    this.app.showSystemMessage(`Agent mode: ${this.app.state.agentMode ? 'on' : 'off'}`);
                }
                break;

            case '/checkpoint':
                await this.handleCheckpointCommand(args);
                break;

            case '/usage':
                await this.handleUsageCommand(args);
                break;

            case '/status':
                await this.showStatus();
                break;

            case '/context':
                await this.handleContextCommand(args);
                break;

            case '/theme':
                this.handleThemeCommand(args);
                break;

            case '/show':
            case '/cat':
                await this.handleShowCommand(args);
                break;

            case '/edit':
                await this.app.handleEditCommand(args);
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

            case '/config':
                await this.handleConfigCommand(args);
                break;

            case '/generate':
            case '/explain':
            case '/test':
            case '/docs':
            case '/debug':
            case '/implement':
            case '/convert':
            case '/spec':
                // Send as regular message - server handles these
                this.app.addMessage('user', input);
                await this.app.streamChat(input);
                break;

            default:
                this.app.showError(`Unknown command: ${cmd}. Type /help for available commands.`);
        }
        } finally {
            this.app.state.isHandlingCommand = false;
        }
    }

    showHelp() {
        // Use shared help generator if available
        let helpText;
        if (typeof SharedCommands !== 'undefined' && SharedCommands.generateHelpText) {
            helpText = SharedCommands.generateHelpText();
        } else {
            helpText = '**Available Commands:**\n\n';
            Object.entries(this.app.slashCommands).forEach(([cmd, info]) => {
                helpText += `\`${info.usage}\` - ${info.description}\n`;
            });
        }

        helpText += '\n**Keyboard Shortcuts:**\n';
        helpText += '- `Esc` - Stop streaming\n';
        helpText += '- `↑/↓` - Command history\n';
        helpText += '- `@file` - Reference a file\n';
        helpText += '- `@git` - Include git diff\n';
        helpText += '- `@tree` - Include project structure\n';

        this.app.addMessage('system', helpText);
    }

    async handleModelCommand(args) {
        if (!args || args === 'list') {
            try {
                const data = await this.app.apiClient.getModels();
                let text = '**Available Models:**\n\n';
                data.models.forEach(m => {
                    const current = m.id === this.app.state.currentModel ? ' *(current)*' : '';
                    text += `- \`${m.id}\`${current} - ${m.name}\n`;
                });
                this.app.addMessage('system', text);
            } catch (error) {
                this.app.showError(`Failed to list models: ${error.message}`);
            }
        } else {
            this.app.elements.modelSelect.value = args;
            await this.app.handleModelChange();
        }
    }

    async handleProviderCommand(args) {
        if (!args || args === 'list') {
            try {
                const data = await this.app.apiClient.getProviders();
                let text = '**Available Providers:**\n\n';
                data.providers.forEach(p => {
                    const current = p.id === this.app.state.currentProvider ? ' *(current)*' : '';
                    const status = p.has_api_key ? '✓' : '✗';
                    text += `- \`${p.id}\`${current} [${status}] - ${p.name}\n`;
                });
                this.app.addMessage('system', text);
            } catch (error) {
                this.app.showError(`Failed to list providers: ${error.message}`);
            }
        } else {
            this.app.elements.providerSelect.value = args;
            await this.app.handleProviderChange();
        }
    }

    async handleToolsCommand(args) {
        const subCmd = args.split(/\s+/)[0];

        switch (subCmd) {
            case 'enable':
            case 'on':
                if (!this.app.state.toolsEnabled) await this.app.toggleTools();
                break;

            case 'disable':
            case 'off':
                if (this.app.state.toolsEnabled) await this.app.toggleTools();
                break;

            case 'status':
            case '':
                try {
                    const data = await this.app.apiClient.getTools();
                    let text = '**Tools Status:**\n\n';
                    text += `- Enabled: ${data.enabled ? 'yes' : 'no'}\n`;
                    text += `- Tool count: ${data.tools.length}\n`;
                    text += `- Verbose: ${data.verbose ? 'on' : 'off'}\n`;
                    this.app.addMessage('system', text);
                } catch (error) {
                    this.app.showError(`Failed to get tools status: ${error.message}`);
                }
                break;

            case 'list':
                try {
                    const data = await this.app.apiClient.getTools();
                    let text = '**Available Tools:**\n\n';
                    data.tools.forEach(t => {
                        text += `- \`${t.name}\` - ${t.description}\n`;
                    });
                    this.app.addMessage('system', text);
                } catch (error) {
                    this.app.showError(`Failed to list tools: ${error.message}`);
                }
                break;

            case 'set':
                const setParts = args.split(/\s+/).slice(1);
                if (setParts[0] === 'verbose') {
                    const value = setParts[1] === 'on' || setParts[1] === 'true';
                    try {
                        await this.app.apiClient.setToolConfig('verbose', value ? 'on' : 'off');
                        this.app.state.verbose = value;
                        this.app.showSystemMessage(`Verbose mode ${value ? 'enabled' : 'disabled'}`);
                    } catch (error) {
                        this.app.showError(`Failed to set verbose: ${error.message}`);
                    }
                } else {
                    this.app.showError('Usage: /tools set verbose on|off');
                }
                break;

            case 'config':
                try {
                    const data = await this.app.apiClient.getTools();
                    let text = '**Tool Configuration:**\n\n';
                    text += `- Enabled: ${data.enabled ? 'yes' : 'no'}\n`;
                    text += `- Max iterations: ${data.max_iterations || 15}\n`;
                    text += `- Verbose: ${data.verbose ? 'on' : 'off'}\n`;
                    text += `- Consent mode: ${data.consent_mode || 'default'}\n`;
                    text += `- Tool count: ${data.tools.length}\n`;
                    this.app.addMessage('system', text);
                } catch (error) {
                    this.app.showError(`Failed to get tool config: ${error.message}`);
                }
                break;

            case 'agent':
                const agentArg = args.split(/\s+/)[1];
                if (agentArg === 'on' || agentArg === 'enable') {
                    if (!this.app.state.agentMode) await this.app.toggleAgent();
                    this.app.showSystemMessage('Agent mode enabled. Tools auto-enabled.');
                } else if (agentArg === 'off' || agentArg === 'disable') {
                    if (this.app.state.agentMode) await this.app.toggleAgent();
                    this.app.showSystemMessage('Agent mode disabled.');
                } else {
                    const status = this.app.state.agentMode ? 'ON' : 'OFF';
                    this.app.addMessage('system', `**Agent Mode:** ${status}\n\nUsage: \`/tools agent on|off\`\nOr use \`/agent <task>\` to run an autonomous task.`);
                }
                break;

            case 'help':
                const toolName = args.split(/\s+/)[1];
                if (toolName) {
                    try {
                        const data = await this.app.apiClient.getToolHelp(toolName);
                        let text = `**Tool: ${data.name}**\n\n`;
                        text += `${data.description}\n\n`;
                        if (data.parameters && data.parameters.properties) {
                            text += '**Parameters:**\n';
                            Object.entries(data.parameters.properties).forEach(([name, prop]) => {
                                const required = data.parameters.required?.includes(name) ? ' *(required)*' : '';
                                text += `- \`${name}\`${required}: ${prop.description || prop.type || 'no description'}\n`;
                            });
                        }
                        this.app.addMessage('system', text);
                    } catch (error) {
                        this.app.showError(`Failed to get tool help: ${error.message}`);
                    }
                } else {
                    this.app.addMessage('system', '**Tool Help**\n\nUsage: `/tools help <tool-name>` - Show help for a specific tool\n\nUse `/tools list` to see available tools.');
                }
                break;

            default:
                this.app.showError(`Unknown /tools subcommand: ${subCmd}. Available: enable, disable, status, list, config, set, agent, help`);
        }
    }

    async handleCheckpointCommand(args) {
        const subCmd = args.split(/\s+/)[0];

        switch (subCmd) {
            case 'status':
            case '':
                try {
                    const data = await this.app.apiClient.getAgentStatus();
                    let text = '**Checkpoint Status:**\n\n';
                    if (data.checkpoint) {
                        text += `- Backend: ${data.checkpoint.backend}\n`;
                        text += `- Enabled: ${data.checkpoint.enabled ? 'yes' : 'no'}\n`;
                        text += `- Last checkpoint: ${data.checkpoint.last_checkpoint || 'none'}\n`;
                        text += `- Valid: ${data.checkpoint.is_valid ? 'yes' : 'no'}\n`;
                        if (!data.checkpoint.is_valid) {
                            text += `- Reason: ${data.checkpoint.validity_reason}\n`;
                        }
                    } else {
                        text += 'Checkpoint system not available.\n';
                    }
                    this.app.addMessage('system', text);
                } catch (error) {
                    this.app.showError(`Failed to get checkpoint status: ${error.message}`);
                }
                break;

            case 'list':
                try {
                    const data = await this.app.apiClient.listCheckpoints();
                    let text = '**Recent Checkpoints:**\n\n';
                    if (data.checkpoints.length === 0) {
                        text += 'No checkpoints found.\n';
                    } else {
                        data.checkpoints.forEach(cp => {
                            text += `- \`${cp.id}\` - ${cp.description} (${cp.timestamp})\n`;
                        });
                    }
                    this.app.addMessage('system', text);
                } catch (error) {
                    this.app.showError(`Failed to list checkpoints: ${error.message}`);
                }
                break;

            case 'undo':
                await this.app.undoCheckpoint();
                break;

            case 'backend':
                const backendArg = args.split(/\s+/)[1];
                if (backendArg) {
                    const validBackends = ['git', 'file', 'auto', 'none'];
                    if (!validBackends.includes(backendArg)) {
                        this.app.showError(`Invalid backend: ${backendArg}. Valid options: ${validBackends.join(', ')}`);
                        return;
                    }
                    try {
                        const data = await this.app.apiClient.setCheckpointBackend(backendArg);
                        this.app.showSystemMessage(`Checkpoint backend set to: ${data.backend}`);
                    } catch (error) {
                        this.app.showError(`Failed to set backend: ${error.message}`);
                    }
                } else {
                    this.app.addMessage('system', '**Checkpoint Backend**\n\nUsage: `/checkpoint backend <git|file|auto|none>`\n\n- `git`: Use git commits (recommended for git repos)\n- `file`: Use file snapshots (~/.ppxai/checkpoints/)\n- `auto`: Auto-detect best backend\n- `none`: Disable checkpoints');
                }
                break;

            case 'clear':
                try {
                    const data = await this.app.apiClient.clearCheckpoints(0);
                    this.app.showSystemMessage(data.message || `Cleared ${data.removed} checkpoint(s)`);
                } catch (error) {
                    this.app.showError(`Failed to clear checkpoints: ${error.message}`);
                }
                break;

            case 'info':
                const checkpointId = args.split(/\s+/)[1];
                if (checkpointId) {
                    try {
                        const data = await this.app.apiClient.getCheckpointInfo(checkpointId);
                        let text = '**Checkpoint Details:**\n\n';
                        text += `- ID: \`${data.id}\`\n`;
                        text += `- Description: ${data.description}\n`;
                        text += `- Timestamp: ${data.timestamp}\n`;
                        text += `- Status: ${data.is_current ? (data.is_valid ? 'Current (can undo)' : 'Stale (cannot undo)') : 'Historical'}\n`;
                        this.app.addMessage('system', text);
                    } catch (error) {
                        this.app.showError(`Failed to get checkpoint info: ${error.message}`);
                    }
                } else {
                    this.app.addMessage('system', '**Checkpoint Info**\n\nUsage: `/checkpoint info <checkpoint_id>`\n\nUse `/checkpoint list` to see available checkpoints.');
                }
                break;

            default:
                this.app.showError(`Unknown /checkpoint subcommand: ${subCmd}. Available: status, list, undo, backend, clear, info`);
        }
    }

    async handleUsageCommand(args) {
        // v1.16.1: Delegate to shared command handler via POST /command/usage
        try {
            const result = await this.app.apiClient.executeCommand('usage', args.trim());
            this.renderCommandResult(result);
        } catch (error) {
            this.app.showError(`Failed to get usage: ${error.message}`);
        }
    }

    /**
     * Render a server-side CommandResult as markdown in the chat.
     *
     * Generic dispatcher for all command result types returned by
     * POST /command/{name}. Works for any command, not just /usage.
     *
     * v1.16.1: Added for CommandFactory server-side execution.
     */
    renderCommandResult(result) {
        switch (result.type) {
            case 'TableResult':
            case 'DirectoryListingResult':
                this.app.addMessage('system', window.SharedFormatters.formatTableResult(result));
                break;
            case 'ConfirmationResult':
            case 'NotificationResult':
                this.app.showSystemMessage(result.message);
                break;
            case 'ErrorResult':
                this.app.showError(result.message +
                    (result.suggestions && result.suggestions.length
                        ? '\n' + result.suggestions.join('\n') : ''));
                break;
            case 'KeyValueResult':
                this.app.addMessage('system', window.SharedFormatters.formatKeyValueResult(result));
                break;
            default:
                this.app.showSystemMessage(result.message);
        }
    }

    /**
     * Handle /context command - show context usage and injected files (v1.13.9)
     * v1.14.0: Added 'hints' subcommand for bootstrap context
     */
    async handleContextCommand(args) {
        const subCmd = args.trim().toLowerCase();

        try {
            if (subCmd === 'clear') {
                // Clear injected contexts
                const data = await this.app.apiClient.clearContextInjections();

                if (data.removed_count > 0) {
                    this.app.showSystemMessage(`Cleared ${data.removed_count} injected context(s) from conversation.`);
                } else {
                    this.app.showSystemMessage('No injected contexts to clear.');
                }
                // Update badge
                await this.app.updateContextInfo();
            } else if (subCmd === 'reload') {
                // Reload bootstrap context (v1.14.1)
                const data = await this.app.apiClient.reloadContext();

                if (data.success) {
                    // v1.15.2: Server returns flat structure, not nested under 'status'
                    if (data.loaded) {
                        const sources = data.sources || [];
                        const sourceCount = sources.length;
                        const charCount = data.char_count || 0;
                        if (sourceCount > 1) {
                            this.app.showSystemMessage(`✓ Bootstrap context reloaded (merged ${sourceCount} files, ${charCount} chars)`);
                        } else if (sourceCount === 1) {
                            this.app.showSystemMessage(`✓ Bootstrap context reloaded from \`${sources[0].path}\` (${charCount} chars)`);
                        } else {
                            this.app.showSystemMessage(`✓ Bootstrap context reloaded (${charCount} chars)`);
                        }
                    } else {
                        this.app.showSystemMessage('Bootstrap context reloaded (no AGENTS.md/CLAUDE.md found in any scope).');
                    }
                } else {
                    this.app.showError(`Failed to reload context: ${data.error || 'Unknown error'}`);
                }
            } else if (subCmd === 'hints') {
                // Show active bootstrap hints (v1.14.0)
                const hints = await this.app.apiClient.getContextHints();

                if (!hints.loaded) {
                    // Get working directory for context
                    let workingDir = 'unknown';
                    try {
                        const wdData = await this.app.apiClient.getWorkingDir();
                        workingDir = wdData.path || 'unknown';
                    } catch (e) { /* ignore */ }

                    let msg = '**No bootstrap context loaded.**\n';
                    msg += `Working directory: \`${workingDir}\`\n`;
                    msg += '\n*Create AGENTS.md or CLAUDE.md in your project directory,*\n';
                    msg += '*or use `/wd <path>` to navigate to a directory with one.*';
                    this.app.addMessage('system', msg);
                    return;
                }

                let msg = '**Active Bootstrap Hints**\n';
                msg += `  Source: \`${hints.source}\`\n`;
                msg += `  Provider: ${hints.provider}\n`;
                msg += `  Model: ${hints.model}\n`;

                // Provider hints
                if (hints.provider_hints && hints.provider_hints.length > 0) {
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
                    if (hints.all_provider_keys && hints.all_provider_keys.length > 0) {
                        msg += `\n  Available: ${hints.all_provider_keys.join(', ')}`;
                    }
                    msg += '\n';
                }

                // Model hints
                if (hints.model_hints && hints.model_hints.length > 0) {
                    msg += `\n**Model Hints:** (${hints.model_hints.length} active)`;
                    msg += `\n  Matched patterns: ${hints.matched_patterns.join(', ')}\n`;
                    for (const [pattern, hint] of hints.model_hints) {
                        const displayHint = hint.length > 80 ? hint.substring(0, 80) + '...' : hint;
                        msg += `  • [${pattern}] ${displayHint}\n`;
                    }
                } else {
                    msg += '\n**Model Hints:** *none active*';
                    if (hints.all_model_patterns && hints.all_model_patterns.length > 0) {
                        msg += `\n  Available patterns: ${hints.all_model_patterns.join(', ')}`;
                    }
                    msg += '\n';
                }

                this.app.addMessage('system', msg);
            } else if (subCmd === 'show') {
                // Show bootstrap context hierarchy (v1.14.2)
                const status = await this.app.apiClient.getBootstrapContext();

                if (!status.loaded) {
                    let workingDir = 'unknown';
                    try {
                        const wdData = await this.app.apiClient.getWorkingDir();
                        workingDir = wdData.path || 'unknown';
                    } catch (e) { /* ignore */ }

                    let msg = '**No bootstrap context loaded.**\n';
                    msg += `Working directory: \`${workingDir}\`\n\n`;
                    msg += '*Scope search order:*\n';
                    msg += '1. `~/.ppxai/AGENTS.md` (global)\n';
                    msg += '2. `{git_root}/AGENTS.md` (project)\n';
                    msg += '3. `{cwd}/AGENTS.md` (subdir)\n\n';
                    msg += '*Create AGENTS.md or CLAUDE.md in any of these locations.*';
                    this.app.addMessage('system', msg);
                    return;
                }

                const sources = status.sources || [];
                const totalSize = status.total_size || 0;
                const charCount = status.char_count || 0;
                const estimatedTokens = Math.floor(charCount / 4);

                let msg = '**Bootstrap Context**\n\n';
                msg += `**Sources:** (${sources.length} file${sources.length !== 1 ? 's' : ''})\n`;

                for (let i = 0; i < sources.length; i++) {
                    const src = sources[i];
                    const sizeKb = (src.size / 1024).toFixed(1);
                    const scopeBadge = {
                        'global': '🌐 global',
                        'project': '📁 project',
                        'subdir': '📂 subdir'
                    }[src.scope] || src.scope;
                    msg += `${i + 1}. \`${src.path}\`\n`;
                    msg += `   [${scopeBadge}] ${sizeKb} KB\n`;
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
                this.app.addMessage('system', msg);
            } else {
                // Show context usage info
                const info = await this.app.apiClient.getContextInfo();

                // Build progress bar
                const percent = info.usage_percent || 0;
                const barLength = 30;
                const filled = Math.min(barLength, Math.round(barLength * Math.min(percent, 100) / 100));
                const bar = '█'.repeat(filled) + '░'.repeat(barLength - filled);

                // Color indicator
                let colorIcon = '🟢';
                if (percent >= 100) { colorIcon = '🔴'; }
                else if (percent >= 80) { colorIcon = '🟡'; }

                let contextMsg = '**Context Usage:**\n';
                contextMsg += `  Estimated: ~${(info.estimated_tokens || 0).toLocaleString()} / ${(info.context_limit || 0).toLocaleString()} tokens (${percent.toFixed(1)}%)\n`;
                contextMsg += `  Model: ${info.model || 'unknown'} (${info.provider || 'unknown'})\n`;
                contextMsg += `  Messages: ${info.message_count || 0}\n`;
                contextMsg += `  ${colorIcon} [${bar}] ${percent.toFixed(0)}%\n`;

                // Show injected files
                const injected = info.injected_contexts || [];
                if (injected.length > 0) {
                    contextMsg += `\n**Injected Contexts:** (${(info.injected_tokens || 0).toLocaleString()} tokens)\n`;
                    injected.forEach(ctx => {
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

                this.app.addMessage('system', contextMsg);
            }
        } catch (error) {
            this.app.showError(`Failed to get context info: ${error.message}`);
        }
    }

    async showStatus() {
        try {
            const data = await this.app.apiClient.getStatus();

            let text = '**Current Status:**\n\n';
            text += `- Provider: ${data.provider}\n`;
            text += `- Model: ${data.model}\n`;
            text += `- Tools: ${data.tools_enabled ? 'enabled' : 'disabled'}\n`;
            text += `- Auto-inject context: ${data.auto_inject_context ? 'yes' : 'no'}\n`;

            this.app.addMessage('system', text);
        } catch (error) {
            this.app.showError(`Failed to get status: ${error.message}`);
        }
    }

    handleThemeCommand(args) {
        if (!args) {
            this.app.showSystemMessage(`Current theme: ${this.app.state.theme}`);
        } else if (['dark', 'light', 'system'].includes(args)) {
            this.app.state.theme = args;
            this.app.applyTheme();
            localStorage.setItem('ppxai-theme', this.app.state.theme);
            this.app.showSystemMessage(`Theme set to: ${this.app.state.theme}`);
        } else {
            this.app.showError(`Unknown theme: ${args}. Available: dark, light, system`);
        }
    }

    async handleCdCommand(args) {
        if (!args || !args.trim()) {
            // No args - show current working directory (same as /pwd)
            await this.handlePwdCommand();
            return;
        }

        const targetPath = args.trim();

        try {
            const data = await this.app.apiClient.setWorkingDir(targetPath);
            this.app.showSystemMessage(`Working directory changed to: \`${data.path}\``);
            // Update the folder badge
            this.app.updateFolderBadge(data.path);
        } catch (error) {
            this.app.showError(`Failed to change directory: ${error.message}`);
        }
    }

    async handlePwdCommand() {
        try {
            const data = await this.app.apiClient.getWorkingDir();
            this.app.showSystemMessage(`Current working directory: \`${data.path}\``);
        } catch (error) {
            this.app.showError(`Failed to get working directory: ${error.message}`);
        }
    }

    /**
     * Handle /ls command - list directory contents (v1.16.0)
     */
    async handleLsCommand(args) {
        try {
            const params = new URLSearchParams();
            if (args) {
                const parts = args.trim().split(/\s+/);
                const showHidden = parts.includes('-a');
                const pathParts = parts.filter(p => p !== '-a');
                if (pathParts.length > 0) params.set('path', pathParts.join(' '));
                if (showHidden) params.set('a', 'true');
            }
            const data = await this.app.apiClient.listFiles(params.toString());
            // Format as monospace table
            const pad = (s, n) => s.padEnd(n);
            const header = `${pad('Name', 40)} ${pad('Size', 10)} Modified`;
            const sep = '-'.repeat(60);
            const rows = data.files.map(f => {
                const size = f.size != null ? this._humanSize(f.size) : '-';
                const mod = f.modified ? f.modified.replace('T', ' ').slice(0, 16) : '?';
                return `${pad(f.name, 40)} ${pad(size, 10)} ${mod}`;
            });
            const content = '```\n' + [data.path, '', header, sep, ...rows].join('\n') + '\n```';
            this.app.showSystemMessage(content);
        } catch (error) {
            this.app.showError(`Failed to list directory: ${error.message}`);
        }
    }

    _humanSize(bytes) {
        for (const unit of ['B', 'KB', 'MB', 'GB']) {
            if (Math.abs(bytes) < 1024) return unit === 'B' ? `${bytes} B` : `${bytes.toFixed(1)} ${unit}`;
            bytes /= 1024;
        }
        return `${bytes.toFixed(1)} TB`;
    }

    /**
     * Handle /tree command - show directory tree (v1.16.0)
     */
    async handleTreeCommand(args) {
        try {
            const params = new URLSearchParams();
            if (args) {
                const parts = args.trim().split(/\s+/);
                for (const part of parts) {
                    if (/^\d+$/.test(part)) params.set('depth', part);
                    else params.set('path', part);
                }
            }
            const data = await this.app.apiClient.getFileTree(params.toString());
            const lines = [];
            const renderNode = (node, prefix, isLast) => {
                const connector = isLast ? '└── ' : '├── ';
                lines.push(prefix + connector + node.label);
                const children = node.children || [];
                for (let i = 0; i < children.length; i++) {
                    const childPrefix = prefix + (isLast ? '    ' : '│   ');
                    renderNode(children[i], childPrefix, i === children.length - 1);
                }
            };
            // Root
            lines.push(data.tree.label);
            const rootChildren = data.tree.children || [];
            for (let i = 0; i < rootChildren.length; i++) {
                renderNode(rootChildren[i], '', i === rootChildren.length - 1);
            }
            const stats = `${data.stats.dirs} directories, ${data.stats.files} files`;
            const content = '```\n' + lines.join('\n') + '\n\n' + stats + '\n```';
            this.app.showSystemMessage(content);
        } catch (error) {
            this.app.showError(`Failed to get directory tree: ${error.message}`);
        }
    }

    /**
     * Handle /config command - configuration management (v1.15.2)
     * Subcommands: reload, path, or no args for help
     */
    async handleConfigCommand(args) {
        const subCmd = args ? args.trim().toLowerCase() : '';

        if (subCmd === 'reload') {
            await this.app.reloadConfig();
        } else if (subCmd === 'path') {
            try {
                const data = await this.app.apiClient.getConfigPath();
                this.app.showSystemMessage(`**Config file:** \`${data.path || 'Not found'}\``);
            } catch (error) {
                this.app.showError(`Failed to get config path: ${error.message}`);
            }
        } else {
            // Show help
            let msg = '**Config Commands:**\n\n';
            msg += '- `/config reload` - Reload config from file\n';
            msg += '- `/config path` - Show config file path\n';
            this.app.addMessage('system', msg);
        }
    }

    // === /preview Command (v1.15.4) ===

    async handlePreviewCommand(args) {
        if (!args || !args.trim()) {
            this.app.showError('Usage: /preview <file.html>');
            return;
        }

        const filepath = args.trim();

        if (filepath.toLowerCase() === 'close') {
            this.app.closeHtmlPreview();
            return;
        }

        this.app.openHtmlPreview(filepath);
    }

    async handleShowCommand(args) {
        if (!args || !args.trim()) {
            this.app.showError('Usage: /show <filepath> or /show @<search-query>');
            return;
        }

        const filepath = args.trim();

        try {
            const data = await this.app.apiClient.readFile(filepath);

            // v1.13.10: Handle image and PDF files
            if (data.type === 'image') {
                this.app.showImagePreview(data.filename || filepath, data.content, data.mime_type, data.size);
            } else if (data.type === 'pdf') {
                this.app.showPdfPreview(data.filename || filepath, data.content, data.size);
            } else {
                // Show text in preview panel
                this.app.showPreviewPanel(data.filename || filepath, data.content, data.size, data.lines);
            }
        } catch (error) {
            this.app.showError(`Failed to read file: ${error.message}`);
        }
    }
}

// Browser global export
if (typeof window !== 'undefined') {
    window.CommandDispatcher = CommandDispatcher;
}
