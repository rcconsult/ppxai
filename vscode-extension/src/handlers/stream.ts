/**
 * Stream event processing with EventBus integration.
 *
 * Phase 3b of chatPanel.ts refactoring - extracts stream event processing
 * from handleStreamEvent() and emits typed events via EventBus.
 *
 * v1.14.x - Decouples stream parsing from UI rendering
 */

import { StreamEvent } from '../httpClient';
import { ChatEventBus, ToolCallData, ToolResultData, ContextData } from './eventBus';

/**
 * Process a stream event and emit typed events via EventBus.
 *
 * This function handles parsing and validation of stream events,
 * then emits appropriate typed events that subscribers can handle.
 *
 * @param event The raw stream event from the backend
 * @param eventBus The EventBus to emit events on
 */
export function processStreamEvent(event: StreamEvent, eventBus: ChatEventBus): void {
    switch (event.type) {
        case 'thinking':
            eventBus.emit('stream:thinking', event.content);
            break;

        case 'started':
            eventBus.emit('stream:started', event.content);
            break;

        case 'reasoning_chunk':
            eventBus.emit('stream:reasoning', event.content);
            break;

        case 'chunk':
            eventBus.emit('stream:chunk', event.content);
            break;

        case 'tool_group_start':
            processToolGroupStart(event.content, eventBus);
            break;

        case 'tool_group_end':
            processToolGroupEnd(event.content, eventBus);
            break;

        case 'tool_call':
            processToolCall(event.content, eventBus);
            break;

        case 'tool_result':
            processToolResult(event.content, eventBus);
            break;

        case 'context_injected':
            processContextInjected(event.content, eventBus);
            break;

        case 'display_file':
            processDisplayFile(event, eventBus);
            break;

        case 'consent_request':
            processConsentRequest(event, eventBus);
            break;

        case 'status':
            // Status messages (checkpoint notifications, etc.)
            eventBus.emit('stream:status', event.content);
            break;

        case 'agent_iteration':
            processAgentIteration(event, eventBus);
            break;

        case 'agent_complete':
            processAgentComplete(event, eventBus);
            break;

        case 'agent_max_iterations':
            processAgentMaxIterations(event, eventBus);
            break;

        case 'working_dir_changed':
            const newPath = event.content || (event.metadata?.path as string);
            if (newPath) {
                eventBus.emit('ui:working_dir_changed', newPath);
            }
            break;

        case 'state_sync':
            // v1.17.1: Engine pushed state change — forward to subscribers
            processStateSync(event, eventBus);
            break;

        case 'error':
            eventBus.emit('stream:error', event.content);
            break;

        case 'warning':
            // v1.18.6: surface engine WARNING events (e.g. attached image
            // on a non-vision model — v1.19.0 Item 24: now either routed
            // via VL sidecar / shell tool, or the send is blocked, never a
            // silent placeholder). Payload shape:
            // {type, severity, message, details?, suggested_action?}
            // — same as the validator-warning shape the web client renders.
            try {
                const data = JSON.parse(event.content);
                eventBus.emit('stream:warning', data);
            } catch {
                eventBus.emit('stream:warning', { message: String(event.content) });
            }
            break;

        case 'done':
            eventBus.emit('stream:done', event.content);
            break;
    }
}

/**
 * Parse and emit tool call event.
 */
function processToolCall(content: string, eventBus: ChatEventBus): void {
    try {
        const data = JSON.parse(content) as ToolCallData;
        eventBus.emit('stream:tool_call', {
            tool: data.tool,
            arguments: data.arguments,
            call_id: data.call_id
        });
    } catch {
        // Fallback: emit as raw content for legacy handling
        console.warn('Failed to parse tool_call event:', content);
    }
}

/**
 * Parse and emit tool result event.
 */
function processToolResult(content: string, eventBus: ChatEventBus): void {
    try {
        const data = JSON.parse(content) as ToolResultData;
        eventBus.emit('stream:tool_result', {
            tool: data.tool,
            result: data.result,
            call_id: data.call_id,
            success: data.success
        });
    } catch {
        console.warn('Failed to parse tool_result event:', content);
    }
}

/**
 * Parse and emit tool group start event.
 */
