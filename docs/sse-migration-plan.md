# SSE Migration Plan: JSON-RPC to HTTP + Server-Sent Events

## Executive Summary

This document outlines the migration from JSON-RPC over stdio to HTTP with Server-Sent Events (SSE) for the ppxai VS Code extension backend communication. This change will significantly improve streaming performance, reduce latency, and provide better developer tooling.

**Target Version:** v1.9.0 (Part B - after uv migration)

**Prerequisites:** Complete [uv migration](uv-migration-plan.md) first (Part A of v1.9.0)

---

## Motivation

### Current Architecture Issues

The current VS Code extension communicates with the Python backend via JSON-RPC over stdio:

```
Extension → spawn python → stdio JSON-RPC → EngineClient
                          (blocking per request)
```

**Problems identified:**

1. **Synchronous Request Handling**
   - `jsonrpc.py` uses `for line in sys.stdin` with `asyncio.run()` per request
   - Each request blocks until complete, preventing true concurrent handling
   - Location: [ppxai/server/jsonrpc.py:415-438](../ppxai/server/jsonrpc.py)

2. **Mixed Stdout Protocol**
   - Streaming events and JSON-RPC responses share the same stdout channel
   - Custom parsing logic required in extension
   - Location: [vscode-extension/src/backend.ts:160-203](../vscode-extension/src/backend.ts)

3. **Process Management Overhead**
   - Child process spawn adds ~100-300ms startup latency
   - Process crash requires full restart
   - No graceful reconnection

4. **Limited Debugging**
   - Custom protocol not inspectable with standard tools
   - Difficult to debug streaming issues

### Why Server-Sent Events?

SSE is the optimal choice for LLM streaming because:

| Feature | SSE | WebSocket | JSON-RPC/stdio |
|---------|-----|-----------|----------------|
| Streaming support | Native | Native | Custom |
| HTTP compatible | Yes | Upgrade required | No |
| Auto-reconnect | Built-in | Manual | Manual |
| Proxy/firewall friendly | Yes | Sometimes blocked | N/A |
| Browser DevTools | Full support | Limited | None |
| Implementation complexity | Low | Medium | Medium |
| Request cancellation | AbortController | Manual | Kill process |

SSE is specifically designed for server-to-client streaming, which matches the LLM response pattern perfectly.

---

## Performance Analysis

### Expected Improvements

| Metric | JSON-RPC (current) | HTTP + SSE (proposed) | Improvement |
|--------|-------------------|----------------------|-------------|
| First token latency | 50-200ms | 10-30ms | 3-10x faster |
| Throughput | ~1,000 msg/s | ~5,000 msg/s | 5x higher |
| Memory per connection | Process overhead | HTTP connection | Lower |
| Reconnection time | Full restart | <100ms | Much faster |

### Why the Improvement?

1. **No asyncio.run() per request**: FastAPI handles async natively
2. **No JSON-RPC envelope**: SSE events are simpler
3. **Connection reuse**: HTTP keep-alive vs new request parsing
4. **Native streaming**: No buffering of stdout

---

## Proposed Architecture

```
Current:  Extension → spawn python → stdio JSON-RPC → EngineClient
                      (blocking per request)

Proposed: Extension → HTTP fetch  → FastAPI/SSE → EngineClient
                      (native streaming)
```

### Component Overview

```
vscode-extension/
├── src/
│   ├── backend.ts           # Legacy JSON-RPC (kept for fallback)
│   ├── backend-http.ts      # NEW: HTTP + SSE client
│   ├── serverManager.ts     # NEW: Server lifecycle management
│   └── backendFactory.ts    # NEW: Auto-select best backend

ppxai/
├── server/
│   ├── jsonrpc.py           # Legacy (kept for backward compat)
│   ├── http.py              # NEW: FastAPI + SSE server
│   └── __main__.py          # Updated: Support both modes
```

---

## Implementation Plan

### Step 1: Install Server Dependencies

With uv migration complete (Part A), server dependencies are already defined in `pyproject.toml`:

```toml
# Already in pyproject.toml
[project.optional-dependencies]
server = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
]
```

**Install server dependencies:**
```bash
uv sync --extra server
```

