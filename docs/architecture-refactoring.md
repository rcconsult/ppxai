# ppxai Architecture Refactoring Plan

## Overview

This document outlines the comprehensive plan to refactor ppxai into a clean, modular architecture with clear separation between:

1. **Engine** - Core business logic (providers, tools, models, sessions)
2. **Clients** - Frontend interfaces (TUI, VSCode Extension, Web UI)
3. **Configuration** - Provider and tool definitions

## Design Principles

### 1. Tool Independence
- Tools can be enhanced or updated independently from providers
- Tools are registered in a central registry
- Provider-specific tools can be conditionally loaded
- Some tools may not make sense for all providers (e.g., Perplexity has built-in search)

### 2. Provider Separation
- Each provider (Perplexity, OpenAI, Gemini, OpenRouter, Local) is isolated
- Providers loaded dynamically based on user selection
- Provider-specific capabilities are declared in configuration
- Provider can define which tools to enable/disable

### 3. Model Management
- Models listed after provider selection
- Model list comes from configuration or provider's API (if available)
- Optional: Refresh model list from provider's listing API

### 4. Client Uniformity
- All clients (TUI, VSCode, Web) use the same engine API
- Same functionality available everywhere
- Clients receive events/data, not formatted output

---

## Proposed Architecture

```
ppxai/
├── engine/                         # Core engine (no UI dependencies)
│   ├── __init__.py                 # Public API exports
│   ├── types.py                    # Shared types/dataclasses
│   ├── config.py                   # Configuration loader
│   ├── providers/                  # Provider implementations
│   │   ├── __init__.py             # Provider registry & factory
│   │   ├── base.py                 # BaseProvider abstract class
│   │   ├── perplexity.py           # Perplexity provider
│   │   ├── openai_provider.py      # OpenAI/ChatGPT provider
│   │   ├── openrouter.py           # OpenRouter provider
│   │   └── local.py                # Local models (Ollama, vLLM)
│   ├── tools/                      # Tool system
│   │   ├── __init__.py             # Tool registry
│   │   ├── base.py                 # BaseTool abstract class
│   │   ├── manager.py              # Tool manager (load/execute)
│   │   ├── builtin/                # Built-in tools
│   │   │   ├── __init__.py
│   │   │   ├── filesystem.py       # read_file, search_files, list_directory
│   │   │   ├── shell.py            # execute_shell_command
│   │   │   ├── calculator.py       # calculator
│   │   │   ├── datetime_tool.py    # get_datetime
│   │   │   └── web.py              # web_search, fetch_url, get_weather
│   │   └── mcp/                    # MCP tool integration (optional)
│   │       └── __init__.py
│   ├── session.py                  # Session management
│   ├── prompts.py                  # System prompts & templates
│   └── client.py                   # Main engine client (facade)
│
├── server/                         # Server interfaces
│   ├── __init__.py
│   ├── jsonrpc.py                  # JSON-RPC over stdio
│   ├── http.py                     # HTTP/REST server (optional)
│   └── websocket.py                # WebSocket server (optional)
│
├── tui/                            # Terminal UI client
│   ├── __init__.py
│   ├── main.py                     # TUI entry point
│   ├── ui.py                       # Rich console components
│   └── commands.py                 # Slash command handlers
│
├── ppxai.py                        # CLI entry point
└── __main__.py                     # Module entry point
```

---

## Component Details

### Engine Layer (`engine/`)

#### `engine/types.py` - Shared Types

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum

class EventType(Enum):
    STREAM_START = "stream_start"
    STREAM_CHUNK = "stream_chunk"
    STREAM_END = "stream_end"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"

@dataclass
class Message:
    role: str  # 'user', 'assistant', 'system'
    content: str

@dataclass
class UsageStats:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0

@dataclass
class ChatResponse:
    content: str
    citations: List[str] = field(default_factory=list)
    usage: Optional[UsageStats] = None

@dataclass
class Event:
    type: EventType
    data: Any = None

@dataclass
class ProviderCapabilities:
    web_search: bool = False
    web_fetch: bool = False
    weather: bool = False
    citations: bool = False
    streaming: bool = True

@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: callable
    provider_specific: Optional[List[str]] = None  # If set, only for these providers
```

#### `engine/providers/base.py` - Base Provider

```python
from abc import ABC, abstractmethod
from typing import List, Dict, AsyncIterator, Optional
from ..types import Message, ChatResponse, Event, ProviderCapabilities

