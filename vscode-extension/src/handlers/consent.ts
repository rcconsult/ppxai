/**
 * Consent handler module for file and shell consent requests.
 *
 * Phase 4b of chatPanel.ts refactoring - extracts consent dialog logic
 * using Inversion of Control pattern for testability.
 *
 * v1.14.x - Enables isolated testing of consent flows
 */

import { HttpClient, FileConsentRequest, ShellConsentRequest, EventMetadata, ConsentResponse } from '../httpClient';
import { ChatEventBus } from './eventBus';

// ============================================================================
// Types
// ============================================================================

/** QuickPick item for consent dialogs */
export interface ConsentPickItem {
    label: string;
    detail: string;
    value: ConsentResponse;
}

/** Dialog interface for dependency injection (VSCode-agnostic) */
export interface ConsentDialogs {
    showQuickPick(
        items: ConsentPickItem[],
        options: { placeHolder: string; title: string; ignoreFocusOut: boolean }
    ): Promise<ConsentPickItem | undefined>;
}

/** Context for consent handlers */
export interface ConsentContext {
    backend: HttpClient;
    dialogs: ConsentDialogs;
    eventBus?: ChatEventBus;
}

// ============================================================================
// Consent Option Templates
// ============================================================================

/** Standard file consent options */
export const FILE_CONSENT_OPTIONS: ConsentPickItem[] = [
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

/** Standard shell consent options */
export const SHELL_CONSENT_OPTIONS: ConsentPickItem[] = [
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

// ============================================================================
// Consent Handlers
// ============================================================================

/**
 * Handle file edit consent request.
 *
 * Shows a keyboard-friendly QuickPick asking user for permission to edit a file.
 * Supports: Yes (this file), No, Always (all files), Never (block all)
 *
 * @param ctx Consent context with backend and dialogs
 * @param data File consent request data
 * @param metadata Optional event metadata
 */
export async function handleFileConsent(
    ctx: ConsentContext,
    data: FileConsentRequest,
    metadata?: EventMetadata
): Promise<void> {
    try {
        const filePath = data.file_path || metadata?.file_path as string;

        if (!filePath) {
            console.error('File consent request missing file_path');
            return;
        }

        // Show consent dialog
        const selected = await ctx.dialogs.showQuickPick(FILE_CONSENT_OPTIONS, {
            placeHolder: `📝 File Edit: ${filePath}`,
            title: 'File Edit Consent Required',
            ignoreFocusOut: true
        });

        // Map selection to response (default: deny)
        const response: ConsentResponse = selected?.value || 'n';

        // Send consent response to server
        await ctx.backend.consent(filePath, response);

        // Emit consent resolved event
        ctx.eventBus?.emit('consent:resolved', {
            filepath: filePath,
            response
        });

    } catch (error) {
        console.error('Consent request error:', error);
        // On error, deny for safety
        const filePath = data.file_path || metadata?.file_path as string;
        if (filePath) {
            try {
                await ctx.backend.consent(filePath, 'n');
            } catch {
                // Ignore - best effort
            }
        }
    }
}

/**
 * Handle shell command consent request.
 *
 * Shows a keyboard-friendly QuickPick asking user for permission to execute a shell command.
 * Displays command, working directory, and risk level.
 * Supports: Yes (this command), No, Always (all commands), Never (block all)
 *
 * @param ctx Consent context with backend and dialogs
 * @param data Shell consent request data
 */
export async function handleShellConsent(
    ctx: ConsentContext,
    data: ShellConsentRequest
): Promise<void> {
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

        // Truncate long commands for display
        const displayCommand = command.length > 50 ? command.substring(0, 50) + '...' : command;

        // Show consent dialog
        const selected = await ctx.dialogs.showQuickPick(SHELL_CONSENT_OPTIONS, {
            placeHolder: `${riskEmoji} ${riskMessage}: ${displayCommand}`,
            title: `Shell Command Consent Required (in ${workingDir})`,
            ignoreFocusOut: true
        });

        // Map selection to response (default: deny)
        const response: ConsentResponse = selected?.value || 'n';

        // Send shell consent response to server
        await ctx.backend.shellConsent(command, workingDir, response);

        // Emit consent resolved event
        ctx.eventBus?.emit('consent:resolved', {
            command,
            response
        });

    } catch (error) {
        console.error('Shell consent request error:', error);
        // On error, deny for safety
        const command = data.command;
        const workingDir = data.working_dir || '.';
        if (command) {
            try {
                await ctx.backend.shellConsent(command, workingDir, 'n');
            } catch {
                // Ignore - best effort
            }
        }
    }
}

/**
 * Create a consent context from VSCode APIs.
 * This is the adapter that bridges the VSCode-agnostic handlers with VSCode dialogs.
 *
 * @param backend HttpClient for API calls
 * @param vscodeWindow VSCode window API
 * @param eventBus Optional EventBus for events
 */
export function createVSCodeConsentContext(
    backend: HttpClient,
    vscodeWindow: { showQuickPick: <T extends vscode.QuickPickItem>(items: T[], options?: vscode.QuickPickOptions) => Thenable<T | undefined> },
    eventBus?: ChatEventBus
): ConsentContext {
    return {
        backend,
        eventBus,
        dialogs: {
            showQuickPick: async (items, options) => {
                const result = await vscodeWindow.showQuickPick(items, options);
                return result as ConsentPickItem | undefined;
            }
        }
    };
}