**Rationale:**
- FastAPI: Modern async web framework with excellent streaming support
- uvicorn: ASGI server with optimal performance for SSE

---

### Step 2: Create HTTP Server

**File:** `ppxai/server/http.py`

```python
"""
HTTP server with SSE streaming for ppxai engine.

This server provides better performance than JSON-RPC/stdio for
streaming LLM responses. See docs/sse-migration-plan.md for details.
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Optional, List, Any
import json
import os

from ..engine import EngineClient, EventType


class ChatRequest(BaseModel):
    message: str
    stream: bool = True
    context: Optional[dict] = None


class CodingTaskRequest(BaseModel):
    task_type: str
    content: str
    language: Optional[str] = None
    filename: Optional[str] = None
    stream: bool = True


class ProviderRequest(BaseModel):
    provider: str


class ModelRequest(BaseModel):
    model: str


class ToolConfigRequest(BaseModel):
    setting: str
    value: Any


class WorkingDirRequest(BaseModel):
    path: str


class SessionRequest(BaseModel):
    session_name: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize engine on startup, cleanup on shutdown."""
    app.state.engine = EngineClient()

    # Auto-select first provider with API key
    for provider in app.state.engine.list_providers():
        if provider.has_api_key:
            app.state.engine.set_provider(provider.id)
            break

    yield

    await app.state.engine.cleanup()


app = FastAPI(
    title="ppxai API",
    description="HTTP API for ppxai AI assistant",
    version="1.0.0",
    lifespan=lifespan
)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["vscode-webview://*", "http://localhost:*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Streaming Endpoints ===

@app.post("/chat")
async def chat(request: Request, body: ChatRequest):
    """
    Chat endpoint with Server-Sent Events streaming.

    Events:
    - stream_start: Chat started
    - stream_chunk: Partial response token
    - context_injected: File content was auto-injected
    - tool_call: Tool being invoked
    - tool_result: Tool execution result
    - stream_end: Final complete response
    - error: Error occurred
    """
    engine: EngineClient = request.app.state.engine

    # Build message with optional context
    message = body.message
    if body.context and body.context.get("code"):
        lang = body.context.get("language", "")
        message = f"{message}\n\n```{lang}\n{body.context['code']}\n```"

    async def generate():
        try:
            async for event in engine.chat(message, stream=body.stream):
                data = {
                    "type": event.type.value,
                    "data": event.data,
                }
                if event.metadata:
                    data["metadata"] = event.metadata
                yield f"data: {json.dumps(data)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            error_data = {"type": "error", "data": str(e)}
            yield f"data: {json.dumps(error_data)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@app.post("/coding_task")
async def coding_task(request: Request, body: CodingTaskRequest):
    """Execute a coding task with SSE streaming."""
    engine: EngineClient = request.app.state.engine

    # Import coding prompts
    from ..prompts import CODING_PROMPTS

    if body.task_type not in CODING_PROMPTS:
        raise HTTPException(status_code=400, detail=f"Unknown task type: {body.task_type}")

    system_prompt = CODING_PROMPTS[body.task_type]

    # Build user message
    if body.task_type == "explain":
        user_message = f"Explain this code:\n\n```{body.language or ''}\n{body.content}\n```"
    elif body.task_type == "test":
        user_message = f"Generate unit tests for this code:\n\n```{body.language or ''}\n{body.content}\n```"
    elif body.task_type == "docs":
        user_message = f"Generate documentation for this code:\n\n```{body.language or ''}\n{body.content}\n```"
    elif body.task_type == "debug":
        user_message = f"Debug this error:\n\n{body.content}"
    elif body.task_type == "implement":
        user_message = f"Implement the following in {body.language or 'Python'}:\n\n{body.content}"
    else:
        user_message = body.content

    if body.filename:
        user_message = f"File: {body.filename}\n\n{user_message}"

    full_message = f"{system_prompt}\n\n{user_message}"

    async def generate():
        try:
            async for event in engine.chat(full_message, stream=body.stream):
                data = {"type": event.type.value, "data": event.data}
                yield f"data: {json.dumps(data)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# === Provider Endpoints ===

@app.get("/providers")
async def get_providers(request: Request):
    """List available providers."""
    engine: EngineClient = request.app.state.engine
    return [
        {
            "id": p.id,
            "name": p.name,
            "has_api_key": p.has_api_key
        }
        for p in engine.list_providers()
    ]


@app.post("/provider")
async def set_provider(request: Request, body: ProviderRequest):
    """Switch to a different provider."""
    engine: EngineClient = request.app.state.engine
    success = engine.set_provider(body.provider)
    if not success:
        raise HTTPException(status_code=400, detail=f"Provider not found or no API key: {body.provider}")
    return {"success": True}


# === Model Endpoints ===

@app.get("/models")
async def get_models(request: Request):
    """List models for current provider."""
    engine: EngineClient = request.app.state.engine
    return [
        {
            "id": m.id,
            "name": m.name,
            "description": m.description
        }
        for m in engine.list_models()
    ]


@app.post("/model")
async def set_model(request: Request, body: ModelRequest):
    """Switch to a different model."""
    engine: EngineClient = request.app.state.engine
    success = engine.set_model(body.model)
    return {"success": success}


# === Tool Endpoints ===

@app.post("/tools/enable")
async def enable_tools(request: Request):
    """Enable AI tools."""
    engine: EngineClient = request.app.state.engine
    return {"success": engine.enable_tools()}


@app.post("/tools/disable")
async def disable_tools(request: Request):
    """Disable AI tools."""
    engine: EngineClient = request.app.state.engine
    return {"success": engine.disable_tools()}


@app.get("/tools")
async def list_tools(request: Request):
    """List available tools."""
    engine: EngineClient = request.app.state.engine
    return engine.list_tools()


@app.get("/tools/status")
async def get_tools_status(request: Request):
    """Get tools status."""
    engine: EngineClient = request.app.state.engine
    return engine.get_tools_status()


@app.post("/tools/config")
async def set_tool_config(request: Request, body: ToolConfigRequest):
    """Configure tool settings."""
    engine: EngineClient = request.app.state.engine
    return {"success": engine.set_tool_config(body.setting, body.value)}


# === Context Injection Endpoints ===

@app.post("/working_dir")
async def set_working_dir(request: Request, body: WorkingDirRequest):
    """Set working directory for file path resolution."""
    engine: EngineClient = request.app.state.engine
    engine.set_working_dir(body.path)
    return {"success": True}


@app.post("/auto_inject")
async def set_auto_inject(request: Request, enabled: bool):
    """Enable or disable automatic context injection."""
    engine: EngineClient = request.app.state.engine
    return {"success": engine.set_auto_inject(enabled)}


@app.get("/auto_inject")
async def get_auto_inject(request: Request):
    """Check if auto-injection is enabled."""
    engine: EngineClient = request.app.state.engine
    return {"enabled": engine.get_auto_inject()}


# === Session Endpoints ===

@app.get("/sessions")
async def get_sessions(request: Request):
    """List saved sessions."""
    engine: EngineClient = request.app.state.engine
    return [
        {
            "name": s.name,
            "created_at": s.created_at,
            "provider": s.provider,
            "model": s.model,
            "message_count": s.message_count
        }
        for s in engine.list_sessions()
    ]


@app.post("/session/load")
async def load_session(request: Request, body: SessionRequest):
    """Load a saved session."""
    engine: EngineClient = request.app.state.engine
    success = engine.load_session(body.session_name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Session not found: {body.session_name}")
    return {"success": True}


@app.post("/session/save")
async def save_session(request: Request):
    """Save current session."""
    engine: EngineClient = request.app.state.engine
    name = engine.save_session()
    return {"name": name}


@app.get("/history")
async def get_history(request: Request):
    """Get conversation history."""
    engine: EngineClient = request.app.state.engine
    return engine.get_history()


@app.post("/history/clear")
async def clear_history(request: Request):
    """Clear conversation history."""
    engine: EngineClient = request.app.state.engine
    engine.clear_history()
    return {"success": True}


@app.get("/usage")
async def get_usage(request: Request):
    """Get usage statistics."""
    engine: EngineClient = request.app.state.engine
    return engine.get_usage()


# === Status ===

@app.get("/status")
async def get_status(request: Request):
    """Get current engine status."""
    engine: EngineClient = request.app.state.engine
    return engine.get_status()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


# === Server Runner ===

def run_server(host: str = "127.0.0.1", port: int = None):
    """Run the HTTP server.

    Usage:
        uv run ppxai-server
        # Or directly:
        uv run python -m ppxai.server.http
    """
    import uvicorn

    if port is None:
        port = int(os.environ.get("PPXAI_PORT", "8765"))

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )


if __name__ == "__main__":
    run_server()
```

