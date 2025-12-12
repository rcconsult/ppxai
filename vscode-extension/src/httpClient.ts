/**
 * HTTP Client for ppxai-server
 *
 * Communicates with the ppxai HTTP server using REST + SSE for streaming.
 * Provides a compatible interface with PythonBackend for easy migration.
 */

import * as vscode from 'vscode';

// === Types matching PythonBackend interface ===

export interface StreamEvent {
    type: 'thinking' | 'started' | 'chunk' | 'done' | 'error' | 'tool_call' | 'tool_result' | 'context_injected';
    content: string;
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
    provider: string;
    model: string;
    message_count: number;
}

type StreamCallback = (event: StreamEvent) => void;

/**
 * HTTP Client for ppxai-server communication
 *
 * Provides the same interface as PythonBackend for easy migration.
 */
export class HttpClient {
    private baseUrl: string;
    private conversationHistory: Message[] = [];
    private outputChannel: vscode.OutputChannel;
    private _ready: boolean = false;

    constructor(baseUrl: string = 'http://127.0.0.1:54320') {
        this.baseUrl = baseUrl;
        this.outputChannel = vscode.window.createOutputChannel('ppxai HTTP');
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
     * Get current engine status
     */
    async getStatus(): Promise<EngineStatus> {
        const response = await fetch(`${this.baseUrl}/status`);
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
        const response = await fetch(`${this.baseUrl}/providers`);
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
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: providerId, model })
        });
        return response.ok;
    }

    /**
     * Get available models for current provider
     */
    async getModels(): Promise<ModelInfo[]> {
        const response = await fetch(`${this.baseUrl}/models`);
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
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model: modelId })
        });
        return response.ok;
    }

    /**
     * Get tools list
     */
    async listTools(): Promise<ToolInfo[]> {
        const response = await fetch(`${this.baseUrl}/tools`);
        if (!response.ok) {
            throw new Error(`Failed to get tools: ${response.statusText}`);
        }
        const data = await response.json() as { tools: ToolInfo[]; enabled: boolean };
        return data.tools;
    }

    /**
     * Get tools status
     */
    async getToolsStatus(): Promise<{ enabled: boolean; tool_count: number; max_iterations: number }> {
        const response = await fetch(`${this.baseUrl}/tools`);
        if (!response.ok) {
            throw new Error(`Failed to get tools: ${response.statusText}`);
        }
        const data = await response.json() as { tools: ToolInfo[]; enabled: boolean };
        return {
            enabled: data.enabled,
            tool_count: data.tools.length,
            max_iterations: 10  // Default, not exposed by HTTP API yet
        };
    }

    /**
     * Enable tools
     */
    async enableTools(): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/tools`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled: false })
        });
        return response.ok;
    }

    /**
     * Set tool configuration (stub for interface compatibility)
     */
    async setToolConfig(_setting: string, _value: any): Promise<boolean> {
        // Not yet implemented in HTTP API
        return true;
    }

    /**
     * Set working directory (stub for interface compatibility)
     */
    async setWorkingDir(_path: string): Promise<boolean> {
        // Not yet implemented in HTTP API
        return true;
    }

    /**
     * Set auto-inject context (stub for interface compatibility)
     */
    async setAutoInject(_enabled: boolean): Promise<boolean> {
        // Not yet implemented in HTTP API
        return true;
    }

    /**
     * Get auto-inject status (stub for interface compatibility)
     */
    async getAutoInject(): Promise<boolean> {
        try {
            const status = await this.getStatus();
            return status.auto_inject_context || false;
        } catch {
            return false;
        }
    }

    /**
     * Send chat message with SSE streaming
     */
    async chat(message: string, streamCallback?: StreamCallback): Promise<string> {
        const response = await fetch(`${this.baseUrl}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message })
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

        const response = await fetch(`${this.baseUrl}/coding_task`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, task_type: taskType })
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
    }

    /**
     * Map server SSE events to StreamEvent format
     */
    private mapServerEvent(event: { type: string; data: any; metadata?: any }): StreamEvent | null {
        switch (event.type) {
            case 'stream_start':
                return { type: 'started', content: '' };
            case 'stream_chunk':
                return { type: 'chunk', content: event.data || '' };
            case 'stream_end':
                return { type: 'done', content: event.data || '' };
            case 'tool_call':
                return { type: 'tool_call', content: JSON.stringify(event.data) };
            case 'tool_result':
                return { type: 'tool_result', content: event.data || '' };
            case 'tool_error':
                return { type: 'error', content: event.data || 'Tool error' };
            case 'context_injected':
                return { type: 'context_injected', content: event.data || '' };
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
            method: 'POST'
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
            headers: { 'Content-Type': 'application/json' },
            body: name ? JSON.stringify({ name }) : '{}'
        });
        if (!response.ok) {
            throw new Error(`Failed to save session: ${response.statusText}`);
        }
        const data = await response.json() as { name: string };
        return data.name;
    }

    /**
     * Get saved sessions
     */
    async getSessions(): Promise<SessionInfo[]> {
        const response = await fetch(`${this.baseUrl}/sessions`);
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
            method: 'POST'
        });
        return response.ok;
    }

    /**
     * Get usage statistics (stub - not yet in HTTP API)
     */
    async getUsage(): Promise<{
        total_tokens: number;
        prompt_tokens: number;
        completion_tokens: number;
        estimated_cost: number;
    }> {
        // Not yet implemented in HTTP API
        return {
            total_tokens: 0,
            prompt_tokens: 0,
            completion_tokens: 0,
            estimated_cost: 0
        };
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
