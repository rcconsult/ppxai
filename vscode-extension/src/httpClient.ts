/**
 * HTTP Client for ppxai-server
 *
 * Communicates with the ppxai HTTP server using REST + SSE for streaming.
 * Provides a compatible interface with PythonBackend for easy migration.
 */

import * as crypto from 'crypto';
import * as vscode from 'vscode';

// === Types matching PythonBackend interface ===

// === Consent Request Types ===

export interface FileConsentRequest {
    file_path: string;
    operation?: 'edit' | 'create' | 'delete';
    tool_name?: string;
}

export interface ShellConsentRequest {
    type: 'shell';
    command: string;
    working_dir?: string;
    risk_level?: 'safe' | 'dangerous' | 'never' | 'unknown';
    tool_name?: string;
}

export type ConsentRequest = FileConsentRequest | ShellConsentRequest;

// v1.14.2: Added 'terminal' option to run command in VSCode terminal
export type ConsentResponse = 'y' | 'n' | 'always' | 'never' | 'terminal';

// === Stream Event Types ===

export interface EventMetadata {
    file_path?: string;
    operation?: string;
    tool_name?: string;
    [key: string]: unknown;
}

export interface StreamEvent {
    type: 'thinking' | 'started' | 'reasoning_chunk' | 'chunk' | 'done' | 'error' | 'warning' | 'tool_call' | 'tool_result' | 'context_injected' | 'display_file' | 'consent_request' | 'status' | 'agent_iteration' | 'agent_complete' | 'agent_max_iterations' | 'working_dir_changed' | 'tool_group_start' | 'tool_group_end' | 'state_sync';
    content: string;
    metadata?: EventMetadata;
}

export interface ProviderInfo {
    id: string;
    name: string;
    has_api_key: boolean;
    default_model?: string;
    capabilities?: {
        web_search: boolean;
        citations: boolean;
        streaming: boolean;
    };
}

export interface ModelInfo {
    id: string;
    name: string;
    description: string;
}

export interface ToolInfo {
    name: string;
    description: string;
    parameters?: Record<string, { description?: string; required?: boolean }>;
}

/**
 * Response shape of POST /files/read (ppxai/server/routes/files.py::read_file).
 *
 * `type` is the discriminator. CRITICAL: `content` is UTF-8 text ONLY when
 * type === 'text'; for 'image' | 'pdf' | 'office_spreadsheet' it is BASE64.
 * Branch on `type` before treating `content` as editable text — writing
 * base64 into a text buffer corrupts the file. Office presentations / Word
 * docs are NOT returned here (server replies 400 + a hint); they go through
 * GET /files/preview instead.
 */
export interface ReadFileResponse {
    filename: string;
    path: string;
    type: 'text' | 'image' | 'pdf' | 'office_spreadsheet';
    content: string;
    size: number;
    mime_type?: string;  // present for binary types
    lines?: number;      // present only for type === 'text'
}

export interface EngineStatus {
    provider: string;
    model: string;
    tools_enabled: boolean;
    tools_verbose?: boolean;
    agent_mode?: boolean;
    auto_route?: boolean;
    working_dir?: string;
    session_name?: string;
    debug_log?: boolean;
    tool_count?: number;
    has_api_key?: boolean;
    message_count?: number;
    auto_inject_context?: boolean;
}

// v1.18.1 Wire envelope returned by POST /command/<name>.
//   `result`        — CommandResult.to_dict() (rendered payload)
//   `side_effects`  — UI directives orthogonal to the payload
//                     (open editor, spawn terminal, etc.)
//   `events`        — drained engine side-channel events
//                     (state_sync, working_dir_changed, etc.)
//                     for state-sync determinism Phase B
//   `version`       — envelope schema version (currently 1)
//
// `result` is loosely typed because it ranges across all
// CommandResult subtypes — TableResult, MarkdownResult, FileViewResult,
// etc. — and the renderer pattern-matches on `result.type`.
export interface CommandResultPayload {
    type: string;
    status: string;
    message: string;
    metadata?: Record<string, unknown>;
    columns?: string[];
    rows?: string[][];
    pairs?: Record<string, string>;
    details?: Record<string, unknown>;
    suggestions?: string[];
    error_details?: string | null;
    content?: string;
    filepath?: string;
    items?: Array<Record<string, unknown>>;
    root?: Record<string, unknown>;
    [key: string]: unknown;
}

export interface SideEffectEntry {
    kind: string;
    [key: string]: unknown;
}

export interface SsePiggybackEvent {
    type: string;
    data?: Record<string, unknown>;
    metadata?: Record<string, unknown>;
}

export interface CommandEnvelope {
    ok: boolean;
    result: CommandResultPayload;
    side_effects: SideEffectEntry[];
    events?: SsePiggybackEvent[];
    version: number;
}

// Multimodal content part (OpenAI format). Text parts carry `text`, image
// parts carry `image_url.url` (usually a data: URI), file parts carry
// `name` / `filename`, and the R5 (v1.17.6) `uploaded_file` type carries
// structured metadata (name, media_type, file_id, summary, extra) for
// PDFs / Office / large-CSV attachments. Unknown types are tolerated
// and surface as placeholders.
export interface ContentBlock {
    type: string;
    text?: string;
    image_url?: { url: string };
    name?: string;
    filename?: string;
    media_type?: string;
    file_id?: string;
    summary?: string;
    extra?: { [key: string]: string };
}

export type MessageContent = string | ContentBlock[];

export interface Message {
    role: 'user' | 'assistant' | 'system';
    content: MessageContent;
}

/**
 * Flatten Message.content (string | ContentBlock[]) to plain display text.
 * Mirrors Message.text_content() in the Python engine. Image / file parts
 * become [Image: name] / [File: name] placeholders.
 */
export function textContent(content: MessageContent | undefined | null): string {
    if (content == null) return '';
    if (typeof content === 'string') return content;
    if (!Array.isArray(content)) return String(content);
    const parts: string[] = [];
    for (const block of content) {
        if (!block || typeof block !== 'object') continue;
        if (block.type === 'text') {
            parts.push(block.text || '');
        } else if (block.type === 'image_url') {
            parts.push(`[Image: ${block.name || 'image'}]`);
        } else if (block.type === 'input_file' || block.type === 'file') {
            parts.push(`[File: ${block.name || block.filename || 'file'}]`);
        } else if (block.type === 'uploaded_file') {
            // R5 (v1.17.6): PDFs / Office / large CSVs as first-class blocks.
            const name = block.name || 'file';
            const media = block.media_type || '';
            parts.push(media ? `[Attached: ${name} (${media})]` : `[Attached: ${name}]`);
        } else {
            parts.push(`[${block.type || 'part'}]`);
        }
    }
    return parts.join('\n');
}

export interface SessionInfo {
    name: string;
    created_at: string;
    saved_at?: string;  // When session was last saved
    provider: string;
    model: string;
    message_count: number;
}

type StreamCallback = (event: StreamEvent) => void;

/**
 * HTTP Client for ppxai-server communication
 *
 * Provides the same interface as PythonBackend for easy migration.
 * v1.14.0: Added session isolation via X-Session-Id header.
 */
export class HttpClient {
    private baseUrl: string;
    private conversationHistory: Message[] = [];
    private outputChannel: vscode.OutputChannel;
    private _ready: boolean = false;
    private currentAbortController: AbortController | null = null;
    // v1.12.0: Track verbose mode for tool output display
    private _toolsVerbose: boolean = false;
    // v1.14.0: Session ID for server-side session isolation
    private _sessionId: string;
    // Item 40: bearer token for the /v1/* API. undefined = none attached.
    private _apiToken: string | undefined;

    constructor(baseUrl: string = 'http://127.0.0.1:54320', sessionId?: string) {
        this.baseUrl = baseUrl;
        // v1.14.0: Generate unique session ID for this client instance
        this._sessionId = sessionId || `vscode-${crypto.randomUUID()}`;
        this.outputChannel = vscode.window.createOutputChannel('ppxai HTTP');
        this.outputChannel.appendLine(`[Session] ID: ${this._sessionId}`);
    }