---

### Step 3: Create TypeScript HTTP Client

**File:** `vscode-extension/src/backend-http.ts`

```typescript
/**
 * HTTP Backend with SSE Streaming
 *
 * Replaces JSON-RPC/stdio for better streaming performance.
 * See docs/sse-migration-plan.md for details.
 */

export interface StreamEvent {
    type: string;
    data: any;
    metadata?: Record<string, any>;
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

export interface EngineStatus {
    provider: string;
    model: string;
    tools_enabled: boolean;
    tool_count: number;
    has_api_key: boolean;
    message_count: number;
}

export interface ToolsStatus {
    enabled: boolean;
    tool_count: number;
    max_iterations: number;
}

export interface SessionInfo {
    name: string;
    created_at: string;
    provider: string;
    model: string;
    message_count: number;
}

export interface UsageStats {
    total_tokens: number;
    prompt_tokens: number;
    completion_tokens: number;
    estimated_cost: number;
}

type StreamCallback = (event: StreamEvent) => void;

export class HttpBackend {
    private baseUrl: string;
    private abortController: AbortController | null = null;

    constructor(port: number = 8765) {
        this.baseUrl = `http://127.0.0.1:${port}`;
    }

    /**
     * Check if the HTTP server is available
     */
    async isAvailable(): Promise<boolean> {
        try {
            const response = await fetch(`${this.baseUrl}/health`, {
                method: 'GET',
                signal: AbortSignal.timeout(1000)
            });
            return response.ok;
        } catch {
            return false;
        }
    }

    /**
     * Chat with SSE streaming
     */
    async chat(
        message: string,
        onEvent?: StreamCallback,
        context?: { code?: string; language?: string }
    ): Promise<string> {
        this.abortController = new AbortController();

        const response = await fetch(`${this.baseUrl}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message,
                stream: !!onEvent,
                context
            }),
            signal: this.abortController.signal
        });

        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        if (!response.body) {
            throw new Error('No response body');
        }

        return this.processSSEStream(response.body, onEvent);
    }

    /**
     * Execute coding task with SSE streaming
     */
    async codingTask(
        taskType: string,
        content: string,
        language?: string,
        filename?: string,
        onEvent?: StreamCallback
    ): Promise<string> {
        this.abortController = new AbortController();

        const response = await fetch(`${this.baseUrl}/coding_task`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                task_type: taskType,
                content,
                language,
                filename,
                stream: !!onEvent
            }),
            signal: this.abortController.signal
        });

        if (!response.ok) {
            throw new Error(`HTTP error: ${response.status}`);
        }

        if (!response.body) {
            throw new Error('No response body');
        }

        return this.processSSEStream(response.body, onEvent);
    }

    /**
     * Process SSE stream and extract events
     */
    private async processSSEStream(
        body: ReadableStream<Uint8Array>,
        onEvent?: StreamCallback
    ): Promise<string> {
        const reader = body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let finalContent = '';

        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });

                // Process complete SSE events
                const lines = buffer.split('\n\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        const data = line.slice(6).trim();

                        if (data === '[DONE]') {
                            continue;
                        }

                        try {
                            const event = JSON.parse(data) as StreamEvent;

                            // Map to legacy event format for compatibility
                            if (onEvent) {
                                onEvent({
                                    type: this.mapEventType(event.type),
                                    data: event.data,
                                    metadata: event.metadata
                                });
                            }

                            if (event.type === 'stream_end') {
                                finalContent = event.data;
                            }
                        } catch (e) {
                            console.error('SSE parse error:', e);
                        }
                    }
                }
            }
        } finally {
            reader.releaseLock();
        }

        return finalContent;
    }

    /**
     * Map event types to match legacy backend format
     */
    private mapEventType(type: string): string {
        const mapping: Record<string, string> = {
            'stream_start': 'started',
            'stream_chunk': 'chunk',
            'stream_end': 'done',
            'context_injected': 'context_injected',
            'tool_call': 'tool_call',
            'tool_result': 'tool_result',
            'error': 'error'
        };
        return mapping[type] || type;
    }

    /**
     * Cancel ongoing chat request
     */
    cancelChat(): void {
        this.abortController?.abort();
        this.abortController = null;
    }

    // === Provider Methods ===

    async getProviders(): Promise<ProviderInfo[]> {
        const response = await fetch(`${this.baseUrl}/providers`);
        return response.json();
    }

    async setProvider(provider: string): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/provider`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider })
        });
        const result = await response.json();
        return result.success;
    }

    // === Model Methods ===

    async getModels(): Promise<ModelInfo[]> {
        const response = await fetch(`${this.baseUrl}/models`);
        return response.json();
    }

    async setModel(model: string): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/model`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model })
        });
        const result = await response.json();
        return result.success;
    }

    // === Tool Methods ===

    async enableTools(): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/tools/enable`, { method: 'POST' });
        const result = await response.json();
        return result.success;
    }

    async disableTools(): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/tools/disable`, { method: 'POST' });
        const result = await response.json();
        return result.success;
    }

    async listTools(): Promise<Array<{ name: string; description: string }>> {
        const response = await fetch(`${this.baseUrl}/tools`);
        return response.json();
    }

    async getToolsStatus(): Promise<ToolsStatus> {
        const response = await fetch(`${this.baseUrl}/tools/status`);
        return response.json();
    }

    async setToolConfig(setting: string, value: any): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/tools/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ setting, value })
        });
        const result = await response.json();
        return result.success;
    }

    // === Context Methods ===

    async setWorkingDir(path: string): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/working_dir`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });
        const result = await response.json();
        return result.success;
    }

    // === Session Methods ===

    async getSessions(): Promise<SessionInfo[]> {
        const response = await fetch(`${this.baseUrl}/sessions`);
        return response.json();
    }

    async loadSession(sessionName: string): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/session/load`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_name: sessionName })
        });
        return response.ok;
    }

    async saveSession(): Promise<string> {
        const response = await fetch(`${this.baseUrl}/session/save`, { method: 'POST' });
        const result = await response.json();
        return result.name;
    }

    async getHistory(): Promise<Array<{ role: string; content: string }>> {
        const response = await fetch(`${this.baseUrl}/history`);
        return response.json();
    }

    async clearHistory(): Promise<boolean> {
        const response = await fetch(`${this.baseUrl}/history/clear`, { method: 'POST' });
        return response.ok;
    }

    async getUsage(): Promise<UsageStats> {
        const response = await fetch(`${this.baseUrl}/usage`);
        return response.json();
    }

    // === Status ===

    async getStatus(): Promise<EngineStatus> {
        const response = await fetch(`${this.baseUrl}/status`);
        return response.json();
    }
}
```

