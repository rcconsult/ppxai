/**
 * EventBus for decoupled event-driven architecture.
 *
 * Phase 3a of chatPanel.ts refactoring - provides pub/sub pattern
 * to decouple stream handlers, consent handlers, and UI updates.
 *
 * v1.14.x - Enables isolated handler testing and cleaner separation
 */

import {
    FileConsentRequest,
    ShellConsentRequest,
    EventMetadata,
    ConsentResponse
} from '../httpClient';

// Re-export types from httpClient for convenience
export type { FileConsentRequest, ShellConsentRequest, EventMetadata, ConsentResponse };

// ============================================================================
// Event Data Types (unique to EventBus)
// ============================================================================

/** Tool call data from stream events */
export interface ToolCallData {
    tool: string;
    arguments: Record<string, unknown>;
    call_id?: string;
}

/** Tool result data from stream events */
export interface ToolResultData {
    tool: string;
    result: string;
    call_id?: string;
    success?: boolean;
}

/** Context injection data */
export interface ContextData {
    source: string;
    content: string;
    language?: string;
    size?: number;
    truncated?: boolean;
}

/** Consent resolution event data (for 'consent:resolved') */
export interface ConsentResolvedData {
    filepath?: string;
    command?: string;
    response: ConsentResponse;
}

// ============================================================================
// Event Maps (type-safe event signatures)
// ============================================================================

/** Events emitted by stream handlers */
export interface StreamEvents {
    'stream:thinking': (content: string) => void;
    'stream:started': (content: string) => void;
    'stream:chunk': (content: string) => void;
    'stream:reasoning': (content: string) => void;
    'stream:tool_call': (data: ToolCallData) => void;
    'stream:tool_result': (data: ToolResultData) => void;
    'stream:context_injected': (data: ContextData) => void;
    'stream:done': (content: string) => void;
    'stream:error': (content: string) => void;
}

/** Events emitted by consent handlers */
export interface ConsentEvents {
    'consent:file_request': (data: FileConsentRequest, metadata?: EventMetadata) => void;
    'consent:shell_request': (data: ShellConsentRequest) => void;
    'consent:resolved': (data: ConsentResolvedData) => void;
}

/** Events emitted by agent state machine */
export interface AgentEvents {
    'agent:started': (task: string) => void;
    'agent:iteration': (n: number, max: number) => void;
    'agent:complete': (summary: string) => void;
    'agent:max_iterations': (iterations: number) => void;
    'agent:error': (message: string) => void;
    'agent:interrupted': () => void;
}

/** Events for UI updates */
export interface UIEvents {
    'ui:status_update': () => void;
    'ui:working_dir_changed': (path: string) => void;
    'ui:clear': () => void;
}

/** Combined event map for type-safe subscriptions */
export type ChatEvents = StreamEvents & ConsentEvents & AgentEvents & UIEvents;

// ============================================================================
// EventBus Implementation
// ============================================================================

/**
 * Type-safe event emitter for decoupled handler communication.
 *
 * Features:
 * - Type-safe event names and handler signatures
 * - Synchronous event delivery for predictable ordering
 * - Error isolation (one handler crash doesn't break others)
 * - Automatic unsubscribe via returned function
 *
 * Usage:
 * ```typescript
 * const bus = new ChatEventBus();
 *
 * // Subscribe
 * const unsubscribe = bus.on('stream:chunk', (content) => {
 *     console.log('Received:', content);
 * });
 *
 * // Emit
 * bus.emit('stream:chunk', 'Hello');
 *
 * // Unsubscribe
 * unsubscribe();
 * ```
 */
export class ChatEventBus {
    private listeners = new Map<string, Set<(...args: unknown[]) => void>>();

    /**
     * Subscribe to an event.
     * @param event Event name
     * @param handler Handler function (type-safe signature)
     * @returns Unsubscribe function
     */
    on<K extends keyof ChatEvents>(event: K, handler: ChatEvents[K]): () => void {
        if (!this.listeners.has(event)) {
            this.listeners.set(event, new Set());
        }
        this.listeners.get(event)!.add(handler);
        return () => this.off(event, handler);
    }

    /**
     * Unsubscribe from an event.
     * @param event Event name
     * @param handler Handler function to remove
     */
    off<K extends keyof ChatEvents>(event: K, handler: ChatEvents[K]): void {
        this.listeners.get(event)?.delete(handler);
    }

    /**
     * Emit an event to all subscribers.
     * Errors in handlers are caught and logged to prevent cascade failures.
     * @param event Event name
     * @param args Event arguments (type-safe)
     */
    emit<K extends keyof ChatEvents>(event: K, ...args: Parameters<ChatEvents[K]>): void {
        this.listeners.get(event)?.forEach(handler => {
            try {
                handler(...args);
            } catch (e) {
                console.error(`EventBus error in ${event}:`, e);
            }
        });
    }

    /**
     * Subscribe to an event for one-time execution.
     * Handler is automatically removed after first call.
     * @param event Event name
     * @param handler Handler function
     * @returns Unsubscribe function (in case you want to cancel before event fires)
     */
    once<K extends keyof ChatEvents>(event: K, handler: ChatEvents[K]): () => void {
        const wrapper = ((...args: Parameters<ChatEvents[K]>) => {
            this.off(event, wrapper as ChatEvents[K]);
            (handler as (...a: unknown[]) => void)(...args);
        }) as ChatEvents[K];
        return this.on(event, wrapper);
    }

    /**
     * Remove all listeners for an event (or all events if no event specified).
     * Useful for cleanup during dispose/deactivation.
     * @param event Optional event name to clear
     */
    clear(event?: keyof ChatEvents): void {
        if (event) {
            this.listeners.delete(event);
        } else {
            this.listeners.clear();
        }
    }

    /**
     * Get count of listeners for debugging/testing.
     * @param event Optional event name
     * @returns Number of listeners
     */
    listenerCount(event?: keyof ChatEvents): number {
        if (event) {
            return this.listeners.get(event)?.size ?? 0;
        }
        let count = 0;
        this.listeners.forEach(set => count += set.size);
        return count;
    }
}
