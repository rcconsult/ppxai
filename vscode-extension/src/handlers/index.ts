/**
 * Handlers module barrel export
 *
 * Phases 2-3 of chatPanel.ts refactoring - exports:
 * - HandlerContext interface for dependency injection (Phase 2)
 * - Command handlers for /tools, /checkpoint (Phase 2)
 * - EventBus for pub/sub communication (Phase 3a)
 * - Stream event processor (Phase 3b)
 */

// Phase 2: Command handlers with IoC pattern
export { HandlerContext, HandlerResult, DialogCallbacks, CommandHandler } from './types';
export { handleToolsCommand, handleCheckpointCommand, handleLsCommand, handleTreeCommand } from './commands';

// Phase 3b: Stream event processing
export { processStreamEvent } from './stream';

// Phase 3a: EventBus for decoupled event handling
export {
    ChatEventBus,
    ChatEvents,
    StreamEvents,
    ConsentEvents,
    AgentEvents,
    UIEvents,
    ToolCallData,
    ToolResultData,
    ContextData,
    ConsentResolvedData
} from './eventBus';

// Re-export consent types from httpClient via eventBus
export type {
    FileConsentRequest,
    ShellConsentRequest,
    EventMetadata,
    ConsentResponse
} from './eventBus';

// Phase 4a: Agent state machine
export {
    AgentStateMachine,
    AgentState,
    AgentInput,
    AgentConfig,
    ConsentRequest,
    ConsentResponseValue
} from './agentStateMachine';

// Phase 4b: Consent handlers
export {
    handleFileConsent,
    handleShellConsent,
    createVSCodeConsentContext,
    ConsentContext,
    ConsentDialogs,
    ConsentPickItem,
    TerminalExecutor,  // v1.14.2
    FILE_CONSENT_OPTIONS,
    SHELL_CONSENT_OPTIONS
} from './consent';