---

### Step 4: Server Lifecycle Manager

**File:** `vscode-extension/src/serverManager.ts`

```typescript
/**
 * Manages the ppxai HTTP server lifecycle
 *
 * Supports both uv (recommended) and direct Python execution.
 */

import * as vscode from 'vscode';
import { spawn, ChildProcess } from 'child_process';
import * as which from 'which';

export class ServerManager {
    private process: ChildProcess | null = null;
    private port: number;
    private outputChannel: vscode.OutputChannel;

    constructor(port: number = 8765) {
        this.port = port;
        this.outputChannel = vscode.window.createOutputChannel('ppxai Server');
    }

    /**
     * Check if uv is available
     */
    private async hasUv(): Promise<boolean> {
        try {
            await which('uv');
            return true;
        } catch {
            return false;
        }
    }

    /**
     * Start the HTTP server
     */
    async start(): Promise<boolean> {
        if (this.process) {
            return true; // Already running
        }

        const useUv = await this.hasUv();
        const pythonPath = vscode.workspace.getConfiguration('ppxai')
            .get<string>('pythonPath') || 'python3';

        // Determine command based on uv availability
        const command = useUv ? 'uv' : pythonPath;
        const args = useUv
            ? ['run', 'ppxai-server']
            : ['-m', 'ppxai.server.http'];

        this.outputChannel.appendLine(
            `Starting HTTP server on port ${this.port} using ${useUv ? 'uv' : 'python'}...`
        );

        try {
            this.process = spawn(command, args, {
                env: {
                    ...process.env,
                    PPXAI_PORT: String(this.port),
                    PYTHONUNBUFFERED: '1'
                }
            });

            // Log stdout
            this.process.stdout?.on('data', (data) => {
                this.outputChannel.appendLine(`[stdout] ${data.toString().trim()}`);
            });

            // Log stderr
            this.process.stderr?.on('data', (data) => {
                this.outputChannel.appendLine(`[stderr] ${data.toString().trim()}`);
            });

            // Handle exit
            this.process.on('exit', (code) => {
                this.outputChannel.appendLine(`Server exited with code ${code}`);
                this.process = null;
            });

            // Wait for server to be ready
            return await this.waitForReady(10000);

        } catch (error) {
            this.outputChannel.appendLine(`Failed to start server: ${error}`);
            return false;
        }
    }

    /**
     * Wait for server to respond to health check
     */
    private async waitForReady(timeoutMs: number): Promise<boolean> {
        const startTime = Date.now();
        const checkInterval = 100;

        while (Date.now() - startTime < timeoutMs) {
            try {
                const response = await fetch(`http://127.0.0.1:${this.port}/health`, {
                    signal: AbortSignal.timeout(500)
                });
                if (response.ok) {
                    this.outputChannel.appendLine('Server is ready');
                    return true;
                }
            } catch {
                // Server not ready yet
            }
            await new Promise(resolve => setTimeout(resolve, checkInterval));
        }

        this.outputChannel.appendLine('Server startup timeout');
        return false;
    }

    /**
     * Stop the server
     */
    stop(): void {
        if (this.process) {
            this.outputChannel.appendLine('Stopping server...');
            this.process.kill();
            this.process = null;
        }
    }

    /**
     * Check if server is running
     */
    isRunning(): boolean {
        return this.process !== null;
    }

    /**
     * Get the server port
     */
    getPort(): number {
        return this.port;
    }
}
```

---

### Step 5: Backend Factory with Fallback

**File:** `vscode-extension/src/backendFactory.ts`

```typescript
/**
 * Backend factory with automatic fallback
 *
 * Tries HTTP backend first, falls back to JSON-RPC if unavailable.
 */

