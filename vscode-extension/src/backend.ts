/**
 * Python Backend Manager
 *
 * Manages communication with the ppxai Python JSON-RPC server.
 * Spawns python -m ppxai.server and communicates via stdio.
 */

import * as vscode from 'vscode';
import { spawn, ChildProcess } from 'child_process';
import * as readline from 'readline';
import * as path from 'path';

export interface StreamEvent {
    type: 'stream';
    id: number;
    event: {
        type: 'thinking' | 'started' | 'chunk' | 'done' | 'error' | 'tool_call' | 'tool_result' | 'context_injected';
        content: string;
    };
}

export interface JsonRpcResponse {
    jsonrpc: '2.0';
    id: number;
    result?: any;
    error?: {
        code: number;
        message: string;
    };
}

export interface ProviderInfo {
    id: string;
    name: string;
    has_api_key: boolean;
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
    tool_count: number;
    has_api_key: boolean;
    message_count: number;
}

type StreamCallback = (event: StreamEvent['event']) => void;

export class PythonBackend {
    private process: ChildProcess | null = null;
    private requestId: number = 0;
    private pendingRequests: Map<number, {
        resolve: (value: any) => void;
        reject: (error: Error) => void;
        streamCallback?: StreamCallback;
    }> = new Map();
    private outputChannel: vscode.OutputChannel;
    private ready: boolean = false;
    private readyPromise: Promise<void>;
    private readyResolve: (() => void) | null = null;

    constructor() {
        this.outputChannel = vscode.window.createOutputChannel('ppxai Backend');
        this.readyPromise = new Promise((resolve) => {
            this.readyResolve = resolve;
        });
    }

    /**
     * Start the Python backend server
     */
    async start(): Promise<boolean> {
        if (this.process) {
            return true;
        }

        const pythonPath = vscode.workspace.getConfiguration('ppxai').get<string>('pythonPath') || 'python3';

        // Find the ppxai package directory
        const workspaceFolders = vscode.workspace.workspaceFolders;
        let cwd = workspaceFolders?.[0]?.uri.fsPath;

        // Try to find ppxai in common locations
        const possiblePaths = [
            cwd,
            path.join(cwd || '', '..'),
            process.env.HOME ? path.join(process.env.HOME, '.ppxai') : undefined,
        ].filter(Boolean) as string[];

        this.outputChannel.appendLine(`Starting Python backend with: ${pythonPath} -m ppxai.server`);

        try {
            this.process = spawn(pythonPath, ['-m', 'ppxai.server'], {
                cwd: possiblePaths[0],
                env: { ...process.env, PYTHONUNBUFFERED: '1' }
            });

            if (!this.process.stdout || !this.process.stderr) {
                throw new Error('Failed to create process streams');
            }

            // Handle stdout (JSON-RPC responses)
            const rl = readline.createInterface({
                input: this.process.stdout,
                crlfDelay: Infinity
            });

            rl.on('line', (line) => {
                this.handleOutput(line);
            });

            // Handle stderr (errors and logs)
            this.process.stderr.on('data', (data) => {
                this.outputChannel.appendLine(`[stderr] ${data.toString()}`);
            });

            // Handle process exit
            this.process.on('exit', (code) => {
                this.outputChannel.appendLine(`Backend process exited with code ${code}`);
                this.process = null;
                this.ready = false;

                // Reject all pending requests
                for (const [, pending] of this.pendingRequests) {
                    pending.reject(new Error('Backend process exited'));
                }
                this.pendingRequests.clear();
            });

            this.process.on('error', (err) => {
                this.outputChannel.appendLine(`Backend process error: ${err.message}`);
                vscode.window.showErrorMessage(`ppxai backend error: ${err.message}`);
            });

            // Wait for ready signal
            await this.readyPromise;
            return true;

        } catch (error) {
            this.outputChannel.appendLine(`Failed to start backend: ${error}`);
            vscode.window.showErrorMessage(`Failed to start ppxai backend: ${error}`);
            return false;
        }
    }

    /**
     * Handle output from the Python process
     */
    private handleOutput(line: string) {
        if (!line.trim()) {return;}

        this.outputChannel.appendLine(`[recv] ${line}`);

        try {
            const data = JSON.parse(line);

            // Handle ready signal
            if (data.type === 'ready') {
                this.ready = true;
                this.outputChannel.appendLine('Backend ready');
                if (this.readyResolve) {
                    this.readyResolve();
                    this.readyResolve = null;
                }
                return;
            }

            // Handle streaming events
            if (data.type === 'stream') {
                const streamEvent = data as StreamEvent;
                const pending = this.pendingRequests.get(streamEvent.id);
                if (pending?.streamCallback) {
                    pending.streamCallback(streamEvent.event);
                }
                return;
            }

            // Handle JSON-RPC response
            const response = data as JsonRpcResponse;
            const pending = this.pendingRequests.get(response.id);
            if (pending) {
                this.pendingRequests.delete(response.id);
                if (response.error) {
                    pending.reject(new Error(response.error.message));
                } else {
                    pending.resolve(response.result);
                }
            }

        } catch (error) {
            this.outputChannel.appendLine(`Parse error: ${error}`);
        }
    }