class BaseProvider(ABC):
    """Abstract base class for all AI providers."""

    name: str
    capabilities: ProviderCapabilities

    @abstractmethod
    def __init__(self, api_key: str, base_url: str, **kwargs):
        pass

    @abstractmethod
    async def chat(
        self,
        messages: List[Message],
        model: str,
        stream: bool = False
    ) -> AsyncIterator[Event]:
        """Send chat request, yielding events."""
        pass

    @abstractmethod
    def list_models(self) -> List[Dict[str, str]]:
        """Return available models for this provider."""
        pass

    @abstractmethod
    def validate_config(self) -> bool:
        """Validate provider configuration."""
        pass

    def needs_tool(self, tool_category: str) -> bool:
        """Check if provider needs a tool (doesn't have native capability)."""
        return not getattr(self.capabilities, tool_category, False)
```

#### `engine/providers/__init__.py` - Provider Registry

```python
from typing import Dict, Type, Optional
from .base import BaseProvider

_providers: Dict[str, Type[BaseProvider]] = {}

def register_provider(name: str, provider_class: Type[BaseProvider]):
    """Register a provider implementation."""
    _providers[name] = provider_class

def get_provider(name: str, **kwargs) -> Optional[BaseProvider]:
    """Get an instance of a provider by name."""
    if name not in _providers:
        return None
    return _providers[name](**kwargs)

def list_providers() -> List[str]:
    """List all registered provider names."""
    return list(_providers.keys())

# Auto-register built-in providers
from .perplexity import PerplexityProvider
from .openai_provider import OpenAIProvider
from .openrouter import OpenRouterProvider
from .local import LocalProvider

register_provider("perplexity", PerplexityProvider)
register_provider("openai", OpenAIProvider)
register_provider("openrouter", OpenRouterProvider)
register_provider("local", LocalProvider)
```

#### `engine/tools/base.py` - Base Tool

```python
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List

class BaseTool(ABC):
    """Abstract base class for all tools."""

    name: str
    description: str
    parameters: Dict[str, Any]
    provider_specific: Optional[List[str]] = None  # Only for these providers (None = all)

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Execute the tool and return result."""
        pass

    def is_available_for(self, provider: str) -> bool:
        """Check if tool is available for a specific provider."""
        if self.provider_specific is None:
            return True
        return provider in self.provider_specific
```

#### `engine/tools/manager.py` - Tool Manager

```python
from typing import Dict, List, Optional, Any
from .base import BaseTool

class ToolManager:
    """Manages tool registration and execution."""

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._provider: Optional[str] = None

    def register_tool(self, tool: BaseTool):
        """Register a tool."""
        self._tools[tool.name] = tool

    def set_provider(self, provider: str):
        """Set current provider (filters available tools)."""
        self._provider = provider

    def get_available_tools(self) -> List[BaseTool]:
        """Get tools available for current provider."""
        if self._provider is None:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.is_available_for(self._provider)]

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Get a specific tool by name."""
        tool = self._tools.get(name)
        if tool and tool.is_available_for(self._provider):
            return tool
        return None

    async def execute_tool(self, name: str, **kwargs) -> str:
        """Execute a tool by name."""
        tool = self.get_tool(name)
        if not tool:
            raise ValueError(f"Tool not found or not available: {name}")
        return await tool.execute(**kwargs)

    def get_tools_prompt(self) -> str:
        """Generate system prompt describing available tools."""
        # ... generates prompt for current provider's available tools
```

#### `engine/client.py` - Main Engine Client (Facade)

```python
from typing import List, AsyncIterator, Optional, Dict, Any
from .types import Message, Event, EventType, ChatResponse
from .providers import get_provider
from .tools.manager import ToolManager
from .session import SessionManager
from .config import load_config