import { HttpBackend } from './backend-http';
import { PythonBackend } from './backend';
import { ServerManager } from './serverManager';

export interface Backend {
    chat(message: string, onEvent?: (event: any) => void): Promise<string>;
    getProviders(): Promise<any[]>;
    setProvider(provider: string): Promise<boolean>;
    getModels(): Promise<any[]>;
    setModel(model: string): Promise<boolean>;
    enableTools(): Promise<boolean>;
    disableTools(): Promise<boolean>;
    listTools(): Promise<any[]>;
    getToolsStatus(): Promise<any>;
    setToolConfig(setting: string, value: any): Promise<boolean>;
    setWorkingDir(path: string): Promise<boolean>;
    getSessions(): Promise<any[]>;
    loadSession(name: string): Promise<boolean>;
    saveSession(): Promise<string>;
    getHistory(): Promise<any[]>;
    clearHistory(): Promise<boolean>;
    getUsage(): Promise<any>;
    getStatus(): Promise<any>;
}

export class BackendFactory {
    private serverManager: ServerManager;
    private httpBackend: HttpBackend | null = null;
    private jsonRpcBackend: PythonBackend | null = null;
    private activeBackend: 'http' | 'jsonrpc' | null = null;

    constructor() {
        this.serverManager = new ServerManager();
    }

