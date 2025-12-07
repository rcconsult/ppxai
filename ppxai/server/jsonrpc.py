"""
JSON-RPC 2.0 server over stdio using EngineClient.

This server provides the same functionality as the old server.py but uses
the new EngineClient facade, enabling tools and unified behavior across
all frontends.
"""

import asyncio
import json
import sys
import traceback
from typing import Any, Callable, Dict, Optional

from ..engine import EngineClient, EventType
from ..prompts import CODING_PROMPTS


class JsonRpcServer:
    """JSON-RPC 2.0 server over stdio using EngineClient.

    Provides identical functionality to the old server.py but uses
    the new engine layer for all operations.
    """

    def __init__(self):
        """Initialize the server with EngineClient."""
        self.engine = EngineClient()
        self.methods: Dict[str, Callable] = {}

        # Initialize with default provider
        self._init_engine()

        # Register RPC methods
        self._register_methods()

    def _init_engine(self):
        """Initialize the engine with default provider."""
        providers = self.engine.list_providers()

        # Try to find a provider with API key
        for provider in providers:
            if provider.has_api_key:
                self.engine.set_provider(provider.id)
                break

    def _register_methods(self):
        """Register all RPC methods."""
        self.methods = {
            # Chat
            "chat": self.chat,
            "coding_task": self.coding_task,
            # Provider
            "get_providers": self.get_providers,
            "set_provider": self.set_provider,
            # Model
            "get_models": self.get_models,
            "set_model": self.set_model,
            # Tools
            "enable_tools": self.enable_tools,
            "disable_tools": self.disable_tools,
            "list_tools": self.list_tools,
            "get_tools_status": self.get_tools_status,
            "set_tool_config": self.set_tool_config,
            # Context injection
            "set_working_dir": self.set_working_dir,
            "set_auto_inject": self.set_auto_inject,
            "get_auto_inject": self.get_auto_inject,
            # Session
            "get_sessions": self.get_sessions,
            "load_session": self.load_session,
            "save_session": self.save_session,
            "get_history": self.get_history,
            "clear_history": self.clear_history,
            "get_usage": self.get_usage,
            # Status
            "get_status": self.get_status,
        }

    # === Chat Methods ===

    def chat(self, message: str, context: Optional[Dict] = None, stream: bool = False) -> str:
        """Send a chat message.

        Args:
            message: User message
            context: Optional context with code snippet
            stream: Whether to stream (handled via events)

        Returns:
            Assistant response
        """
        # Build message with optional context
        full_message = message
        if context:
            if context.get("code"):
                lang = context.get("language", "")
                full_message = f"{message}\n\n```{lang}\n{context['code']}\n```"

        # Use sync method for simplicity
        return self.engine.chat_sync(full_message, stream=stream)

    async def chat_async(self, message: str, context: Optional[Dict] = None, stream: bool = False) -> str:
        """Async chat with streaming support."""
        full_message = message
        if context and context.get("code"):
            lang = context.get("language", "")
            full_message = f"{message}\n\n```{lang}\n{context['code']}\n```"

        result = ""
        async for event in self.engine.chat(full_message, stream=stream):
            if stream and event.type == EventType.STREAM_CHUNK:
                # Send streaming event
                pass  # Handled by _handle_streaming_request
            elif event.type == EventType.STREAM_END:
                result = event.data
            elif event.type == EventType.ERROR:
                raise RuntimeError(event.data)

        return result

    def coding_task(
        self,
        task_type: str,
        content: str,
        language: Optional[str] = None,
        filename: Optional[str] = None,
        stream: bool = False
    ) -> str:
        """Execute a coding task.

        Args:
            task_type: Task type (explain, test, docs, debug, implement)
            content: Code or content to process
            language: Programming language
            filename: Source filename
            stream: Whether to stream

        Returns:
            Result of coding task
        """
        if task_type not in CODING_PROMPTS:
            raise ValueError(f"Unknown task type: {task_type}")

        # Build the prompt
        system_prompt = CODING_PROMPTS[task_type]

        # Build user message based on task type
        if task_type == "explain":
            user_message = f"Explain this code:\n\n```{language or ''}\n{content}\n```"
        elif task_type == "test":
            user_message = f"Generate unit tests for this code:\n\n```{language or ''}\n{content}\n```"
        elif task_type == "docs":
            user_message = f"Generate documentation for this code:\n\n```{language or ''}\n{content}\n```"
        elif task_type == "debug":
            user_message = f"Debug this error:\n\n{content}"
        elif task_type == "implement":
            user_message = f"Implement the following in {language or 'Python'}:\n\n{content}"
        else:
            user_message = content

        if filename:
            user_message = f"File: {filename}\n\n{user_message}"

        # Combine with system prompt
        full_message = f"{system_prompt}\n\n{user_message}"

        return self.engine.chat_sync(full_message, stream=stream)

    # === Provider Methods ===

    def get_providers(self) -> list:
        """Get list of available providers."""
        providers = self.engine.list_providers()
        return [
            {
                "id": p.id,
                "name": p.name,
                "has_api_key": p.has_api_key
            }
            for p in providers
        ]

    def set_provider(self, provider: str) -> bool:
        """Switch to a different provider."""
        return self.engine.set_provider(provider)

    # === Model Methods ===

    def get_models(self) -> list:
        """Get list of models for current provider."""
        models = self.engine.list_models()
        return [
            {
                "id": m.id,
                "name": m.name,
                "description": m.description
            }
            for m in models
        ]

    def set_model(self, model: str) -> bool:
        """Switch to a different model."""
        return self.engine.set_model(model)

    # === Tool Methods ===

    def enable_tools(self) -> bool:
        """Enable AI tools."""
        return self.engine.enable_tools()

    def disable_tools(self) -> bool:
        """Disable AI tools."""
        return self.engine.disable_tools()

    def list_tools(self) -> list:
        """List available tools."""
        return self.engine.list_tools()

    def get_tools_status(self) -> dict:
        """Get tools status."""
        return self.engine.get_tools_status()

    def set_tool_config(self, setting: str, value: Any) -> bool:
        """Configure tool settings."""
        return self.engine.set_tool_config(setting, value)

    # === Context Injection Methods ===

    def set_working_dir(self, path: str) -> bool:
        """Set working directory for file path resolution."""
        self.engine.set_working_dir(path)
        return True

    def set_auto_inject(self, enabled: bool) -> bool:
        """Enable or disable automatic context injection."""
        return self.engine.set_auto_inject(enabled)

    def get_auto_inject(self) -> bool:
        """Check if auto-injection is enabled."""
        return self.engine.get_auto_inject()

    # === Session Methods ===

    def get_sessions(self) -> list:
        """Get list of saved sessions."""
        sessions = self.engine.list_sessions()
        return [
            {
                "name": s.name,
                "created_at": s.created_at,
                "provider": s.provider,
                "model": s.model,
                "message_count": s.message_count
            }
            for s in sessions
        ]

    def load_session(self, session_name: str) -> bool:
        """Load a saved session."""
        return self.engine.load_session(session_name)

    def save_session(self) -> str:
        """Save current session."""
        return self.engine.save_session()

    def get_history(self) -> list:
        """Get conversation history."""
        return self.engine.get_history()

    def clear_history(self) -> bool:
        """Clear conversation history."""
        self.engine.clear_history()
        return True

    def get_usage(self) -> dict:
        """Get usage statistics."""
        return self.engine.get_usage()

    # === Status ===

    def get_status(self) -> dict:
        """Get current engine status."""
        return self.engine.get_status()

    # === Request Handling ===

    def handle_request(self, request: Dict) -> Dict:
        """Handle a JSON-RPC request."""
        request_id = request.get("id")
        method_name = request.get("method")
        params = request.get("params", {})

        try:
            if method_name not in self.methods:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method_name}"
                    }
                }

            method = self.methods[method_name]

            # Handle streaming requests
            if params.get("stream"):
                return asyncio.run(self._handle_streaming_request(request_id, method_name, params))

            # Regular request
            if isinstance(params, dict):
                params.pop("stream", None)
                result = method(**params)
            else:
                result = method(params)

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }

        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32000,
                    "message": str(e)
                }
            }

    async def _handle_streaming_request(self, request_id: int, method_name: str, params: Dict) -> Dict:
        """Handle a streaming request."""
        try:
            if method_name == "chat":
                message = params.get("message", "")
                context = params.get("context")

                full_message = message
                if context and context.get("code"):
                    lang = context.get("language", "")
                    full_message = f"{message}\n\n```{lang}\n{context['code']}\n```"

                # Send thinking event immediately
                self._send_stream_event(request_id, "thinking", "Processing request...")

                full_response = ""
                async for event in self.engine.chat(full_message, stream=True):
                    if event.type == EventType.CONTEXT_INJECTED:
                        # File content was auto-injected
                        self._send_stream_event(request_id, "context_injected", json.dumps(event.data))
                    elif event.type == EventType.STREAM_START:
                        # API call started, waiting for first token
                        self._send_stream_event(request_id, "started", "Waiting for response...")
                    elif event.type == EventType.STREAM_CHUNK:
                        self._send_stream_event(request_id, "chunk", event.data)
                    elif event.type == EventType.TOOL_CALL:
                        self._send_stream_event(request_id, "tool_call", json.dumps(event.data))
                    elif event.type == EventType.TOOL_RESULT:
                        self._send_stream_event(request_id, "tool_result", json.dumps(event.data))
                    elif event.type == EventType.STREAM_END:
                        full_response = event.data
                    elif event.type == EventType.ERROR:
                        self._send_stream_event(request_id, "error", event.data)
                        raise RuntimeError(event.data)

                self._send_stream_event(request_id, "done")

                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": full_response
                }

            elif method_name == "coding_task":
                # For coding tasks, use non-streaming for now
                params.pop("stream", None)
                result = self.coding_task(**params)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }

            else:
                # Non-streamable method
                params.pop("stream", None)
                method = self.methods[method_name]
                result = method(**params)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result
                }

        except Exception as e:
            self._send_stream_event(request_id, "error", str(e))
            raise

    def _send_stream_event(self, request_id: int, event_type: str, content: str = ""):
        """Send a streaming event to stdout."""
        event = {
            "type": "stream",
            "id": request_id,
            "event": {
                "type": event_type,
                "content": content
            }
        }
        print(json.dumps(event), flush=True)

    def run(self):
        """Run the server, reading JSON-RPC requests from stdin."""
        # Signal ready
        print(json.dumps({"type": "ready"}), flush=True)

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
                response = self.handle_request(request)
                print(json.dumps(response), flush=True)
            except json.JSONDecodeError as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": f"Parse error: {e}"
                    }
                }
                print(json.dumps(error_response), flush=True)


def main():
    """Main entry point for the JSON-RPC server."""
    server = JsonRpcServer()
    server.run()


if __name__ == "__main__":
    main()
