/**
 * Extracted command handlers for chatPanel.ts
 *
 * Phase 2 of chatPanel.ts refactoring - uses Inversion of Control pattern
 * to decouple handlers from ChatViewProvider instance state.
 *
 * v1.14.x - Extracted from chatPanel.ts for better separation of concerns
 */

import { HandlerContext, HandlerResult } from './types';

// ============================================================================
// /tools Command Handler
// ============================================================================

/**
 * Handle /tools command - manage tool settings and status
 */
export async function handleToolsCommand(ctx: HandlerContext, args: string[]): Promise<void> {
    const subcommand = args[0]?.toLowerCase() || 'status';

    switch (subcommand) {
        case 'enable':
            await ctx.backend.enableTools();
            const tools = await ctx.backend.listTools();
            ctx.postMessage({
                type: 'systemMessage',
                content: `✓ Tools enabled (${tools.length} tools available)`
            });
            await ctx.updateStatus();
            break;

        case 'disable':
            await ctx.backend.disableTools();
            ctx.postMessage({
                type: 'systemMessage',
                content: '✓ Tools disabled'
            });
            await ctx.updateStatus();
            break;

        case 'list':
            const toolsList = await ctx.backend.listTools();
            if (toolsList.length === 0) {
                ctx.postMessage({
                    type: 'systemMessage',
                    content: 'No tools available. Use `/tools enable` first.'
                });
            } else {
                const list = toolsList.map(t => `• **${t.name}**: ${t.description}`).join('\n');
                ctx.postMessage({
                    type: 'systemMessage',
                    content: `**Available Tools:**\n${list}`
                });
            }
            break;

        case 'config':
            if (args.length >= 3) {
                const setting = args[1];
                const value = args[2];
                await ctx.backend.setToolConfig(setting, value);
                ctx.postMessage({
                    type: 'systemMessage',
                    content: `✓ Set ${setting} = ${value}`
                });
            } else {
                // Show current config (matches TUI behavior)
                const configStatus = await ctx.backend.getToolsStatus();
                ctx.postMessage({
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
                    await ctx.backend.setToolConfig('verbose', enabled ? 'on' : 'off');
                    ctx.postMessage({
                        type: 'systemMessage',
                        content: enabled
                            ? '✓ Verbose tool logging enabled\n*Tool inputs and outputs will be displayed during execution*'
                            : '✓ Verbose tool logging disabled'
                    });
                } else {
                    ctx.postMessage({
                        type: 'error',
                        content: `Unknown setting: ${setting}\nAvailable: verbose`
                    });
                }
            } else {
                ctx.postMessage({
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
                    await ctx.backend.enableAgentMode();
                    ctx.postMessage({
                        type: 'systemMessage',
                        content: '✓ Agent mode enabled\n*Tools auto-enabled. Use `/agent <task>` to start autonomous execution.*'
                    });
                    await ctx.updateAgentStatus();
                    await ctx.updateStatus();
                } else if (['off', 'disable'].includes(action)) {
                    await ctx.backend.disableAgentMode();
                    ctx.postMessage({
                        type: 'systemMessage',
                        content: '✓ Agent mode disabled'
                    });
                    await ctx.updateAgentStatus();
                } else {
                    ctx.postMessage({
                        type: 'error',
                        content: `Unknown action: ${action}\nUsage: /tools agent on|off`
                    });
                }
            } else {
                // Show current agent status
                const agentStatus = await ctx.backend.getAgentStatus();
                ctx.postMessage({
                    type: 'systemMessage',
                    content: `**Agent Mode:** ${agentStatus.agent_mode ? 'ON' : 'OFF'}

Usage: \`/tools agent on|off\`
       \`/agent <task>\` - Run autonomous task`
                });
            }
            break;

        case 'help':
            if (args[1] === 'editing') {
                ctx.postMessage({
                    type: 'systemMessage',
                    content: getFileEditingHelp()
                });
            } else if (args[1]) {
                // v1.11.9: Show help for specific tool (matches TUI)
                await showToolHelp(ctx, args[1]);
            } else {
                ctx.postMessage({
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
            const status = await ctx.backend.getToolsStatus();
            const available = status.enabled ? await ctx.backend.listTools() : [];
            const agentMode = await ctx.backend.getAgentStatus();
            ctx.postMessage({
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
async function showToolHelp(ctx: HandlerContext, toolName: string): Promise<void> {
    try {
        const toolsList = await ctx.backend.listTools();
        const tool = toolsList.find(t => t.name.toLowerCase() === toolName.toLowerCase());

        if (!tool) {
            ctx.postMessage({
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

        ctx.postMessage({
            type: 'systemMessage',
            content: `**Tool: ${tool.name}**

${tool.description}${paramsInfo}`
        });
    } catch (error) {
        ctx.postMessage({
            type: 'error',
            content: `Failed to get tool help: ${error}`
        });
    }
}

/**
 * File editing help text
 */
function getFileEditingHelp(): string {
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

// ============================================================================
// /checkpoint Command Handler
// ============================================================================

/**
 * Handle /checkpoint command - manage file checkpoints for undo
 */
export async function handleCheckpointCommand(ctx: HandlerContext, args: string[]): Promise<void> {
    const subcommand = args[0]?.toLowerCase() || 'status';

    try {
        switch (subcommand) {
            case 'status':
                const status = await ctx.backend.getCheckpointStatus();
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
                ctx.postMessage({
                    type: 'systemMessage',
                    content: statusMsg
                });
                break;

            case 'list':
                const result = await ctx.backend.listCheckpoints(10);
                if (result.checkpoints.length === 0) {
                    ctx.postMessage({
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
                    ctx.postMessage({
                        type: 'systemMessage',
                        content: listMsg
                    });
                }
                break;

            case 'backend':
                const backend = args[1]?.toLowerCase() as 'git' | 'file' | 'auto' | 'none';
                if (!backend) {
                    const currentStatus = await ctx.backend.getCheckpointStatus();
                    ctx.postMessage({
                        type: 'systemMessage',
                        content: `Current backend: **${currentStatus.backend}**\n\nUsage: \`/checkpoint backend <git|file|auto|none>\``
                    });
                } else if (!['git', 'file', 'auto', 'none'].includes(backend)) {
                    ctx.postMessage({
                        type: 'error',
                        content: `Invalid backend: ${backend}\nValid options: git, file, auto, none`
                    });
                } else {
                    const backendResult = await ctx.backend.setCheckpointBackend(backend);
                    ctx.postMessage({
                        type: 'systemMessage',
                        content: `✓ Checkpoint backend set to: **${backendResult.backend}**`
                    });
                }
                break;

            case 'clear':
                const clearStatus = await ctx.backend.getCheckpointStatus();
                if (clearStatus.backend !== 'file') {
                    ctx.postMessage({
                        type: 'systemMessage',
                        content: `Clear only applies to file-based checkpoints.\nCurrent backend: ${clearStatus.backend}`
                    });
                } else {
                    const confirm = await ctx.dialogs.showWarningMessage(
                        'Clear all file-based checkpoints?',
                        { modal: true },
                        'Clear'
                    );
                    if (confirm === 'Clear') {
                        const clearResult = await ctx.backend.clearFileCheckpoints(0);
                        ctx.postMessage({
                            type: 'systemMessage',
                            content: `✓ Cleared ${clearResult.removed} checkpoint(s)`
                        });
                    }
                }
                break;

            case 'info':
                const cpId = args[1];
                if (!cpId) {
                    ctx.postMessage({
                        type: 'error',
                        content: 'Usage: `/checkpoint info <checkpoint_id>`\nUse `/checkpoint list` to see available checkpoints.'
                    });
                } else {
                    const checkpoints = await ctx.backend.listCheckpoints(20);
                    const matching = checkpoints.checkpoints.find(cp => cp.id.startsWith(cpId));
                    if (!matching) {
                        ctx.postMessage({
                            type: 'error',
                            content: `Checkpoint not found: ${cpId}\nUse \`/checkpoint list\` to see available checkpoints.`
                        });
                    } else {
                        let infoMsg = '**Checkpoint Details**\n';
                        infoMsg += `• ID: \`${matching.id}\`\n`;
                        infoMsg += `• Description: ${matching.description}\n`;
                        infoMsg += `• Timestamp: ${matching.timestamp}\n`;
                        ctx.postMessage({
                            type: 'systemMessage',
                            content: infoMsg
                        });
                    }
                }
                break;

            case 'undo':
                // Delegate to existing undo functionality
                const undoResult = await ctx.backend.undoCheckpoint();
                ctx.postMessage({
                    type: 'systemMessage',
                    content: undoResult.success
                        ? `✓ ${undoResult.message}`
                        : `✗ ${undoResult.message}`
                });
                break;

            default:
                ctx.postMessage({
                    type: 'error',
                    content: `Unknown subcommand: ${subcommand}\nAvailable: status, list, backend, clear, info, undo`
                });
        }
    } catch (error) {
        ctx.postMessage({
            type: 'error',
            content: `Checkpoint error: ${error}`
        });
    }
}

// ============================================================================
// /ls Command Handler (v1.16.0)
// ============================================================================

function humanSize(bytes: number | null): string {
    if (bytes == null) { return '-'; }
    for (const unit of ['B', 'KB', 'MB', 'GB']) {
        if (Math.abs(bytes) < 1024) { return unit === 'B' ? `${bytes} B` : `${bytes.toFixed(1)} ${unit}`; }
        bytes /= 1024;
    }
    return `${bytes.toFixed(1)} TB`;
}

/**
 * Handle /ls command - list directory contents
 */
export async function handleLsCommand(ctx: HandlerContext, args: string[]): Promise<void> {
    try {
        const showHidden = args.includes('-a');
        const pathParts = args.filter(a => a !== '-a');
        const targetPath = pathParts.length > 0 ? pathParts.join(' ') : undefined;

        const data = await ctx.backend.listFiles(targetPath, showHidden);
        const pad = (s: string, n: number) => s.padEnd(n);

        const header = `${pad('Name', 40)} ${pad('Size', 10)} Modified`;
        const sep = '-'.repeat(60);
        const rows = data.files.map((f: any) => {
            const size = humanSize(f.size);
            const mod = f.modified ? f.modified.replace('T', ' ').slice(0, 16) : '?';
            return `${pad(f.name, 40)} ${pad(size, 10)} ${mod}`;
        });
        const content = '```\n' + [data.path, '', header, sep, ...rows].join('\n') + '\n```';
        ctx.postMessage({ type: 'systemMessage', content });
    } catch (error) {
        ctx.postMessage({
            type: 'error',
            content: `Failed to list directory: ${error}`
        });
    }
}

// ============================================================================
// /tree Command Handler (v1.16.0)
// ============================================================================

/**
 * Handle /tree command - show directory tree
 */
export async function handleTreeCommand(ctx: HandlerContext, args: string[]): Promise<void> {
    try {
        let targetPath: string | undefined;
        let depth: number | undefined;
        for (const part of args) {
            if (/^\d+$/.test(part)) { depth = parseInt(part, 10); }
            else { targetPath = part; }
        }

        const data = await ctx.backend.getFileTree(targetPath, depth);
        const lines: string[] = [];
        const renderNode = (node: any, prefix: string, isLast: boolean) => {
            const connector = isLast ? '└── ' : '├── ';
            lines.push(prefix + connector + node.label);
            const children = node.children || [];
            for (let i = 0; i < children.length; i++) {
                const childPrefix = prefix + (isLast ? '    ' : '│   ');
                renderNode(children[i], childPrefix, i === children.length - 1);
            }
        };

        lines.push(data.tree.label);
        const rootChildren = data.tree.children || [];
        for (let i = 0; i < rootChildren.length; i++) {
            renderNode(rootChildren[i], '', i === rootChildren.length - 1);
        }
        const stats = `${data.stats.dirs} directories, ${data.stats.files} files`;
        const content = '```\n' + lines.join('\n') + '\n\n' + stats + '\n```';
        ctx.postMessage({ type: 'systemMessage', content });
    } catch (error) {
        ctx.postMessage({
            type: 'error',
            content: `Failed to get directory tree: ${error}`
        });
    }
}