    /**
     * Get the best available backend
     */
    async getBackend(): Promise<Backend> {
        // Try HTTP backend first
        if (!this.httpBackend) {
            this.httpBackend = new HttpBackend(this.serverManager.getPort());
        }

        // Check if HTTP server is running or start it
        if (!this.serverManager.isRunning()) {
            const started = await this.serverManager.start();
            if (started && await this.httpBackend.isAvailable()) {
                this.activeBackend = 'http';
                return this.httpBackend;
            }
        } else if (await this.httpBackend.isAvailable()) {
            this.activeBackend = 'http';
            return this.httpBackend;
        }

        // Fall back to JSON-RPC
        console.log('HTTP backend unavailable, falling back to JSON-RPC');
        if (!this.jsonRpcBackend) {
            this.jsonRpcBackend = new PythonBackend();
        }
        await this.jsonRpcBackend.start();
        this.activeBackend = 'jsonrpc';
        return this.jsonRpcBackend as unknown as Backend;
    }

    /**
     * Get the currently active backend type
     */
    getActiveBackendType(): 'http' | 'jsonrpc' | null {
        return this.activeBackend;
    }

    /**
     * Cleanup resources
     */
    dispose(): void {
        this.serverManager.stop();
        if (this.jsonRpcBackend) {
            this.jsonRpcBackend.stop();
        }
    }
}
```

---

## Migration Checklist

### Prerequisites
- [ ] Complete uv migration (Part A of v1.9.0) - see [uv-migration-plan.md](uv-migration-plan.md)
- [ ] Verify `pyproject.toml` includes server optional dependencies

### Phase 1: Backend Implementation
- [ ] Install server dependencies: `uv sync --extra server`
- [ ] Create `ppxai/server/http.py`
- [ ] Add `__main__.py` entry point for HTTP server
- [ ] Test HTTP server independently: `uv run ppxai-server`

### Phase 2: Extension Updates
- [ ] Create `vscode-extension/src/backend-http.ts`
- [ ] Create `vscode-extension/src/serverManager.ts`
- [ ] Create `vscode-extension/src/backendFactory.ts`
- [ ] Update `chatPanel.ts` to use `BackendFactory`
- [ ] Update `extension.ts` to manage backend lifecycle

### Phase 3: Testing & Validation
- [ ] Unit tests for HTTP server endpoints
- [ ] Integration tests for SSE streaming
- [ ] Benchmark latency comparison (JSON-RPC vs HTTP)
- [ ] Test fallback to JSON-RPC when HTTP unavailable
- [ ] Test request cancellation via AbortController

### Phase 4: Documentation & Release
- [ ] Update CLAUDE.md with new architecture
- [ ] Update README with new requirements
- [ ] Add configuration option for backend preference
- [ ] Release as v1.9.0

---

## Configuration Options

Add to `package.json` contributes.configuration:

```json
{
    "ppxai.backend": {
        "type": "string",
        "enum": ["auto", "http", "jsonrpc"],
        "default": "auto",
        "description": "Backend communication method (auto = prefer HTTP with JSON-RPC fallback)"
    },
    "ppxai.httpPort": {
        "type": "number",
        "default": 8765,
        "description": "Port for HTTP backend server"
    }
}
```

---

## Rollback Plan

If issues arise with the HTTP backend:

1. Set `ppxai.backend` to `jsonrpc` in settings
2. The factory will use the legacy JSON-RPC backend
3. No code changes required for rollback

---

## Future Considerations

### WebSocket Support

For features requiring bidirectional communication (e.g., live collaboration):

```python
# ppxai/server/websocket.py (future)
from fastapi import WebSocket

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_json()
        async for event in engine.chat(data["message"]):
            await websocket.send_json({"type": event.type.value, "data": event.data})
```

### gRPC Support

For high-performance internal services:

```protobuf
// ppxai.proto (future)
service PpxaiService {
    rpc Chat(ChatRequest) returns (stream ChatEvent);
}
```

---

## References

- [Server-Sent Events Specification](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- [FastAPI StreamingResponse](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse)
- [MDN: Using Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)
- [uv Documentation](https://docs.astral.sh/uv/)
- [ppxai Architecture Document](architecture-refactoring.md)
- [ppxai uv Migration Plan](uv-migration-plan.md)
