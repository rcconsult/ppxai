/**
 * Handlers module barrel export
 *
 * Phases 2-3 of chatPanel.ts refactoring - exports:
 * - HandlerContext interface for dependency injection (Phase 2)
 * - Command handler for /checkpoint (Phase 2)
 * - EventBus for pub/sub communication (Phase 3a)
 * - Stream event processor (Phase 3b)
 */

// Phase 2: Command handlers with IoC pattern
export { HandlerContext, HandlerResult, DialogCallbacks, CommandHandler } from './types';
// ADR 0007 step 5 (2026-09-21): `/tools`, `/ls` and `/tree` route through
// `POST /command/<name>` now, so their bespoke-REST handlers are deleted.
// `/checkpoint` is the one acknowledged-legacy intercept left — see
// LEGACY_INTERCEPTS in ../commandRouter.ts for why.
export { handleCheckpointCommand } from './commands';

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
    ConsentResolvedData,
    WarningEventData
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
