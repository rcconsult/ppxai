/**
 * Handlers module barrel export
 *
 * Phases 3-4 of chatPanel.ts refactoring - exports:
 * - EventBus for pub/sub communication (Phase 3a)
 * - Stream event processor (Phase 3b)
 * - Agent state machine (Phase 4a) + consent handlers (Phase 4b)
 *
 * Phase 2's bespoke-REST command handlers are GONE (2026-09-21). ADR
 * 0007 step 5 routed `/tools`, `/ls`, `/tree` and `/context` through
 * `POST /command/<name>`; `/checkpoint` followed once `/checkpoint
 * clear` grew a confirmation that works in all four clients, and with
 * it went `commands.ts`, `types.ts` (`HandlerContext`,
 * `HandlerResult`, `DialogCallbacks`, `CommandHandler` — nothing else
 * used them) and the whole `LEGACY_INTERCEPTS` mechanism in
 * ../commandRouter.ts.
 */

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