class EngineClient:
    """Main engine client - the facade for all engine functionality.

    This is the primary interface for all frontends (TUI, VSCode, Web).
    """

    def __init__(self):
        self.provider = None
        self.provider_name: str = ""
        self.model: str = ""
        self.tool_manager = ToolManager()
        self.session_manager = SessionManager()
        self.tools_enabled: bool = False
        self.config = load_config()

    # === Provider Management ===

    def set_provider(self, provider_name: str) -> bool:
        """Switch to a different provider."""
        config = self.config.get_provider(provider_name)
        if not config:
            return False

        self.provider = get_provider(
            provider_name,
            api_key=config['api_key'],
            base_url=config['base_url']
        )
        self.provider_name = provider_name
        self.tool_manager.set_provider(provider_name)
        return True

    def list_providers(self) -> List[Dict[str, Any]]:
        """List available providers with their status."""
        return self.config.list_providers()

    # === Model Management ===

    def set_model(self, model_id: str) -> bool:
        """Set the current model."""
        models = self.list_models()
        if any(m['id'] == model_id for m in models):
            self.model = model_id
            return True
        return False

    def list_models(self) -> List[Dict[str, str]]:
        """List available models for current provider."""
        if not self.provider:
            return []
        return self.provider.list_models()

    async def refresh_models(self) -> List[Dict[str, str]]:
        """Refresh model list from provider API (if supported)."""
        if hasattr(self.provider, 'fetch_models'):
            return await self.provider.fetch_models()
        return self.list_models()

    # === Tool Management ===

    def enable_tools(self) -> bool:
        """Enable tool support."""
        self.tools_enabled = True
        return True

    def disable_tools(self) -> bool:
        """Disable tool support."""
        self.tools_enabled = False
        return True

    def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools for current provider."""
        return [
            {"name": t.name, "description": t.description}
            for t in self.tool_manager.get_available_tools()
        ]

    def set_tool_config(self, setting: str, value: Any) -> bool:
        """Configure tool settings."""
        if setting == "max_iterations":
            self.tool_manager.max_iterations = int(value)
            return True
        return False

    # === Chat ===

    async def chat(
        self,
        message: str,
        stream: bool = True
    ) -> AsyncIterator[Event]:
        """Send a chat message, yielding events.

        Events include:
        - STREAM_START: Chat started
        - STREAM_CHUNK: Partial response (for streaming)
        - TOOL_CALL: Tool being called
        - TOOL_RESULT: Tool result
        - STREAM_END: Final response
        - ERROR: Error occurred
        """
        if not self.provider:
            yield Event(EventType.ERROR, "No provider configured")
            return

        # Add message to history
        self.session_manager.add_message(Message("user", message))

        if self.tools_enabled:
            async for event in self._chat_with_tools(message, stream):
                yield event
        else:
            async for event in self._chat_simple(message, stream):
                yield event

    async def _chat_simple(self, message: str, stream: bool) -> AsyncIterator[Event]:
        """Simple chat without tools."""
        messages = self.session_manager.get_messages()
        async for event in self.provider.chat(messages, self.model, stream):
            yield event
            if event.type == EventType.STREAM_END:
                self.session_manager.add_message(Message("assistant", event.data))

    async def _chat_with_tools(self, message: str, stream: bool) -> AsyncIterator[Event]:
        """Chat with tool support."""
        # Build messages with tool prompt
        messages = self.session_manager.get_messages()
        tool_prompt = self.tool_manager.get_tools_prompt()
        # ... tool calling loop with max_iterations

    # === Coding Tasks ===

    async def coding_task(
        self,
        task_type: str,
        content: str,
        language: Optional[str] = None,
        filename: Optional[str] = None
    ) -> AsyncIterator[Event]:
        """Execute a coding task (explain, test, docs, debug, implement)."""
        # ... similar to chat but with coding prompts

    # === Session Management ===

    def save_session(self, name: Optional[str] = None) -> str:
        """Save current session, return session name."""
        return self.session_manager.save(name)

    def load_session(self, name: str) -> bool:
        """Load a saved session."""
        return self.session_manager.load(name)

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List saved sessions."""
        return self.session_manager.list_sessions()

    def clear_history(self):
        """Clear conversation history."""
        self.session_manager.clear()

    def get_usage(self) -> Dict[str, Any]:
        """Get usage statistics."""
        return self.session_manager.get_usage()

    # === Status ===

    def get_status(self) -> Dict[str, Any]:
        """Get current engine status."""
        return {
            "provider": self.provider_name,
            "model": self.model,
            "tools_enabled": self.tools_enabled,
            "tool_count": len(self.tool_manager.get_available_tools()),
            "has_api_key": self.provider is not None
        }
```

---

### Server Layer (`server/`)

The server layer provides multiple transport options for client communication:

#### Transport Options

| Transport | File | Use Case | Status |
|-----------|------|----------|--------|
| JSON-RPC/stdio | `jsonrpc.py` | Legacy, subprocess | ✅ Implemented |
| **HTTP + SSE** | `http.py` | **Recommended**, low latency | 🚧 Planned |
| WebSocket | `websocket.py` | Bidirectional, real-time | 📋 Optional |

#### `server/http.py` - HTTP Server with SSE (Recommended)

**Why SSE over JSON-RPC?** See [docs/sse-migration-plan.md](sse-migration-plan.md) for detailed analysis.

| Metric | JSON-RPC/stdio | HTTP + SSE |
|--------|----------------|------------|
| First token latency | 50-200ms | 10-30ms |
| Per-request overhead | JSON parse + asyncio.run | Native async |
| Reconnection | Manual | Built-in |
| Cancellation | Kill process | AbortController |
| Debug tooling | Custom | Browser DevTools |

```python
"""HTTP server with SSE streaming for ppxai engine."""
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import json

