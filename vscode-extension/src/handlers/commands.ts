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
                        content: 'No checkpoints found.\nRun an `/auto` task to create checkpoints.'
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
