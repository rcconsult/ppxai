/**
 * Element types for the container fields of AppState.
 *
 * The canonical schema (`ppxai/engine/app_state_schema.json`) is
 * language-neutral: Python, the web client and this extension all read the
 * same file, so it declares `array` / `object` and never a TypeScript type
 * name. These interfaces are the TypeScript-side refinement of those three
 * containers, and the generator's `TYPE_REFINEMENTS` map
 * (`scripts/sync-schema.js`) is what binds each one to its field.
 *
 * This file is HAND-WRITTEN and is the only hand-written part of the
 * AppState type layer. Adding a field to the canonical schema needs no
 * edit here — only a change to an entry's *element* shape does, and that
 * shape is owned by the Python projection named in each doc comment.
 *
 * No `vscode` import, deliberately: `appState.ts` and the schema guard
 * must stay drivable under plain Node by the behavioural fences.
 */

/**
 * One active agent-run summary mirrored into AppState.background_agents
 * (v1.19.0 Inc 9). Matches the server's
 * `AgentRunRegistry.active_summary()` projection — badge fields only,
 * never result/error/events.
 */
export interface BackgroundAgentSummary {
    run_id: string;
    status: string;
    task: string;
    owner: string | null;
}

/**
 * A single agent-iteration heartbeat snapshot pushed from the engine
 * (P0 v1.18.0). Mirrors `ppxai/engine/types.py::AgentBeatState.as_event_data()`.
 * All fields are optional on the wire because an empty-object payload
 * `{}` is the engine's signal that the agent loop has ended — which is
 * why the field's generated type is a union with `Record<string, never>`.
 */
export interface AgentBeatSnapshot {
    iteration: number;
    beat: number;
    tool: string;
    ok: boolean;
    failures: number;
    elapsed_s: number;
}

/**
 * A single multimodal attachment entry in context_attachments.
 * Matches the Python dict schema from EngineClient._refresh_context_attachments.
 */
export interface ContextAttachment {
    name: string;
    kind: string;        // "image" | "text" | "pdf" | "file"
    media_type: string;  // e.g. "image/png", "" if unknown
    turn_index: number;  // index into session.messages
    file_id: string;     // SessionFileStore identifier, "" for legacy
}