from ..engine import EngineClient, EventType

app = FastAPI()

@app.post("/chat")
async def chat(request: Request):
    """Chat endpoint with Server-Sent Events streaming."""
    body = await request.json()
    message = body.get("message", "")

    async def generate():
        async for event in request.app.state.engine.chat(message, stream=True):
            data = {"type": event.type.value, "data": event.data}
            yield f"data: {json.dumps(data)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

# REST endpoints for configuration
@app.get("/providers")
async def get_providers(request: Request):
    return [{"id": p.id, "name": p.name, "has_api_key": p.has_api_key}
            for p in request.app.state.engine.list_providers()]

@app.post("/provider")
async def set_provider(request: Request):
    body = await request.json()
    return {"success": request.app.state.engine.set_provider(body["provider"])}

@app.get("/status")
async def get_status(request: Request):
    return request.app.state.engine.get_status()
```

#### `server/jsonrpc.py` - JSON-RPC Server (Legacy)

Retained for backward compatibility with existing integrations.

```python
"""JSON-RPC 2.0 server over stdio.

Provides the same EngineClient functionality over JSON-RPC,
enabling integration with VSCode extension and other clients.

NOTE: For new integrations, prefer HTTP + SSE (server/http.py)
for better performance. See docs/sse-migration-plan.md.
"""

import json
import sys
import asyncio
from typing import Dict, Any
from ..engine.client import EngineClient
from ..engine.types import EventType

class JsonRpcServer:
    def __init__(self):
        self.engine = EngineClient()
        self.methods = {
            # Provider
            "set_provider": self._set_provider,
            "list_providers": self._list_providers,
            # Model
            "set_model": self._set_model,
            "list_models": self._list_models,
            "refresh_models": self._refresh_models,
            # Tools
            "enable_tools": self._enable_tools,
            "disable_tools": self._disable_tools,
            "list_tools": self._list_tools,
            "set_tool_config": self._set_tool_config,
            # Chat
            "chat": self._chat,
            "coding_task": self._coding_task,
            # Session
            "save_session": self._save_session,
            "load_session": self._load_session,
            "list_sessions": self._list_sessions,
            "clear_history": self._clear_history,
            "get_usage": self._get_usage,
            # Status
            "get_status": self._get_status,
        }

    async def _chat(self, message: str, stream: bool = True) -> Dict[str, Any]:
        """Handle chat request, sending stream events if requested."""
        events = []
        async for event in self.engine.chat(message, stream):
            if stream:
                self._send_stream_event(event)
            events.append(event)

        # Return final response
        final = next((e for e in reversed(events) if e.type == EventType.STREAM_END), None)
        return {"content": final.data if final else ""}

    def _send_stream_event(self, event):
        """Send streaming event to stdout."""
        print(json.dumps({
            "type": "stream",
            "event": event.type.value,
            "data": event.data
        }), flush=True)

    def run(self):
        """Main server loop."""
        print(json.dumps({"type": "ready"}), flush=True)

        for line in sys.stdin:
            request = json.loads(line.strip())
            response = asyncio.run(self.handle_request(request))
            print(json.dumps(response), flush=True)
```

---

### TUI Layer (`tui/`)

The TUI consumes events from EngineClient and renders them using Rich:

```python
# tui/main.py
from ..engine.client import EngineClient
from ..engine.types import EventType
from .ui import render_chunk, render_tool_call, render_error

async def main():
    engine = EngineClient()

    # Provider selection
    providers = engine.list_providers()
    selected = select_provider(providers)
    engine.set_provider(selected)

    # Model selection
    models = engine.list_models()
    selected = select_model(models)
    engine.set_model(selected)

    # Main loop
    while True:
        user_input = prompt("You: ")

        async for event in engine.chat(user_input):
            if event.type == EventType.STREAM_CHUNK:
                render_chunk(event.data)
            elif event.type == EventType.TOOL_CALL:
                render_tool_call(event.data)
            elif event.type == EventType.TOOL_RESULT:
                render_tool_result(event.data)
            elif event.type == EventType.ERROR:
                render_error(event.data)
            elif event.type == EventType.STREAM_END:
                render_complete(event.data)