    /**
     * Get session ID (v1.14.0)
     */
    get sessionId(): string {
        return this._sessionId;
    }

    /**
     * Get headers with session ID (v1.14.0)
     */
    private getHeaders(contentType: boolean = false): Record<string, string> {
        const headers: Record<string, string> = {
            'X-Session-Id': this._sessionId
        };
        if (contentType) {
            headers['Content-Type'] = 'application/json';
        }
        return headers;
    }

    /**
     * Set (or clear, with undefined/'') the bearer attached to /v1/* calls.
     *
     * Item 40: `/v1/agent/*` + `/v1/tokens` stay bearer-protected even from
     * loopback (server auth Inc 8b). Sourced from VSCode SecretStorage via
     * the `ppxai.setApiToken` command — never from settings.json (secrets
     * must not sync or land in dotfiles).
     */
    setApiToken(token: string | undefined): void {
        this._apiToken = token || undefined;
    }

    /** The bearer currently attached to /v1 calls (undefined = none). */
    get apiToken(): string | undefined {
        return this._apiToken;
    }

    /**
     * Headers for the protected /v1 surface: session headers + bearer.
     * Kept SEPARATE from getHeaders(): the server validates any presented
     * bearer even on loopback-exempt UI routes, so a stale token attached
     * everywhere would 401 the whole extension instead of just /v1 calls.
     */
    private v1Headers(contentType: boolean = false): Record<string, string> {
        const headers = this.getHeaders(contentType);
        if (this._apiToken) {
            headers['Authorization'] = `Bearer ${this._apiToken}`;
        }
        return headers;
    }

    /**
     * Get current verbose mode setting (v1.12.0)
     */
    get toolsVerbose(): boolean {
        return this._toolsVerbose;
    }

    /**
     * Get the base URL (v1.13.1)
     */
    getBaseUrl(): string {
        return this.baseUrl;
    }

    /**
     * Check if server is available and mark as ready
     */
    async start(): Promise<boolean> {
        try {
            const available = await this.isAvailable();
            if (available) {
                this._ready = true;
                this.outputChannel.appendLine(`Connected to ppxai-server at ${this.baseUrl}`);
                return true;
            }
            this.outputChannel.appendLine(`ppxai-server not available at ${this.baseUrl}`);
            return false;
        } catch (error) {
            this.outputChannel.appendLine(`Failed to connect: ${error}`);
            return false;
        }
    }

    /**
     * Stop client (no-op for HTTP, kept for interface compatibility)
     */
    stop(): void {
        this._ready = false;
    }

    /**
     * Check if client is ready
     */
    isRunning(): boolean {
        return this._ready;
    }

    /**
     * Check if server is available
     */
    async isAvailable(): Promise<boolean> {
        try {
            const response = await fetch(`${this.baseUrl}/health`, {
                method: 'GET',
                signal: AbortSignal.timeout(2000)
            });
            return response.ok;
        } catch {
            return false;
        }
    }

    /**
     * Get server health status
     */
    async getHealth(): Promise<{ status: string; version: string; engine: boolean }> {
        const response = await fetch(`${this.baseUrl}/health`);
        if (!response.ok) {
            throw new Error(`Health check failed: ${response.statusText}`);
        }
        return response.json() as Promise<{ status: string; version: string; engine: boolean }>;
    }