    /**
     * Send a JSON-RPC request
     */
    private async request<T>(method: string, params: any = {}, streamCallback?: StreamCallback, timeoutMs: number = 60000): Promise<T> {
        if (!this.process || !this.ready) {
            const started = await this.start();
            if (!started) {
                throw new Error('Backend not available');
            }
        }

        const id = ++this.requestId;
        const request = {
            jsonrpc: '2.0',
            id,
            method,
            params
        };

        return new Promise<T>((resolve, reject) => {
            this.pendingRequests.set(id, { resolve, reject, streamCallback });

            const requestStr = JSON.stringify(request);
            this.outputChannel.appendLine(`[send] ${requestStr}`);
            this.process!.stdin!.write(requestStr + '\n');

            // Timeout
            setTimeout(() => {
                if (this.pendingRequests.has(id)) {
                    this.pendingRequests.delete(id);
                    reject(new Error('Request timeout'));
                }
            }, timeoutMs);
        });
    }

    /**
     * Stop the backend
     */
    stop() {
        if (this.process) {
            this.process.kill();
            this.process = null;
            this.ready = false;
        }
    }

    /**
     * Check if backend is running
     */
    isRunning(): boolean {
        return this.ready && this.process !== null;
    }

    // === API Methods ===

    async getStatus(): Promise<EngineStatus> {
        return this.request<EngineStatus>('get_status');
    }

    async getProviders(): Promise<ProviderInfo[]> {
        return this.request<ProviderInfo[]>('get_providers');
    }

    async setProvider(provider: string): Promise<boolean> {
        return this.request<boolean>('set_provider', { provider });
    }

    async getModels(): Promise<ModelInfo[]> {
        return this.request<ModelInfo[]>('get_models');
    }

    async setModel(model: string): Promise<boolean> {
        return this.request<boolean>('set_model', { model });
    }

    async enableTools(): Promise<boolean> {
        return this.request<boolean>('enable_tools');
    }

    async disableTools(): Promise<boolean> {
        return this.request<boolean>('disable_tools');
    }

    async listTools(): Promise<ToolInfo[]> {
        return this.request<ToolInfo[]>('list_tools');
    }

    async getToolsStatus(): Promise<{ enabled: boolean; tool_count: number; max_iterations: number }> {
        return this.request('get_tools_status');
    }

    async setToolConfig(setting: string, value: any): Promise<boolean> {
        return this.request<boolean>('set_tool_config', { setting, value });
    }

    // Context injection methods
    async setWorkingDir(path: string): Promise<boolean> {
        return this.request<boolean>('set_working_dir', { path });
    }

    async setAutoInject(enabled: boolean): Promise<boolean> {
        return this.request<boolean>('set_auto_inject', { enabled });
    }

    async getAutoInject(): Promise<boolean> {
        return this.request<boolean>('get_auto_inject');
    }

    async chat(message: string, streamCallback?: StreamCallback): Promise<string> {
        // 5 minute timeout for chat (tool calls can take a while)
        return this.request<string>('chat', { message, stream: !!streamCallback }, streamCallback, 300000);
    }

    async codingTask(
        taskType: string,
        content: string,
        language?: string,
        filename?: string,
        streamCallback?: StreamCallback
    ): Promise<string> {
        // 5 minute timeout for coding tasks
        return this.request<string>('coding_task', {
            task_type: taskType,
            content,
            language,
            filename,
            stream: !!streamCallback
        }, streamCallback, 300000);
    }

    async getHistory(): Promise<Array<{ role: string; content: string }>> {
        return this.request('get_history');
    }

    async clearHistory(): Promise<boolean> {
        return this.request<boolean>('clear_history');
    }

    async saveSession(): Promise<string> {
        return this.request<string>('save_session');
    }

    async getSessions(): Promise<Array<{
        name: string;
        created_at: string;
        provider: string;
        model: string;
        message_count: number;
    }>> {
        return this.request('get_sessions');
    }

    async loadSession(sessionName: string): Promise<boolean> {
        return this.request<boolean>('load_session', { session_name: sessionName });
    }

    async getUsage(): Promise<{
        total_tokens: number;
        prompt_tokens: number;
        completion_tokens: number;
        estimated_cost: number;
    }> {
        return this.request('get_usage');
    }
}
