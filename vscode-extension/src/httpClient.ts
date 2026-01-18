/**
 * HTTP Client for ppxai-server
 *
 * Communicates with the ppxai HTTP server using REST + SSE for streaming.
 * Provides a compatible interface with PythonBackend for easy migration.
 */

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

export type ConsentResponse = 'y' | 'n' | 'always' | 'never';

// === Stream Event Types ===

export interface EventMetadata {
    file_path?: string;
    operation?: string;
    tool_name?: string;
    [key: string]: unknown;
}

export interface StreamEvent {
    type: 'thinking' | 'started' | 'reasoning_chunk' | 'chunk' | 'done' | 'error' | 'tool_call' | 'tool_result' | 'context_injected' | 'consent_request' | 'status' | 'agent_iteration' | 'agent_complete' | 'agent_max_iterations' | 'working_dir_changed';
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

export interface EngineStatus {
    provider: string;
    model: string;
    tools_enabled: boolean;
    tool_count?: number;
    has_api_key?: boolean;
    message_count?: number;
    auto_inject_context?: boolean;
}

export interface Message {
    role: 'user' | 'assistant' | 'system';
    content: string;
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

    constructor(baseUrl: string = 'http://127.0.0.1:54320', sessionId?: string) {
        this.baseUrl = baseUrl;
        // v1.14.0: Generate unique session ID for this client instance
        this._sessionId = sessionId || `vscode-${this.generateUUID()}`;
        this.outputChannel = vscode.window.createOutputChannel('ppxai HTTP');
        this.outputChannel.appendLine(`[Session] ID: ${this._sessionId}`);
    }

    /**
     * Generate a UUID v4 (v1.14.0)
     */
    private generateUUID(): string {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
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
            auto_inject_context: data.auto_inject_context,
        };
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
     * Set active provider
     */
    async setProvider(providerId: string, model?: string): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/providers`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ provider: providerId, model })
        });
        return response.ok;
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
     * Set active model
     */
    async setModel(modelId: string): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/models`, {
            method: 'POST',
            headers: this.getHeaders(true),
            body: JSON.stringify({ model: modelId })
        });
        return response.ok;
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
     * Send chat message with SSE streaming
     */
    async chat(message: string, streamCallback?: StreamCallback): Promise<string> {
        // Create new AbortController for this request
        this.currentAbortController = new AbortController();

        try {
            const response = await fetch(`${this.baseUrl}/chat`, {
                method: 'POST',
                headers: this.getHeaders(true),
                body: JSON.stringify({ message }),
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
                return { type: 'done', content: event.data || '' };
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
            case 'error':
                return { type: 'error', content: event.data || 'Unknown error' };
            case 'info':
                return { type: 'thinking', content: event.data || '' };
            default:
                return null;
        }
    }

    /**
     * Get conversation history
     */
    async getHistory(): Promise<Array<{ role: string; content: string }>> {
        return [...this.conversationHistory];
    }

    /**
     * Clear conversation history
     */
    async clearHistory(): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/sessions/clear`, {
            method: 'POST',
            headers: this.getHeaders()
        });
        if (response.ok) {
            this.conversationHistory = [];
        }
        return response.ok;
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
