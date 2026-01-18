/**
 * Handler context types for Inversion of Control pattern.
 *
 * Decouples command handlers from ChatViewProvider's instance state,
 * enabling testability and single-responsibility separation.
 */

import { HttpClient } from '../httpClient';

/**
 * Result of a handler operation - used for consistent message types.
 */
export interface HandlerResult {
    /** Message type: 'systemMessage' for info, 'error' for errors */
    type: 'systemMessage' | 'error';
    /** Message content (markdown supported) */
    content: string;
}

/**
 * Callback for displaying native VSCode dialogs.
 * Uses Thenable for VSCode API compatibility.
 */
export interface DialogCallbacks {
    /** Show a warning message with optional modal and actions */
    showWarningMessage(message: string, options: { modal: boolean }, ...actions: string[]): Thenable<string | undefined>;
}

/**
 * Context provided to command handlers via dependency injection.
 *
 * Handlers receive this context instead of accessing ChatViewProvider's
 * private members directly, enabling:
 * - Unit testing with mock contexts
 * - Clear dependency boundaries
 * - Potential reuse across different view providers
 */
export interface HandlerContext {
    /** Post a message to the webview */
    postMessage: (msg: HandlerResult) => void;

    /** Backend HTTP client for API calls */
    backend: HttpClient;

    /** Refresh the status display */
    updateStatus: () => Promise<void>;

    /** Refresh the agent status display */
    updateAgentStatus: () => Promise<void>;

    /** VSCode dialog callbacks (for confirmations, etc.) */
    dialogs: DialogCallbacks;
}

/**
 * Type signature for a slash command handler.
 */
export type CommandHandler = (ctx: HandlerContext, args: string[]) => Promise<void>;