function processToolGroupStart(content: string, eventBus: ChatEventBus): void {
    try {
        const data = JSON.parse(content);
        eventBus.emit('stream:tool_group_start', data);
    } catch {
        console.warn('Failed to parse tool_group_start event:', content);
        // Fallback: emit empty object to prevent crashes
        eventBus.emit('stream:tool_group_start', {});
    }
}

/**
 * Parse and emit tool group end event.
 */
function processToolGroupEnd(content: string, eventBus: ChatEventBus): void {
    try {
        const data = JSON.parse(content);
        eventBus.emit('stream:tool_group_end', data);
    } catch {
        console.warn('Failed to parse tool_group_end event:', content);
        // Fallback: emit empty object to prevent crashes
        eventBus.emit('stream:tool_group_end', {});
    }
}

/**
 * Parse and emit context injected event.
 */
function processContextInjected(content: string, eventBus: ChatEventBus): void {
    try {
        const data = JSON.parse(content) as ContextData;
        eventBus.emit('stream:context_injected', {
            source: data.source,
            content: data.content,
            language: data.language,
            size: data.size,
            truncated: data.truncated
        });
    } catch {
        // Ignore parse errors for context injection
    }
}

/**
 * Parse and emit display file event (v1.15.2).
 * Triggered when AI uses display_file tool to proactively show a file.
 */
function processDisplayFile(event: StreamEvent, eventBus: ChatEventBus): void {
    try {
        // Event metadata contains {filepath: string}
        const filepath = event.metadata?.filepath as string;
        if (filepath) {
            eventBus.emit('stream:display_file', filepath);
        }
    } catch (error) {
        console.warn('Failed to parse display_file event:', error);
    }
}

/**
 * Parse and emit consent request event.
 */
function processConsentRequest(event: StreamEvent, eventBus: ChatEventBus): void {
    try {
        const data = JSON.parse(event.content);

        // Determine consent type
        if (data.type === 'shell' || data.command) {
            // Shell command consent
            eventBus.emit('consent:shell_request', {
                type: 'shell',
                command: data.command,
                working_dir: data.working_dir,
                risk_level: data.risk_level,
                tool_name: data.tool_name
            });
        } else {
            // File edit consent
            eventBus.emit('consent:file_request', {
                file_path: data.file_path,
                operation: data.operation,
                tool_name: data.tool_name
            }, event.metadata);
        }
    } catch (error) {
        console.error('Consent request parse error:', error);
    }
}

/**
 * Parse and emit agent iteration event.
 */
function processAgentIteration(event: StreamEvent, eventBus: ChatEventBus): void {
    try {
        const data = event.metadata || JSON.parse(event.content);
        const iteration = (data.iteration as number) || 0;
        const max = (data.max as number) || 10;
        eventBus.emit('agent:iteration', iteration, max);
    } catch {
        // Fallback with defaults
        eventBus.emit('agent:iteration', 0, 10);
    }
}

/**
 * Parse and emit agent complete event.
 */
function processAgentComplete(event: StreamEvent, eventBus: ChatEventBus): void {
    try {
        const data = event.metadata || JSON.parse(event.content);
        const summary = (data.summary as string) || '';
        eventBus.emit('agent:complete', summary);
    } catch {
        eventBus.emit('agent:complete', '');
    }
}

/**
 * Parse and emit agent max iterations event.
 */
function processAgentMaxIterations(event: StreamEvent, eventBus: ChatEventBus): void {
    try {
        const data = event.metadata || JSON.parse(event.content);
        const iterations = (data.iterations as number) || 10;
        eventBus.emit('agent:max_iterations', iterations);
    } catch {
        eventBus.emit('agent:max_iterations', 10);
    }
}

/**
 * Process state_sync event — engine pushed an AppState field change.
 * Emits 'state:sync' with the changed fields as a plain object.
 */
function processStateSync(event: StreamEvent, eventBus: ChatEventBus): void {
    try {
        const data = typeof event.content === 'string'
            ? JSON.parse(event.content)
            : event.content;
        if (data && typeof data === 'object') {
            eventBus.emit('state:sync', data);
        }
    } catch {
        console.warn('Failed to parse state_sync event:', event.content);
    }
}