    /**
     * U4 (ADR 0011): GET /config/execution — the execution.collect mode
     * the collect UX renders from (auto | yes | no).
     */
    async configExecution(): Promise<{ collect: string }> {
        const response = await fetch(`${this.baseUrl}/config/execution`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to read execution config: ${response.statusText}`);
        }
        return response.json() as Promise<{ collect: string }>;
    }

    /**
     * U4 (ADR 0011): POST /sessions/merge-run-result — plain-merge a run's
     * result text into the active session (the model sees it next turn).
     */
    async mergeRunResult(runId: string): Promise<{ merged: boolean; chars: number }> {
        const response = await fetch(`${this.baseUrl}/sessions/merge-run-result`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ run_id: runId })
        });
        if (!response.ok) {
            let detail = response.statusText;
            try {
                const body = await response.json() as any;
                if (body?.detail) { detail = body.detail; }
            } catch { /* keep statusText */ }
            throw new Error(detail);
        }
        return response.json() as Promise<{ merged: boolean; chars: number }>;
    }

    /**
     * Reload configuration from file without restarting server
     */
    async reloadConfig(): Promise<{ success: boolean; message: string; config_path: string | null }> {
        const response = await fetch(`${this.baseUrl}/config/reload`, {
            method: 'POST',
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to reload config: ${response.statusText}`);
        }
        return response.json() as Promise<{ success: boolean; message: string; config_path: string | null }>;
    }

    /**
     * Get current engine status
     */
    async getStatus(): Promise<EngineStatus> {
        const response = await fetch(`${this.baseUrl}/status`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Status check failed: ${response.statusText}`);
        }
        const data = await response.json() as EngineStatus;
        return {
            provider: data.provider,
            model: data.model,
            tools_enabled: data.tools_enabled,
            tools_verbose: data.tools_verbose || false,
            agent_mode: data.agent_mode || false,
            auto_route: data.auto_route || false,
            working_dir: data.working_dir || '',
            session_name: data.session_name || '',
            debug_log: data.debug_log || false,
            auto_inject_context: data.auto_inject_context,
        };
    }

    /**
     * v1.18.0 Phase 2: snapshot of all SSE-synced AppState fields for
     * reconnect catch-up.
     *
     * Returns the current values of every field the engine pushes via
     * `state_sync` events, shaped exactly like an accumulated payload
     * from the SSE stream. Feed straight through `AppState.updateFromPython()`
     * to re-synchronise after a disconnect without re-deriving which
     * fields changed during the gap.
     */
    async fetchState(): Promise<Record<string, any>> {
        const response = await fetch(`${this.baseUrl}/state`, {
            headers: this.getHeaders(),
        });
        if (!response.ok) {
            throw new Error(`State fetch failed: ${response.statusText}`);
        }
        return response.json() as Promise<Record<string, any>>;
    }

    /**
     * Get available providers
     */
    async getProviders(): Promise<ProviderInfo[]> {
        const response = await fetch(`${this.baseUrl}/providers`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to get providers: ${response.statusText}`);
        }
        const data = await response.json() as { providers: ProviderInfo[] };
        return data.providers;
    }

    /**
     * Set active provider.
     * Returns the number of context messages cleared (0 if none).
     */
    async setProvider(providerId: string, model?: string): Promise<{ ok: boolean; contextReset: number }> {
        const response = await fetch(`${this.baseUrl}/providers`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ provider: providerId, model })
        });
        if (!response.ok) {
            return { ok: false, contextReset: 0 };
        }
        const data = await response.json() as { provider: string; model: string; context_reset?: number };
        return { ok: true, contextReset: data.context_reset ?? 0 };
    }

    /**
     * Get available models for current provider
     */
    async getModels(): Promise<ModelInfo[]> {
        const response = await fetch(`${this.baseUrl}/models`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to get models: ${response.statusText}`);
        }
        const data = await response.json() as { models: ModelInfo[] };
        return data.models;
    }

    /**
     * Set active model.
     * Returns the number of context messages cleared (0 if none).
     */
    async setModel(modelId: string): Promise<{ ok: boolean; contextReset: number }> {
        const response = await fetch(`${this.baseUrl}/models`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ model: modelId })
        });
        if (!response.ok) {
            return { ok: false, contextReset: 0 };
        }
        const data = await response.json() as { model: string; provider: string; context_reset?: number };
        return { ok: true, contextReset: data.context_reset ?? 0 };
    }

    /**
     * Get tools list
     */
    async listTools(): Promise<ToolInfo[]> {
        const response = await fetch(`${this.baseUrl}/tools`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to get tools: ${response.statusText}`);
        }
        const data = await response.json() as { tools: ToolInfo[]; enabled: boolean };
        return data.tools;
    }

    /**
     * Get tools status
     */
    async getToolsStatus(): Promise<{ enabled: boolean; tool_count: number; max_iterations: number; consent_mode: string; verbose: boolean }> {
        const response = await fetch(`${this.baseUrl}/tools`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to get tools: ${response.statusText}`);
        }
        const data = await response.json() as {
            tools: ToolInfo[];
            enabled: boolean;
            max_iterations?: number;
            consent_mode?: string;
            verbose?: boolean;  // v1.12.0
        };
        // v1.12.0: Sync verbose setting from server
        this._toolsVerbose = data.verbose || false;
        return {
            enabled: data.enabled,
            tool_count: data.tools.length,
            max_iterations: data.max_iterations || 15,
            consent_mode: data.consent_mode || 'default',
            verbose: data.verbose || false  // v1.12.0
        };
    }

    /**
     * Enable tools
     */
    async enableTools(): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/tools`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ enabled: true })
        });
        return response.ok;
    }

    /**
     * Disable tools
     */
    async disableTools(): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/tools`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ enabled: false })
        });
        return response.ok;
    }

    /**
     * Set tool configuration (e.g., max_iterations)
     */
    async setToolConfig(setting: string, value: any): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/tools/config`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ setting, value: String(value) })
        });
        // v1.12.0: Track verbose setting locally
        if (response.ok && setting === 'verbose') {
            this._toolsVerbose = ['on', 'true', '1', 'yes'].includes(String(value).toLowerCase());
        }
        return response.ok;
    }

    /**
     * Get working directory
     */
    async getWorkingDir(): Promise<string> {
        try {
            const response = await fetch(`${this.baseUrl}/context/working_dir`, {
                headers: this.getHeaders()
            });
            if (!response.ok) {
                return process.cwd();
            }
            const data = await response.json() as { path: string };
            return data.path;
        } catch {
            return process.cwd();
        }
    }

    /**
     * Set working directory for file path resolution
     */
    async setWorkingDir(path: string): Promise<{ path: string; success: boolean; error?: string }> {
        try {
            const response = await fetch(`${this.baseUrl}/context/working_dir`, {
                method: 'POST',
                headers: this.getHeaders(true),
                body: JSON.stringify({ path })
            });
            if (!response.ok) {
                const error = await response.json() as { detail?: string };
                return { path, success: false, error: error.detail || 'Unknown error' };
            }
            const data = await response.json() as { path: string; success: boolean };
            return data;
        } catch (e) {
            return { path, success: false, error: String(e) };
        }
    }

    /**
     * List directory contents (v1.16.0)
     */
    async listFiles(path?: string, showHidden?: boolean): Promise<{ files: any[]; path: string }> {
        const params = new URLSearchParams();
        if (path) { params.set('path', path); }
        if (showHidden) { params.set('a', 'true'); }
        const response = await fetch(`${this.baseUrl}/files/list?${params}`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            const err = await response.json() as { detail?: string };
            throw new Error(err.detail || 'Failed to list directory');
        }
        return await response.json() as { files: any[]; path: string };
    }

    /**
     * Get directory tree (v1.16.0)
     */
    async getFileTree(path?: string, depth?: number): Promise<{ tree: any; path: string; stats: { dirs: number; files: number } }> {
        const params = new URLSearchParams();
        if (path) { params.set('path', path); }
        if (depth != null) { params.set('depth', String(depth)); }
        const response = await fetch(`${this.baseUrl}/files/tree?${params}`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            const err = await response.json() as { detail?: string };
            throw new Error(err.detail || 'Failed to get directory tree');
        }
        return await response.json() as { tree: any; path: string; stats: { dirs: number; files: number } };
    }

    /**
     * Enable or disable automatic context injection
     */
    async setAutoInject(enabled: boolean): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/context/auto_inject`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ enabled })
        });
        return response.ok;
    }

    /**
     * Get auto-inject context status
     */
    async getAutoInject(): Promise<boolean> {
        try {
            const response = await fetch(`${this.baseUrl}/context/auto_inject`, {
                headers: this.getHeaders()
            });
            if (!response.ok) {
                return true; // Default to enabled
            }
            const data = await response.json() as { enabled: boolean };
            return data.enabled;
        } catch {
            return true; // Default to enabled
        }
    }

    /**
     * Get context usage information (v1.13.9)
     */
    async getContextInfo(): Promise<{
        estimated_tokens: number;
        context_limit: number;
        usage_percent: number;
        injected_contexts: Array<{ source: string; size: number; truncated: boolean }>;
        injected_tokens: number;
        message_count: number;
        total_chars: number;
        provider: string;
        model: string;
    }> {
        const response = await fetch(`${this.baseUrl}/context/info`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to get context info: ${response.statusText}`);
        }
        return response.json() as Promise<{
            estimated_tokens: number;
            context_limit: number;
            usage_percent: number;
            injected_contexts: Array<{ source: string; size: number; truncated: boolean }>;
            injected_tokens: number;
            message_count: number;
            total_chars: number;
            provider: string;
            model: string;
        }>;
    }

    /**
     * Clear injected file contents from context (v1.13.9)
     */
    async clearContextInjections(): Promise<{ removed_count: number; success: boolean }> {
        const response = await fetch(`${this.baseUrl}/context/clear`, {
            method: 'POST',
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to clear context: ${response.statusText}`);
        }
        return response.json() as Promise<{ removed_count: number; success: boolean }>;
    }

    /**
     * Get active bootstrap hints for current provider/model (v1.14.0)
     */
    async getActiveHints(): Promise<{
        loaded: boolean;
        source: string;
        provider: string;
        model: string;
        provider_hints: Array<[string, string]>;
        model_hints: Array<[string, string]>;
        inherited_local: boolean;
        matched_patterns: string[];
        all_provider_keys: string[];
        all_model_patterns: string[];
    }> {
        const response = await fetch(`${this.baseUrl}/context/hints`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to get hints: ${response.statusText}`);
        }
        return response.json() as Promise<{
            loaded: boolean;
            source: string;
            provider: string;
            model: string;
            provider_hints: Array<[string, string]>;
            model_hints: Array<[string, string]>;
            inherited_local: boolean;
            matched_patterns: string[];
            all_provider_keys: string[];
            all_model_patterns: string[];
        }>;
    }

    /**
     * Reload bootstrap context from disk (v1.14.1)
     *
     * Reloads AGENTS.md/CLAUDE.md bootstrap context file from working directory.
     */
    async reloadBootstrapContext(): Promise<{
        success: boolean;
        source: string | null;
        loaded: boolean;
    }> {
        const response = await fetch(`${this.baseUrl}/context/reload`, {
            method: 'POST',
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to reload context: ${response.statusText}`);
        }
        return response.json() as Promise<{
            success: boolean;
            source: string | null;
            loaded: boolean;
        }>;
    }

    /**
     * Get bootstrap context status with scoped sources (v1.14.2)
     *
     * Returns detailed information about loaded bootstrap files including
     * their scopes (global, project, subdir).
     */
    async getBootstrapStatus(): Promise<{
        loaded: boolean;
        sources: Array<{ path: string; scope: string; size: number }>;
        source_paths: string[];
        char_count: number;
        has_hints: boolean;
        provider_hints: string[];
        model_hints: string[];
        total_size: number;
    }> {
        const response = await fetch(`${this.baseUrl}/context/bootstrap`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to get bootstrap status: ${response.statusText}`);
        }
        return response.json() as Promise<{
            loaded: boolean;
            sources: Array<{ path: string; scope: string; size: number }>;
            source_paths: string[];
            char_count: number;
            has_hints: boolean;
            provider_hints: string[];
            model_hints: string[];
            total_size: number;
        }>;
    }

    /**
     * Throw a structured Error from a non-OK response.
     *
     * Keeps `err.message` compatible with the legacy string-matching
     * callers (`err.message.includes('404')`) AND attaches `.status`,
     * `.body`, plus the v1.18.1 cwd-anchor 409 fields
     * (`expected`, `actual`, `events[]`) for callers that want to
     * recover from drift via `ChatViewProvider.handleCwdAnchorMismatch`.
     *
     * Mirrors `ppxai/web/shared/api-client.js::_throwHttpError`.
     */
    private async _throwHttpError(response: Response, fallbackMsg: string): Promise<never> {
        let body: any;
        try { body = await response.json(); }
        catch { body = { detail: response.statusText }; }
        // FastAPI wraps HTTPException bodies in `detail`; the cwd_anchor
        // 409 path packs the structured fields inside that wrapper.
        const detail = (body && typeof body.detail === 'object') ? body.detail : body;
        const messageParts: string[] = [];
        if (typeof detail?.detail === 'string') messageParts.push(detail.detail);
        else if (typeof body?.detail === 'string') messageParts.push(body.detail);
        else messageParts.push(fallbackMsg || `HTTP ${response.status}`);
        const err: any = new Error(messageParts.join(' '));
        err.status = response.status;
        err.body = body;
        if (detail && typeof detail === 'object') {
            err.expected = detail.expected;
            err.actual = detail.actual;
            err.events = detail.events;
        }
        throw err;
    }

    /**
     * Read file contents (v1.18.1 Phase D).
     *
     * Optional `cwdAnchor`: the working_dir the client thinks the
     * relpath was captured against. Server returns 409 if the engine
     * has moved on; httpClient surfaces it as a structured error with
     * `.expected`, `.actual`, `.events` for the recovery helper.
     */
    async readFile(filepath: string, cwdAnchor?: string): Promise<ReadFileResponse> {
        const body: Record<string, unknown> = { path: filepath };
        if (cwdAnchor) body.cwd_anchor = cwdAnchor;
        const response = await fetch(`${this.baseUrl}/files/read`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify(body)
        });
        if (!response.ok) {
            await this._throwHttpError(response, `Failed to read file`);
        }
        // IMPORTANT: branch on `type` before using `content`. For
        // type === 'office_spreadsheet' (and 'image'/'pdf') `content` is
        // BASE64, not UTF-8 text — writing it straight into a text buffer
        // corrupts the file. Only type === 'text' carries editable text
        // (and the `lines` field). See ppxai/server/routes/files.py::read_file.
        return response.json() as Promise<ReadFileResponse>;
    }

    /**
     * Write file contents (v1.14.1)
     *
     * Writes content to a file in the working directory.
     *
     * v1.18.1 Phase D: optional `cwdAnchor` argument enables drift
     * detection — see readFile() for semantics.
     */
    async writeFile(path: string, content: string, cwdAnchor?: string): Promise<{
        path: string;
        success: boolean;
        created: boolean;
        size: number;
    }> {
        const body: Record<string, unknown> = { path, content };
        if (cwdAnchor) body.cwd_anchor = cwdAnchor;
        const response = await fetch(`${this.baseUrl}/files/write`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify(body)
        });
        if (!response.ok) {
            await this._throwHttpError(response, `Failed to write file`);
        }
        return response.json() as Promise<{
            path: string;
            success: boolean;
            created: boolean;
            size: number;
        }>;
    }

    /**
     * Send chat message with SSE streaming
     */
    async chat(
        message: string,
        streamCallback?: StreamCallback,
        files?: Array<{name: string; media_type: string; data: string}>
    ): Promise<string> {
        // Create new AbortController for this request
        this.currentAbortController = new AbortController();

        try {
            // v1.17.4 Phase 6.1: include files array when present.
            // Server ChatRequest accepts files: [{name, media_type, data}]
            // where data is base64. When omitted the body is identical
            // to pre-Phase-6 format for backward compatibility.
            const body: Record<string, any> = { message };
            if (files && files.length > 0) {
                body.files = files;
            }

            const response = await fetch(`${this.baseUrl}/chat`, {
                method: 'POST',
                headers: this.getHeaders(true),
                body: JSON.stringify(body),
                signal: this.currentAbortController.signal
            });

            if (!response.ok) {
                throw new Error(`Chat request failed: ${response.statusText}`);
            }

            if (!response.body) {
                throw new Error('No response body');
            }

            // Track message in local history
            this.conversationHistory.push({ role: 'user', content: message });

            // Notify stream started
            streamCallback?.({ type: 'started', content: '' });

            let fullResponse = '';
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            try {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) {break;}

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || '';

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const event = JSON.parse(line.slice(6));
                                this.outputChannel.appendLine(`[SSE] ${JSON.stringify(event)}`);

                                // Map server events to StreamEvent format
                                const mappedEvent = this.mapServerEvent(event);
                                if (mappedEvent) {
                                    streamCallback?.(mappedEvent);
                                    if (mappedEvent.type === 'chunk') {
                                        fullResponse += mappedEvent.content;
                                    }
                                }

                                if (event.type === 'error') {
                                    throw new Error(event.data);
                                }
                            } catch (e) {
                                if (e instanceof SyntaxError) {
                                    this.outputChannel.appendLine(`Parse warning: ${line}`);
                                } else {
                                    throw e;
                                }
                            }
                        }
                    }
                }
            } finally {
                reader.releaseLock();
            }

            // Notify stream done
            streamCallback?.({ type: 'done', content: fullResponse });

            // Track response in local history
            this.conversationHistory.push({ role: 'assistant', content: fullResponse });

            return fullResponse;
        } catch (error: any) {
            // Handle abort separately from other errors
            if (error.name === 'AbortError') {
                this.outputChannel.appendLine('[Interrupted by user]');
                // Don't send error event - let chatPanel handle silently
                throw new Error('Interrupted by user');
            }
            throw error;
        } finally {
            // Cleanup controller
            this.currentAbortController = null;
        }
    }

    /**
     * Send coding task with SSE streaming
     */
    async codingTask(
        taskType: string,
        content: string,
        language?: string,
        filename?: string,
        streamCallback?: StreamCallback
    ): Promise<string> {
        // Build the message with context
        let message = content;
        if (language) {
            message = `Language: ${language}\n\n${message}`;
        }
        if (filename) {
            message = `File: ${filename}\n\n${message}`;
        }

        // Create new AbortController for this request
        this.currentAbortController = new AbortController();

        try {
            const response = await fetch(`${this.baseUrl}/coding_task`, {
                method: 'POST',
                headers: this.getHeaders(true),
                body: JSON.stringify({ message, task_type: taskType }),
                signal: this.currentAbortController.signal
            });

            if (!response.ok) {
                throw new Error(`Coding task request failed: ${response.statusText}`);
            }

            if (!response.body) {
                throw new Error('No response body');
            }

            // Notify stream started
            streamCallback?.({ type: 'started', content: '' });

            let fullResponse = '';
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            try {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) {break;}

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || '';

                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const event = JSON.parse(line.slice(6));
                                this.outputChannel.appendLine(`[SSE] ${JSON.stringify(event)}`);

                                const mappedEvent = this.mapServerEvent(event);
                                if (mappedEvent) {
                                    streamCallback?.(mappedEvent);
                                    if (mappedEvent.type === 'chunk') {
                                        fullResponse += mappedEvent.content;
                                    }
                                }

                                if (event.type === 'error') {
                                    throw new Error(event.data);
                                }
                            } catch (e) {
                                if (e instanceof SyntaxError) {
                                    this.outputChannel.appendLine(`Parse warning: ${line}`);
                                } else {
                                    throw e;
                                }
                            }
                        }
                    }
                }
            } finally {
                reader.releaseLock();
            }

            // Notify stream done
            streamCallback?.({ type: 'done', content: fullResponse });

            return fullResponse;
        } catch (error: any) {
            // Handle abort separately from other errors
            if (error.name === 'AbortError') {
                this.outputChannel.appendLine('[Interrupted by user]');
                // Don't send error event - let chatPanel handle silently
                throw new Error('Interrupted by user');
            }
            throw error;
        } finally {
            // Cleanup controller
            this.currentAbortController = null;
        }
    }

    /**
     * Interrupt the current streaming request
     */
    async interrupt(): Promise<void> {
        try {
            // Call server interrupt endpoint
            await fetch(`${this.baseUrl}/interrupt`, {
                method: 'POST',
                signal: AbortSignal.timeout(1000)
            });
        } catch (e) {
            // Log but don't fail - abort controller will still work
            this.outputChannel.appendLine(`Interrupt warning: ${e}`);
        }

        // Abort the current fetch request
        if (this.currentAbortController) {
            this.currentAbortController.abort();
            this.currentAbortController = null;
        }
    }

    /**
     * Respond to file edit consent request (Phase 1C: v1.11.0)
     */
    async consent(filePath: string, response: 'y' | 'n' | 'always' | 'never'): Promise<void> {
        try {
            const resp = await fetch(`${this.baseUrl}/consent`, {
                method: 'POST',
                headers: this.getHeaders(true),
                body: JSON.stringify({
                    file_path: filePath,
                    response: response
                }),
                signal: AbortSignal.timeout(5000)
            });

            if (!resp.ok) {
                const error = await resp.text();
                throw new Error(`Consent request failed: ${error}`);
            }

            this.outputChannel.appendLine(`Consent response sent: ${filePath} -> ${response}`);
        } catch (error) {
            this.outputChannel.appendLine(`Consent error: ${error}`);
            throw error;
        }
    }

    /**
     * Respond to shell command consent request (v1.11.2)
     */
    async shellConsent(command: string, workingDir: string, response: 'y' | 'n' | 'always' | 'never'): Promise<void> {
        try {
            const resp = await fetch(`${this.baseUrl}/shell-consent`, {
                method: 'POST',
                headers: this.getHeaders(true),
                body: JSON.stringify({
                    command: command,
                    working_dir: workingDir,
                    response: response
                }),
                signal: AbortSignal.timeout(5000)
            });

            if (!resp.ok) {
                const error = await resp.text();
                throw new Error(`Shell consent request failed: ${error}`);
            }

            this.outputChannel.appendLine(`Shell consent response sent: ${command} -> ${response}`);
        } catch (error) {
            this.outputChannel.appendLine(`Shell consent error: ${error}`);
            throw error;
        }
    }

    /**
     * Map server SSE events to StreamEvent format
     */
    private mapServerEvent(event: { type: string; data: any; metadata?: any }): StreamEvent | null {
        switch (event.type) {
            case 'stream_start':
                return { type: 'started', content: '' };
            case 'reasoning_chunk':
                // v1.13.9: Reasoning tokens from DeepSeek R1, GPT-OSS 120B
                return { type: 'reasoning_chunk', content: event.data || '' };
            case 'stream_chunk':
                return { type: 'chunk', content: event.data || '' };
            case 'stream_end':
                // v1.19.0: preserve metadata (carries {usage}) so the client
                // reads the run's tokens/cost from STREAM_END instead of a
                // redundant GET /usage round-trip.
                return { type: 'done', content: event.data || '', metadata: event.metadata };
            case 'tool_call':
                return { type: 'tool_call', content: JSON.stringify(event.data) };
            case 'tool_result':
                // tool_result data is {tool, result} object - stringify it
                return { type: 'tool_result', content: typeof event.data === 'object' ? JSON.stringify(event.data) : (event.data || '') };
            case 'tool_error':
                // tool_error data is {tool, error} object - extract error message
                const toolErr = event.data as { tool?: string; error?: string } | string;
                const toolErrMsg = typeof toolErr === 'object'
                    ? `Tool error (${toolErr?.tool || 'unknown'}): ${toolErr?.error || JSON.stringify(toolErr)}`
                    : `Tool error: ${toolErr || 'Unknown error'}`;
                return { type: 'error', content: toolErrMsg };
            case 'context_injected':
                // context_injected data is an object - stringify it
                return { type: 'context_injected', content: typeof event.data === 'object' ? JSON.stringify(event.data) : (event.data || '') };
            case 'consent_request':
                // Phase 1C: File edit consent request
                return {
                    type: 'consent_request',
                    content: typeof event.data === 'object' ? JSON.stringify(event.data) : (event.data || ''),
                    metadata: event.metadata
                };
            case 'status':
                // v1.12.0: Checkpoint notifications, agent status messages
                return { type: 'status', content: event.data || '' };
            case 'agent_iteration':
                // v1.12.0: Agent loop iteration progress
                return {
                    type: 'agent_iteration',
                    content: typeof event.data === 'object' ? JSON.stringify(event.data) : (event.data || ''),
                    metadata: event.data
                };
            case 'agent_complete':
                // v1.12.0: Agent task completed successfully
                return {
                    type: 'agent_complete',
                    content: typeof event.data === 'object' ? JSON.stringify(event.data) : (event.data || ''),
                    metadata: event.data
                };
            case 'agent_max_iterations':
                // v1.12.0: Agent reached max iterations
                return {
                    type: 'agent_max_iterations',
                    content: typeof event.data === 'object' ? JSON.stringify(event.data) : (event.data || ''),
                    metadata: event.data
                };
            case 'working_dir_changed':
                // v1.13.2: Working directory changed by tool
                return {
                    type: 'working_dir_changed',
                    content: event.data?.path || '',
                    metadata: event.data
                };
            case 'display_file':
                // v1.15.2: AI tool requests to display a file
                return {
                    type: 'display_file',
                    content: '',
                    metadata: event.data  // Contains {filepath: string}
                };
            case 'tool_group_start':
                // v1.16.0: Start of a tool iteration group
                return {
                    type: 'tool_group_start',
                    content: typeof event.data === 'object' ? JSON.stringify(event.data) : (event.data || '')
                };
            case 'tool_group_end':
                // v1.16.0: End of a tool iteration group
                return {
                    type: 'tool_group_end',
                    content: typeof event.data === 'object' ? JSON.stringify(event.data) : (event.data || '')
                };
            case 'error':
                return { type: 'error', content: event.data || 'Unknown error' };
            case 'state_sync':
                // v1.17.1: Engine pushed AppState field change
                return {
                    type: 'state_sync',
                    content: typeof event.data === 'object' ? JSON.stringify(event.data) : (event.data || '')
                };
            case 'info':
                return { type: 'thinking', content: event.data || '' };
            default:
                return null;
        }
    }

    /**
     * Get conversation history
     */
    async getHistory(): Promise<Message[]> {
        return [...this.conversationHistory];
    }

    /**
     * Drop the client-side conversation mirror.
     *
     * v1.19.1: this no longer calls `POST /sessions/clear`. Clearing a
     * session is command logic and goes through the command envelope
     * (`POST /command/clear` → `CommandFactory` → `handle_clear`) — see
     * `ChatViewProvider.clearConversation`, the single clear path. What
     * remains here is the local mirror reset, which no server event can do:
     * `conversationHistory` is written by this client during streaming
     * (`getHistory` reads it), so it must be dropped alongside the
     * server-side clear or it goes stale.
     */
    resetHistoryMirror(): void {
        this.conversationHistory = [];
    }

    /**
     * Save current session
     */
    async saveSession(name?: string): Promise<string> {
        const response = await fetch(`${this.baseUrl}/sessions/save`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: name ? JSON.stringify({ name }) : '{}'
        });
        if (!response.ok) {
            throw new Error(`Failed to save session: ${response.statusText}`);
        }
        const data = await response.json() as { name: string };
        return data.name;
    }

    /**
     * Export last answer to markdown file
     */
    async exportAnswer(filename?: string): Promise<string> {
        const response = await fetch(`${this.baseUrl}/export`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: filename ? JSON.stringify({ filename }) : '{}'
        });
        if (!response.ok) {
            const error = await response.text();
            throw new Error(error || `Failed to export answer: ${response.statusText}`);
        }
        const data = await response.json() as { filepath: string };
        return data.filepath;
    }

    /**
     * Get saved sessions
     */
    async getSessions(): Promise<SessionInfo[]> {
        const response = await fetch(`${this.baseUrl}/sessions`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to get sessions: ${response.statusText}`);
        }
        const data = await response.json() as { sessions: SessionInfo[] };
        return data.sessions;
    }

    /**
     * Load a saved session
     */
    async loadSession(sessionName: string): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/sessions/load/${encodeURIComponent(sessionName)}`, {
            method: 'POST',
            headers: this.getHeaders()
        });
        return response.ok;
    }

    /**
     * Get usage statistics (v1.12.2: includes per-model breakdown)
     */
    async getUsage(): Promise<{
        total_tokens: number;
        prompt_tokens: number;
        completion_tokens: number;
        estimated_cost: number;
        by_model?: Record<string, {
            total_tokens: number;
            prompt_tokens: number;
            completion_tokens: number;
            estimated_cost: number;
        }>;
        display_mode?: string;
    }> {
        const response = await fetch(`${this.baseUrl}/usage`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to get usage: ${response.statusText}`);
        }
        return response.json() as Promise<{
            total_tokens: number;
            prompt_tokens: number;
            completion_tokens: number;
            estimated_cost: number;
            by_model?: Record<string, {
                total_tokens: number;
                prompt_tokens: number;
                completion_tokens: number;
                estimated_cost: number;
            }>;
            display_mode?: string;
        }>;
    }

    /**
     * Set usage display mode for status line (v1.12.2)
     * @param mode - "session", "provider", "model", or "off"
     */
    async setUsageDisplayMode(mode: string): Promise<{ mode: string; success: boolean }> {
        const response = await fetch(`${this.baseUrl}/usage/display`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ mode })
        });
        if (!response.ok) {
            throw new Error(`Failed to set usage display mode: ${response.statusText}`);
        }
        return response.json() as Promise<{ mode: string; success: boolean }>;
    }

    /**
     * Get current usage display mode (v1.12.2)
     */
    async getUsageDisplayMode(): Promise<{ mode: string }> {
        const response = await fetch(`${this.baseUrl}/usage/display`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to get usage display mode: ${response.statusText}`);
        }
        return response.json() as Promise<{ mode: string }>;
    }

    /**
     * Reset all usage statistics to zero (v1.12.2)
     */
    async resetUsage(): Promise<{ success: boolean }> {
        const response = await fetch(`${this.baseUrl}/usage/reset`, {
            method: 'POST',
            headers: this.getHeaders(true)
        });
        if (!response.ok) {
            throw new Error(`Failed to reset usage: ${response.statusText}`);
        }
        return response.json() as Promise<{ success: boolean }>;
    }

    /**
     * Get aggregated usage report for a time period (v1.12.3)
     *
     * @param period - One of "24h", "week", "month", "year", "all"
     */
    async getUsageReport(period: string): Promise<{
        period: string;
        start_date: string | null;
        end_date: string;
        total_tokens: number;
        total_cost: number;
        session_count: number;
        by_provider: Record<string, {
            prompt_tokens: number;
            completion_tokens: number;
            total_tokens: number;
            estimated_cost: number;
            session_count: number;
        }>;
        by_model: Record<string, {
            prompt_tokens: number;
            completion_tokens: number;
            total_tokens: number;
            estimated_cost: number;
            session_count: number;
        }>;
        sessions: Array<{
            session_id: string;
            started_at: string;
            ended_at: string;
            total_tokens: number;
            total_cost: number;
            message_count: number;
        }>;
    }> {
        const response = await fetch(`${this.baseUrl}/usage/report?period=${encodeURIComponent(period)}`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to get usage report: ${response.statusText}`);
        }
        return response.json() as Promise<{
            period: string;
            start_date: string | null;
            end_date: string;
            total_tokens: number;
            total_cost: number;
            session_count: number;
            by_provider: Record<string, {
                prompt_tokens: number;
                completion_tokens: number;
                total_tokens: number;
                estimated_cost: number;
                session_count: number;
            }>;
            by_model: Record<string, {
                prompt_tokens: number;
                completion_tokens: number;
                total_tokens: number;
                estimated_cost: number;
                session_count: number;
            }>;
            sessions: Array<{
                session_id: string;
                started_at: string;
                ended_at: string;
                total_tokens: number;
                total_cost: number;
                message_count: number;
            }>;
        }>;
    }

    // === Generic Command Execution (v1.16.1) ===

    /**
     * Execute a slash command server-side via CommandFactory.
     *
     * Returns the CommandResult as JSON. The server dispatches through the
     * shared command handler — same code path as TUI clients.
     *
     * @param name - Command name without slash (e.g., "usage", "tools")
     * @param args - Command arguments string
     */
    async executeCommand(name: string, args: string = ''): Promise<CommandEnvelope> {
        const response = await fetch(`${this.baseUrl}/command/${encodeURIComponent(name)}`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ args })
        });
        if (!response.ok) {
            // 404 is "unknown command" — surface it specifically so
            // the dispatcher can show a friendly error instead of a
            // generic failure.
            const err: any = new Error(
                response.status === 404
                    ? `Unknown command: /${name}`
                    : `Command /${name} failed: ${response.statusText}`
            );
            err.status = response.status;
            throw err;
        }
        return response.json() as Promise<CommandEnvelope>;
    }

    /**
     * Get debug log status (v1.11.2)
     */
    async getDebugLogStatus(): Promise<{ enabled: boolean; log_file: string | null }> {
        const response = await fetch(`${this.baseUrl}/debug-log`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to get debug log status: ${response.statusText}`);
        }
        return response.json() as Promise<{ enabled: boolean; log_file: string | null }>;
    }

    /**
     * Enable or disable debug logging (v1.11.2)
     */
    async setDebugLog(enabled: boolean): Promise<{ enabled: boolean; log_file: string | null }> {
        this.outputChannel.appendLine(`[Debug Log] ${enabled ? 'Enabling' : 'Disabling'} server debug logging...`);

        const response = await fetch(`${this.baseUrl}/debug-log`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ enabled })
        });
        if (!response.ok) {
            throw new Error(`Failed to set debug log: ${response.statusText}`);
        }

        const result = await response.json() as { enabled: boolean; log_file: string | null };
        this.outputChannel.appendLine(`[Debug Log] Server debug logging ${result.enabled ? 'enabled' : 'disabled'}`);
        if (result.log_file) {
            this.outputChannel.appendLine(`[Debug Log] Log file: ${result.log_file}`);
        }

        return result;
    }

    // === Agent run registry — /v1/agent/* (v1.19.x build plan T8a) ========
    //
    // The tool-capable /task tier's wire surface (ADR 0003 Stage 2). These
    // mirror the web client's calls exactly; taskController.ts consumes them
    // through its TaskBackend interface. Error detail matters here — the
    // tier's guardrail 4xx bodies (403 tier-off hint, 400 shell-grant, 409
    // respond/ack/resume refusal reasons) are surfaced VERBATIM so the user
    // sees WHY, not just that it failed.

    /** Extract `detail` from a FastAPI error body, else the status text. */
    private async agentError(response: Response, fallback: string): Promise<Error> {
        let detail: string | null = null;
        try {
            const body = await response.json() as { detail?: string };
            if (body && typeof body.detail === 'string') { detail = body.detail; }
        } catch { /* non-JSON error body — keep the fallback */ }
        const err = new Error(detail || `${fallback}: ${response.statusText}`);
        // Surface the HTTP status so callers can special-case auth
        // failures (taskController appends the /token hint on 401).
        (err as Error & { status?: number }).status = response.status;
        return err;
    }

    // Per-request timeout for the agent REST calls. Without it a hung
    // connection stalls the fetch forever — taskController's poll watcher
    // then never increments its failure counter, so its pollMaxFailures
    // give-up tripwire never fires. A timed-out fetch throws (AbortError),
    // which the watcher counts like any other failure. Does NOT apply to
    // the long-lived events stream (agentRunEvents).
    private agentTimeoutMs = 15000;

    /** POST /v1/agent/task — launch a tool-capable, sandboxed run. */
    async agentTask(body: Record<string, any>): Promise<{ run_id: string; status: string }> {
        const response = await fetch(`${this.baseUrl}/v1/agent/task`, {
            method: 'POST',
            headers: this.v1Headers(true),
            body: JSON.stringify(body),
            signal: AbortSignal.timeout(this.agentTimeoutMs)
        });
        if (!response.ok) {
            throw await this.agentError(response, 'Task launch failed');
        }
        return response.json() as Promise<{ run_id: string; status: string }>;
    }

    /**
     * POST /v1/agent/run — launch a one-off `kind=oneshot` run (U3, ADR
     * 0011). The grant is SERVER-config-decided (execution.run.web_search);
     * the body carries only task + optional provider/model intent.
     */
    async agentRunCreate(body: Record<string, any>): Promise<{ run_id: string; status: string }> {
        const response = await fetch(`${this.baseUrl}/v1/agent/run`, {
            method: 'POST',
            headers: this.v1Headers(true),
            body: JSON.stringify(body),
            signal: AbortSignal.timeout(this.agentTimeoutMs)
        });
        if (!response.ok) {
            throw await this.agentError(response, 'Run launch failed');
        }
        return response.json() as Promise<{ run_id: string; status: string }>;
    }

    /**
     * GET /v1/agent/runs[?kind=task|oneshot] — list runs (newest first,
     * owner-scoped). U3: `kind` partitions the listing per command family.
     */
    async agentRuns(kind?: string): Promise<{ runs: any[] }> {
        const url = kind
            ? `${this.baseUrl}/v1/agent/runs?kind=${encodeURIComponent(kind)}`
            : `${this.baseUrl}/v1/agent/runs`;
        const response = await fetch(url, {
            headers: this.v1Headers(),
            signal: AbortSignal.timeout(this.agentTimeoutMs)
        });
        if (!response.ok) {
            throw await this.agentError(response, 'Failed to list agent runs');
        }
        return response.json() as Promise<{ runs: any[] }>;
    }

    /** GET /v1/agent/runs/{id} — one run's meta (incl. waiting/resumable). */
    async agentRun(runId: string): Promise<any> {
        const response = await fetch(`${this.baseUrl}/v1/agent/runs/${encodeURIComponent(runId)}`, {
            headers: this.v1Headers(),
            signal: AbortSignal.timeout(this.agentTimeoutMs)
        });
        if (!response.ok) {
            throw await this.agentError(response, `Failed to fetch run ${runId}`);
        }
        return response.json();
    }

    /**
     * GET /v1/agent/runs/{id}/events?live=1 — async-iterate the parsed
     * `data:` events of a run's live SSE stream (same wire parsing as the
     * web client's _tailEvents). The stream is long-lived by design — no
     * request timeout; the consumer (taskController.runWatch) falls back to
     * meta polling when the stream errors or ends early.
     */
    async *agentRunEvents(runId: string): AsyncGenerator<any, void, unknown> {
        const response = await fetch(
            `${this.baseUrl}/v1/agent/runs/${encodeURIComponent(runId)}/events?live=1`,
            { headers: this.v1Headers() }
        );
        if (!response.ok || !response.body) {
            throw new Error(`stream ${response.status}`);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        try {
            for (;;) {
                const { done, value } = await reader.read();
                if (done) { return; }
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';
                for (const line of lines) {
                    if (!line.startsWith('data: ')) { continue; }
                    try { yield JSON.parse(line.slice(6)); } catch { /* skip bad frame */ }
                }
            }
        } finally {
            void reader.cancel().catch(() => { /* already closed */ });
        }
    }

    /** POST /v1/agent/runs/{id}/cancel — cooperative cancel (Inc 6). */
    async agentRunCancel(runId: string): Promise<any> {
        const response = await fetch(`${this.baseUrl}/v1/agent/runs/${encodeURIComponent(runId)}/cancel`, {
            method: 'POST',
            headers: this.v1Headers(true),
            body: JSON.stringify({}),
            signal: AbortSignal.timeout(this.agentTimeoutMs)
        });
        if (!response.ok) {
            throw await this.agentError(response, `Failed to cancel run ${runId}`);
        }
        return response.json();
    }

    /** POST /v1/agent/runs/{id}/respond — answer a waiting park (T5). */
    async agentRunRespond(runId: string, body: Record<string, any>): Promise<any> {
        const response = await fetch(`${this.baseUrl}/v1/agent/runs/${encodeURIComponent(runId)}/respond`, {
            method: 'POST',
            headers: this.v1Headers(true),
            body: JSON.stringify(body),
            signal: AbortSignal.timeout(this.agentTimeoutMs)
        });
        if (!response.ok) {
            throw await this.agentError(response, `Failed to respond to run ${runId}`);
        }
        return response.json();
    }

    /** POST /v1/agent/runs/{id}/ack — collect a held result (T6). */
    async agentRunAck(runId: string): Promise<any> {
        const response = await fetch(`${this.baseUrl}/v1/agent/runs/${encodeURIComponent(runId)}/ack`, {
            method: 'POST',
            headers: this.v1Headers(true),
            body: JSON.stringify({}),
            signal: AbortSignal.timeout(this.agentTimeoutMs)
        });
        if (!response.ok) {
            throw await this.agentError(response, `Failed to ack run ${runId}`);
        }
        return response.json();
    }

    /** POST /v1/agent/runs/{id}/resume — conditional resume (T7). */
    async agentRunResume(runId: string): Promise<any> {
        const response = await fetch(`${this.baseUrl}/v1/agent/runs/${encodeURIComponent(runId)}/resume`, {
            method: 'POST',
            headers: this.v1Headers(true),
            body: JSON.stringify({}),
            signal: AbortSignal.timeout(this.agentTimeoutMs)
        });
        if (!response.ok) {
            throw await this.agentError(response, `Failed to resume run ${runId}`);
        }
        return response.json();
    }

    // === /v1/tokens (Item 40) =============================================
    // Kept OUTSIDE the agent-registry section on purpose: the parity
    // sentinel (tests/test_vscode_task_controller.py) enforces that every
    // agent call site uses v1Headers, while the mint below is the one
    // documented bare call.

    /**
     * POST /v1/tokens — mint a bearer via the loopback bootstrap
     * (server/auth.py::_is_bootstrap_mint). Deliberately sent WITHOUT the
     * stored bearer (getHeaders, not v1Headers): a stale token would be
     * validated — and rejected — even on the loopback-exempt mint route.
     * Same reason the web client nulls its token before minting.
     */
    async mintApiToken(owner: string): Promise<{ token: string; meta: { token_id: string; owner: string } }> {
        const response = await fetch(`${this.baseUrl}/v1/tokens`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ owner, roles: [] }),
            signal: AbortSignal.timeout(this.agentTimeoutMs)
        });
        if (!response.ok) {
            throw await this.agentError(response, 'Token mint failed');
        }
        return response.json() as Promise<{ token: string; meta: { token_id: string; owner: string } }>;
    }

    // === Agent Mode (v1.11.8) ===

    /**
     * Get agent mode status (v1.11.8, v1.12.0: checkpoint info, v1.12.1: validity check)
     */
    async getAgentStatus(): Promise<{
        agent_mode: boolean;
        tools_enabled: boolean;
        checkpoint?: {
            enabled: boolean;
            backend: 'git' | 'file' | 'none';
            last_checkpoint: string | null;
            is_valid: boolean;  // v1.12.1: Whether checkpoint is still valid
            validity_reason: string;  // v1.12.1: Why checkpoint is valid/invalid
            status_description: string;
        };
    }> {
        const response = await fetch(`${this.baseUrl}/agent/status`, {
            headers: this.getHeaders()
        });
        if (!response.ok) {
            throw new Error(`Failed to get agent status: ${response.statusText}`);
        }
        return response.json() as Promise<{
            agent_mode: boolean;
            tools_enabled: boolean;
            checkpoint?: {
                enabled: boolean;
                backend: 'git' | 'file' | 'none';
                last_checkpoint: string | null;
                is_valid: boolean;
                validity_reason: string;
                status_description: string;
            };
        }>;
    }

    /**
     * Get agent configuration (v1.11.9)
     */
    async getAgentConfig(): Promise<{ max_iterations: number; context_char_limit: number; min_task_words: number }> {
        try {
            const response = await fetch(`${this.baseUrl}/agent/config`, {
                headers: this.getHeaders()
            });
            if (!response.ok) {
                // Return defaults if endpoint not available
                return { max_iterations: 10, context_char_limit: 2000, min_task_words: 3 };
            }
            return response.json() as Promise<{ max_iterations: number; context_char_limit: number; min_task_words: number }>;
        } catch {
            return { max_iterations: 10, context_char_limit: 2000, min_task_words: 3 };
        }
    }

    /**
     * Enable agent mode for autonomous task execution (v1.11.8)
     *
     * Agent mode automatically enables tools if not already enabled.
     */
    async enableAgentMode(): Promise<boolean> {
        this.outputChannel.appendLine('[Agent] Enabling agent mode...');

        const response = await fetch(`${this.baseUrl}/agent/enable`, {
            method: 'POST',
            headers: this.getHeaders(true)
        });

        if (!response.ok) {
            throw new Error(`Failed to enable agent mode: ${response.statusText}`);
        }

        const result = await response.json() as { ok: boolean; agent_mode: boolean; tools_enabled: boolean };
        this.outputChannel.appendLine(`[Agent] Agent mode enabled (tools: ${result.tools_enabled})`);

        return result.agent_mode;
    }

    /**
     * Disable agent mode (v1.11.8)
     */
    async disableAgentMode(): Promise<boolean> {
        this.outputChannel.appendLine('[Agent] Disabling agent mode...');

        const response = await fetch(`${this.baseUrl}/agent/disable`, {
            method: 'POST',
            headers: this.getHeaders(true)
        });

        if (!response.ok) {
            throw new Error(`Failed to disable agent mode: ${response.statusText}`);
        }

        const result = await response.json() as { ok: boolean; agent_mode: boolean };
        this.outputChannel.appendLine('[Agent] Agent mode disabled');

        return !result.agent_mode;  // Return true if successfully disabled
    }

    // === Checkpoints (v1.12.0) ===

    /**
     * Undo last checkpoint (v1.12.0)
     *
     * Reverts all changes from the last agent task.
     * Returns true if successful, false otherwise.
     */
    async undoCheckpoint(): Promise<{ success: boolean; message: string; checkpoint_id?: string }> {
        this.outputChannel.appendLine('[Checkpoint] Undoing last checkpoint...');

        const response = await fetch(`${this.baseUrl}/checkpoint/undo`, {
            method: 'POST',
            headers: this.getHeaders(true)
        });

        if (!response.ok) {
            const error = await response.text();
            throw new Error(`Failed to undo checkpoint: ${error || response.statusText}`);
        }

        const result = await response.json() as { success: boolean; message: string; checkpoint_id?: string };
        this.outputChannel.appendLine(`[Checkpoint] Undo result: ${result.message}`);

        return result;
    }

    /**
     * List recent checkpoints (v1.12.4)
     */
    async listCheckpoints(limit: number = 10): Promise<{
        checkpoints: Array<{ id: string; description: string; timestamp: string }>;
        count: number;
    }> {
        this.outputChannel.appendLine('[Checkpoint] Listing checkpoints...');

        const response = await fetch(`${this.baseUrl}/checkpoint/list?limit=${limit}`, {
            headers: this.getHeaders()
        });

        if (!response.ok) {
            const error = await response.text();
            throw new Error(`Failed to list checkpoints: ${error || response.statusText}`);
        }

        return response.json() as Promise<{
            checkpoints: Array<{ id: string; description: string; timestamp: string }>;
            count: number;
        }>;
    }

    /**
     * Get checkpoint status (v1.12.4)
     */
    async getCheckpointStatus(): Promise<{
        enabled: boolean;
        backend: string;
        last_checkpoint: string | null;
        is_valid: boolean;
        validity_reason: string;
    }> {
        this.outputChannel.appendLine('[Checkpoint] Getting status...');

        const response = await fetch(`${this.baseUrl}/checkpoint/status`, {
            headers: this.getHeaders()
        });

        if (!response.ok) {
            const error = await response.text();
            throw new Error(`Failed to get checkpoint status: ${error || response.statusText}`);
        }

        return response.json() as Promise<{
            enabled: boolean;
            backend: string;
            last_checkpoint: string | null;
            is_valid: boolean;
            validity_reason: string;
        }>;
    }

    /**
     * Set checkpoint backend (v1.12.4)
     */
    async setCheckpointBackend(backend: 'git' | 'file' | 'auto' | 'none'): Promise<{
        success: boolean;
        backend: string;
        enabled: boolean;
    }> {
        this.outputChannel.appendLine(`[Checkpoint] Setting backend to: ${backend}`);

        const response = await fetch(`${this.baseUrl}/checkpoint/backend`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ backend })
        });

        if (!response.ok) {
            const error = await response.text();
            throw new Error(`Failed to set checkpoint backend: ${error || response.statusText}`);
        }

        return response.json() as Promise<{
            success: boolean;
            backend: string;
            enabled: boolean;
        }>;
    }

    /**
     * Clear file-based checkpoints (v1.12.4)
     */
    async clearFileCheckpoints(keepLast: number = 0): Promise<{
        success: boolean;
        removed: number;
        message: string;
    }> {
        this.outputChannel.appendLine('[Checkpoint] Clearing file checkpoints...');

        const response = await fetch(`${this.baseUrl}/checkpoint/clear`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ keep_last: keepLast })
        });

        if (!response.ok) {
            const error = await response.text();
            throw new Error(`Failed to clear checkpoints: ${error || response.statusText}`);
        }

        return response.json() as Promise<{
            success: boolean;
            removed: number;
            message: string;
        }>;
    }

    /**
     * Request server shutdown via HTTP endpoint (v1.13.10)
     *
     * This is the preferred method to stop the server gracefully.
     * Uses the same endpoint as the web app (/shutdown).
     *
     * @returns Promise that resolves when shutdown is initiated
     * @throws Error if server is unreachable (which is often expected during shutdown)
     */
    async shutdown(): Promise<void> {
        this.outputChannel.appendLine('[Server] Requesting shutdown via /shutdown endpoint...');

        try {
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 5000);

            await fetch(`${this.baseUrl}/shutdown`, {
                method: 'POST',
                headers: this.getHeaders(),
                signal: controller.signal
            });

            clearTimeout(timeoutId);
            this.outputChannel.appendLine('[Server] Shutdown request acknowledged');
        } catch (error) {
            // Expected - server shuts down before responding
            this.outputChannel.appendLine('[Server] Shutdown initiated (connection closed as expected)');
        }
    }

    /**
     * Request autocomplete suggestions from the server (v1.17.4).
     * Returns items from engine CompletionProvider (commands, paths, @file refs).
     */
    async complete(buffer: string, cursor: number = -1): Promise<Array<{
        text: string;
        display: string;
        description: string;
        kind: string;
        replace_start: number;
    }>> {
        if (!this._ready) { return []; }
        try {
            const response = await fetch(`${this.baseUrl}/complete`, {
                method: 'POST',
                headers: this.getHeaders(true),
                // `client` lets the engine hide client-side commands this
                // client doesn't implement (engine/completion.py _CLIENT_GATES).
                body: JSON.stringify({ buffer, cursor, client: 'vscode' }),
            });
            if (!response.ok) { return []; }
            const data = await response.json() as { items: Array<any> };
            return data.items || [];
        } catch {
            return [];
        }
    }

    /**
     * Forward a client event to the server debug log (fire-and-forget).
     * @param level - 'info' | 'warning' | 'error'
     * @param message - The log message
     */
    logClientEvent(level: string, message: string): void {
        if (!this._ready) { return; }
        fetch(`${this.baseUrl}/client-log`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ level, message, client: 'vscode' }),
        }).catch(() => {});
    }
}

/**
 * Singleton instance management
 */
let _httpClient: HttpClient | null = null;

export function getHttpClient(): HttpClient {
    if (!_httpClient) {
        const config = vscode.workspace.getConfiguration('ppxai');
        const serverUrl = config.get<string>('serverUrl') || 'http://127.0.0.1:54320';
        _httpClient = new HttpClient(serverUrl);
    }
    return _httpClient;
}

export function resetHttpClient(): void {
    if (_httpClient) {
        _httpClient.stop();
    }
    _httpClient = null;
}
