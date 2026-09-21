/**
 * AppStateFields — GENERATED FILE. DO NOT EDIT.
 *
 * Source:     ppxai/engine/app_state_schema.json (schema version 1.1)
 * Generator:  vscode-extension/scripts/sync-schema.js
 * Regenerate: `npm run sync-schema` from vscode-extension/
 *             (also runs on precompile / prepackage / prewatch)
 *
 * Field names, order and base types come straight from the canonical
 * schema. The canonical schema is LANGUAGE-NEUTRAL and never names a
 * TypeScript type, so the few container fields that deserve a richer
 * shape are narrowed by the hand-written TYPE_REFINEMENTS map in the
 * generator, pointing at the element interfaces in ./appStateTypes.
 *
 * Output is deterministic and carries no timestamp:
 * tests/test_app_state_generated_types.py regenerates it in memory and
 * fails on any difference, in either direction.
 */

import { AgentBeatSnapshot, BackgroundAgentSummary, ContextAttachment } from './appStateTypes';

/**
 * Canonical state fields shared across all ppxai clients, in camelCase.
 *
 * One entry per field in the canonical schema — no more, no less.
 */
export interface AppStateFields {
    /** `provider` (core) — Active provider ID (e.g. 'perplexity', 'openai') */
    currentProvider: string;

    /** `model` (core) — Active model ID (e.g. 'sonar-pro') */
    currentModel: string;

    /** `working_dir` (core) — Current working directory path */
    workingDir: string;

    /** `session_id` (core) — Session identifier */
    sessionId: string;

    /** `session_name` (core) — Human-readable session name */
    sessionName: string;

    /** `tools_enabled` (features) — AI tools available */
    toolsEnabled: boolean;

    /** `tools_verbose` (features) — Show detailed tool output */
    toolsVerbose: boolean;

    /** `agent_mode` (features) — Autonomous task execution mode */
    agentMode: boolean;

    /** `auto_route` (features) — Auto-route coding tasks to a specialized model */
    autoRoute: boolean;

    /** `is_streaming` (streaming) — Response stream in progress */
    isStreaming: boolean;

    /** `cancel_requested` (streaming) — User requested stream cancellation */
    cancelRequested: boolean;

    /** `total_tokens` (usage) — Total tokens (prompt + completion) */
    totalTokens: number;

    /** `prompt_tokens` (usage) — Prompt/input tokens */
    promptTokens: number;

    /** `completion_tokens` (usage) — Completion/output tokens */
    completionTokens: number;

    /** `estimated_cost` (usage) — Cumulative estimated cost in USD. Sourced from UsageStats.estimated_cost; the AppState field shares that name (was total_cost/totalCost, renamed v1.19.0 to end the cross-client remap). */
    estimatedCost: number;

    /** `context_percentage` (usage) — Context window usage (0.0-100.0) */
    contextPercentage: number;

    /** `context_attachments` (multimodal) — List of attachment summaries currently in session.messages. Entry schema: {name, kind, media_type, turn_index, file_id} */
    contextAttachments: ContextAttachment[];

    /** `model_supports_vision` (multimodal) — Whether the active model accepts image_url content parts natively (per model_profiles.supports_vision). Pushed via SSE on every model switch. Clients use this to gate the attach button (passive badge) and warn when the user attaches an image to a non-vision model. False is the conservative default for unregistered models. */
    modelSupportsVision: boolean;

    /** `agent_beat` (streaming) — P0 (v1.18.0) latest agent heartbeat state. Entry schema: {iteration, beat, tool, ok, failures, elapsed_s}. Empty dict when no agent run is active. Populated by EngineClient on AGENT_BEAT events. */
    agentBeat: AgentBeatSnapshot | Record<string, never>;

    /** `last_message_role` (core) — Role of the most recent session message ('' if empty, else 'user'|'assistant'|'system'|'tool'). Maintained by EngineClient via SessionManager.on_messages_changed so Python TUI clients (Rich, Textual) never need to scan session.messages for interrupt/alternation checks. Not currently in SSE_SYNC_FIELDS — web/VSCode do their own message tracking. */
    lastMessageRole: string;

    /** `debug_log` (debug) — Debug logging enabled */
    debugLog: boolean;

    /** `background_agents` (agents) — v1.19.0 (Inc 9) Active (non-terminal) /v1/agent/* runs, newest first, for a UI background-agents badge that survives reconnect. Entry schema: {run_id, status, task, owner}. Mirrors the server-global AgentRunRegistry: pushed via state_sync on run start/finish and recomputed live by GET /state. Empty list when no run is active or on a client with no registry (Rich/Textual against a non-agent engine). */
    backgroundAgents: BackgroundAgentSummary[];
}