```

---

## Configuration System

### `ppxai-config.json` Structure

```json
{
  "providers": {
    "perplexity": {
      "name": "Perplexity AI",
      "base_url": "https://api.perplexity.ai",
      "api_key_env": "PERPLEXITY_API_KEY",
      "capabilities": {
        "web_search": true,
        "web_fetch": true,
        "citations": true
      },
      "default_model": "sonar-pro",
      "coding_model": "sonar-pro",
      "models": {
        "sonar-pro": {"name": "Sonar Pro", "description": "Best for complex queries"},
        "sonar": {"name": "Sonar", "description": "Fast general-purpose"}
      },
      "tools": {
        "disabled": ["web_search", "fetch_url"]
      }
    },
    "openai": {
      "name": "OpenAI",
      "base_url": "https://api.openai.com/v1",
      "api_key_env": "OPENAI_API_KEY",
      "capabilities": {
        "web_search": false,
        "web_fetch": false
      },
      "default_model": "gpt-4o",
      "models": {
        "gpt-4o": {"name": "GPT-4o", "description": "Most capable"},
        "gpt-4o-mini": {"name": "GPT-4o Mini", "description": "Fast and efficient"}
      },
      "tools": {
        "enabled": ["all"]
      }
    },
    "custom": {
      "name": "Custom Provider",
      "base_url": "${CUSTOM_BASE_URL}",
      "api_key_env": "CUSTOM_API_KEY",
      "capabilities": {},
      "tools": {
        "enabled": ["all"],
        "additional": ["custom_tool_x"]
      }
    }
  },
  "tools": {
    "global_max_iterations": 15,
    "custom_tools_dir": "~/.ppxai/tools/"
  }
}
```

---

## Implementation Phases

### Phase 1: Create Engine Types & Structure ✅
- Create `engine/types.py` with all shared types
- Create `engine/providers/base.py` abstract class
- Create `engine/tools/base.py` abstract class
- Create directory structure

### Phase 2: Refactor Providers ✅
- Extract `PerplexityProvider` from current client
- Extract `OpenAIProvider` (generic OpenAI-compatible)
- Create provider registry

### Phase 3: Refactor Tools ✅
- Move tool definitions to `engine/tools/builtin/`
- Create `ToolManager` with provider-aware filtering
- Remove Rich console dependencies from tool execution

### Phase 4: Create Engine Client ✅
- Implement `EngineClient` facade
- Event-based output (no console printing)
- Async iterators for streaming

### Phase 5: Update Server ✅
- Refactor `server.py` to use `EngineClient`
- All methods delegate to engine
- Stream events via JSON

### Phase 6: Update TUI ✅
- Refactor TUI to consume events from `EngineClient`
- All Rich rendering in TUI layer only

### Phase 7: Update VSCode Extension ✅
- Connect to JSON-RPC server
- Remove duplicate TypeScript AI client
- Use Python backend for all functionality

### Phase 8: HTTP + SSE Migration 🚧
**Goal:** Replace JSON-RPC/stdio with HTTP + SSE for improved streaming performance.

See [docs/sse-migration-plan.md](sse-migration-plan.md) for detailed implementation plan.

**Summary:**
1. Add FastAPI + uvicorn dependencies
2. Create `ppxai/server/http.py` with SSE streaming
3. Create `vscode-extension/src/backend-http.ts` with fetch/SSE client
4. Add server lifecycle management to extension
5. Implement automatic fallback to JSON-RPC
6. Benchmark and validate performance improvements

**Expected Improvements:**
- First token latency: 50-200ms → 10-30ms
- Native request cancellation via AbortController
- Built-in SSE reconnection
- Standard HTTP debugging tools

---

## Benefits

1. **Single Source of Truth**: All AI logic in engine layer
2. **Tool Independence**: Tools updated without touching providers
3. **Provider Flexibility**: Easy to add new providers
4. **Client Uniformity**: TUI, VSCode, Web all use same API
5. **Testability**: Engine layer can be tested without UI
6. **Maintainability**: Clear separation of concerns

---

## Migration Path

1. Keep existing code working during refactoring
2. Create new `engine/` alongside existing `ppxai/`
3. Gradually move functionality to engine
4. Update clients one at a time
5. Remove old code once migration complete

---

## Related Files

- Current implementation: `ppxai/client.py`, `perplexity_tools_prompt_based.py`
- Current config: `ppxai/config.py`
- Current server: `ppxai/server.py`
- VSCode Extension: `vscode-extension/`
