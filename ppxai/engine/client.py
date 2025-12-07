"""
Engine Client - Main facade for the ppxai engine.

This is the primary interface for all frontends (TUI, VSCode, Web).
It has no UI dependencies and communicates via events.
"""

import json
import re
from typing import List, AsyncIterator, Optional, Dict, Any
from pathlib import Path

from .types import (
    Message, Event, EventType, UsageStats,
    ProviderInfo, ModelInfo, SessionInfo, ProviderCapabilities
)
from .providers import create_provider, list_registered_providers
from .providers.base import BaseProvider
from .tools.manager import ToolManager
from .tools.builtin import register_all_builtin_tools
from .session import SessionManager
from .context import ContextInjector


class EngineClient:
    """Main engine client - the facade for all engine functionality.

    This is the primary interface for all frontends (TUI, VSCode, Web).
    All communication is via events and data structures, never direct console output.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the engine client.

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        self.provider: Optional[BaseProvider] = None
        self.provider_name: str = ""
        self.model: str = ""

        self.tool_manager = ToolManager()
        self.session = SessionManager()
        self.tools_enabled: bool = False

        # Context injection for automatic file content inclusion
        self.context_injector = ContextInjector()
        self.auto_inject_context: bool = True  # Enabled by default

        # Load configuration
        self._load_config()

    def _load_config(self):
        """Load configuration from ppxai-config.json and .env."""
        # Import from existing config module to reuse configuration loading
        try:
            from ..config import (
                PROVIDERS,
                get_api_key,
                get_base_url,
                get_default_model,
                MODEL_PROVIDER,
            )
            self._providers_config = PROVIDERS
            self._get_api_key = get_api_key
            self._get_base_url = get_base_url
            self._get_default_model = get_default_model
            self._default_provider = MODEL_PROVIDER
        except ImportError:
            # Fallback if old config not available
            self._providers_config = {}
            self._get_api_key = lambda p: None
            self._get_base_url = lambda p: None
            self._get_default_model = lambda: None
            self._default_provider = "perplexity"

    # === Context Injection ===

    def set_working_dir(self, path: str):
        """Set working directory for file path resolution.

        Args:
            path: Working directory path
        """
        self.context_injector.set_working_dir(path)

    def set_auto_inject(self, enabled: bool) -> bool:
        """Enable or disable automatic context injection.

        Args:
            enabled: Whether to enable auto-injection

        Returns:
            True (always succeeds)
        """
        self.auto_inject_context = enabled
        return True

    def get_auto_inject(self) -> bool:
        """Check if auto-injection is enabled.

        Returns:
            True if enabled
        """
        return self.auto_inject_context

    # === Provider Management ===

    def set_provider(self, provider_name: str) -> bool:
        """Switch to a different provider.

        Args:
            provider_name: Provider ID (e.g., 'perplexity', 'openai')

        Returns:
            True if provider was set successfully
        """
        if provider_name not in self._providers_config:
            return False

        api_key = self._get_api_key(provider_name)
        if not api_key:
            return False

        base_url = self._get_base_url(provider_name)
        provider_config = self._providers_config[provider_name]

        # Parse capabilities from config
        caps_dict = provider_config.get("capabilities", {})
        capabilities = ProviderCapabilities.from_dict(caps_dict)

        # Create provider instance
        self.provider = create_provider(
            provider_name,
            api_key=api_key,
            base_url=base_url,
            models=provider_config.get("models", {}),
            capabilities=capabilities
        )

        if self.provider is None:
            # Fallback to generic OpenAI-compatible provider
            from .providers.openai_compat import OpenAICompatibleProvider
            self.provider = OpenAICompatibleProvider(
                api_key=api_key,
                base_url=base_url,
                models=provider_config.get("models", {}),
                capabilities=capabilities
            )

        self.provider_name = provider_name
        self.tool_manager.set_provider(provider_name)
        self.session.set_provider(provider_name)

        # Set default model for this provider
        default_model = provider_config.get("default_model")
        if default_model:
            self.set_model(default_model)

        return True

    def list_providers(self) -> List[ProviderInfo]:
        """List available providers with their status.

        Returns:
            List of ProviderInfo objects
        """
        providers = []
        for provider_id, config in self._providers_config.items():
            has_key = bool(self._get_api_key(provider_id))
            caps_dict = config.get("capabilities", {})

            providers.append(ProviderInfo(
                id=provider_id,
                name=config.get("name", provider_id),
                base_url=config.get("base_url", ""),
                api_key_env=config.get("api_key_env", ""),
                has_api_key=has_key,
                capabilities=ProviderCapabilities.from_dict(caps_dict),
                default_model=config.get("default_model", ""),
                coding_model=config.get("coding_model")
            ))

        return providers

    def get_current_provider(self) -> Optional[str]:
        """Get the current provider name.

        Returns:
            Provider name or None
        """
        return self.provider_name if self.provider else None

    # === Model Management ===

    def set_model(self, model_id: str) -> bool:
        """Set the current model.

        Args:
            model_id: Model ID to use

        Returns:
            True if model was set successfully
        """
        if not self.provider:
            return False

        models = self.provider.list_models()
        if any(m.id == model_id for m in models):
            self.model = model_id
            self.session.set_model(model_id)
            return True

        # Allow setting model even if not in list (for flexibility)
        self.model = model_id
        self.session.set_model(model_id)
        return True

    def list_models(self) -> List[ModelInfo]:
        """List available models for current provider.

        Returns:
            List of ModelInfo objects
        """
        if not self.provider:
            return []
        return self.provider.list_models()

    def get_current_model(self) -> Optional[str]:
        """Get the current model.

        Returns:
            Model ID or None
        """
        return self.model if self.model else None

    # === Tool Management ===

    def enable_tools(self) -> bool:
        """Enable tool support.

        Returns:
            True if tools were enabled
        """
        if not self.tools_enabled:
            # Register all built-in tools
            register_all_builtin_tools(self.tool_manager, self.provider_name)
            self.tools_enabled = True
        return True

    def disable_tools(self) -> bool:
        """Disable tool support.

        Returns:
            True if tools were disabled
        """
        self.tools_enabled = False
        self.tool_manager.clear()
        return True

    def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools for current provider.

        Returns:
            List of tool info dicts
        """
        return self.tool_manager.list_tools()

    def set_tool_config(self, setting: str, value: Any) -> bool:
        """Configure tool settings.

        Args:
            setting: Setting name (e.g., 'max_iterations')
            value: Setting value

        Returns:
            True if setting was applied
        """
        if setting == "max_iterations":
            self.tool_manager.max_iterations = int(value)
            return True
        return False

    def get_tools_status(self) -> Dict[str, Any]:
        """Get tools status.

        Returns:
            Dictionary with tools status
        """
        return {
            "enabled": self.tools_enabled,
            "tool_count": len(self.tool_manager.list_tools()) if self.tools_enabled else 0,
            "max_iterations": self.tool_manager.max_iterations
        }

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
        - CONTEXT_INJECTED: File content was auto-injected
        - TOOL_CALL: Tool being called
        - TOOL_RESULT: Tool result
        - STREAM_END: Final response
        - ERROR: Error occurred

        Args:
            message: User message
            stream: Whether to stream the response

        Yields:
            Event objects
        """
        if not self.provider:
            yield Event(EventType.ERROR, "No provider configured")
            return

        if not self.model:
            yield Event(EventType.ERROR, "No model selected")
            return

        # Auto-inject file context if enabled
        injected_contexts = []

        if self.auto_inject_context:
            message, injected_contexts = self.context_injector.inject_context(message)

            # Emit events for each injected file
            for ctx in injected_contexts:
                yield Event(EventType.CONTEXT_INJECTED, {
                    'source': ctx.source,
                    'language': ctx.language,
                    'truncated': ctx.truncated,
                    'size': ctx.size
                })

        # Add message to history (with injected content)
        self.session.add_message(Message("user", message))

        if self.tools_enabled:
            async for event in self._chat_with_tools(stream):
                yield event
        else:
            async for event in self._chat_simple(stream):
                yield event

    async def _chat_simple(self, stream: bool) -> AsyncIterator[Event]:
        """Simple chat without tools."""
        messages = self.session.get_messages()

        async for event in self.provider.chat(messages, self.model, stream):
            yield event

            # Track final response
            if event.type == EventType.STREAM_END:
                self.session.add_message(Message("assistant", event.data))
                if event.metadata and event.metadata.get("usage"):
                    self.session.update_usage(event.metadata["usage"])

    async def _chat_with_tools(self, stream: bool) -> AsyncIterator[Event]:
        """Chat with tool support."""
        iteration = 0
        max_iterations = self.tool_manager.max_iterations

        while iteration < max_iterations:
            iteration += 1

            # Build messages with tool prompt
            messages = self.session.get_messages()

            # Add system message with tool prompt
            tool_prompt = self.tool_manager.get_tools_prompt()
            if tool_prompt:
                messages = [Message("system", tool_prompt)] + messages

            # Get response from provider
            full_response = ""
            async for event in self.provider.chat(messages, self.model, stream=False):
                if event.type == EventType.ERROR:
                    yield event
                    return
                elif event.type == EventType.STREAM_END:
                    full_response = event.data

            # Check for tool call
            tool_call = self._parse_tool_call(full_response)

            if tool_call:
                tool_name = tool_call["tool"]
                tool_args = tool_call.get("arguments", {})

                yield Event(EventType.TOOL_CALL, {
                    "tool": tool_name,
                    "arguments": tool_args
                })

                # Execute tool
                try:
                    result = await self.tool_manager.execute_tool(tool_name, **tool_args)
                    yield Event(EventType.TOOL_RESULT, {
                        "tool": tool_name,
                        "result": result[:500] + "..." if len(result) > 500 else result
                    })

                    # Add to conversation history
                    self.session.add_message(Message(
                        "assistant",
                        f"[Tool Call: {tool_name}]\n```json\n{json.dumps(tool_call, indent=2)}\n```"
                    ))
                    self.session.add_message(Message(
                        "user",
                        f"[Tool Result for {tool_name}]\n```\n{result}\n```\n\nNow provide your final answer based on this result."
                    ))

                except Exception as e:
                    error_msg = str(e)
                    yield Event(EventType.TOOL_ERROR, {
                        "tool": tool_name,
                        "error": error_msg
                    })

                    self.session.add_message(Message(
                        "assistant",
                        f"[Tool Call: {tool_name}]\n```json\n{json.dumps(tool_call, indent=2)}\n```"
                    ))
                    self.session.add_message(Message(
                        "user",
                        f"[Tool Error]\n{error_msg}\n\nPlease provide an answer without using that tool."
                    ))

                # Continue loop for next iteration
                continue

            else:
                # No tool call - this is the final response
                if stream:
                    # Re-request with streaming for final response
                    async for event in self.provider.chat(messages, self.model, stream=True):
                        yield event
                        if event.type == EventType.STREAM_END:
                            self.session.add_message(Message("assistant", event.data))
                else:
                    self.session.add_message(Message("assistant", full_response))
                    yield Event(EventType.STREAM_END, full_response)

                return

        # Max iterations reached
        yield Event(EventType.INFO, "Maximum tool iterations reached")
        self.session.add_message(Message(
            "assistant",
            "[Tool iterations limit reached. Please try again with a simpler query.]"
        ))

    def _parse_tool_call(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse a tool call from model response.

        Args:
            text: Model response text

        Returns:
            Tool call dict with 'tool' and 'arguments' keys, or None
        """
        def normalize_tool_call(data: dict) -> Optional[dict]:
            if "tool" not in data:
                return None
            tool_name = data["tool"]

            tool = self.tool_manager.get_tool(tool_name)
            if not tool:
                return None

            if "arguments" in data:
                return data

            # Model put parameters at top level
            expected_params = set(tool.parameters.get("properties", {}).keys())
            arguments = {}
            for key, value in data.items():
                if key != "tool" and key in expected_params:
                    arguments[key] = value

            if arguments:
                return {"tool": tool_name, "arguments": arguments}

            return None

        # Try entire response as JSON first (most common case for tool calls)
        text_stripped = text.strip()
        if text_stripped.startswith('{') and text_stripped.endswith('}'):
            try:
                data = json.loads(text_stripped)
                normalized = normalize_tool_call(data)
                if normalized:
                    return normalized
            except json.JSONDecodeError:
                pass

        # Try JSON in code blocks - use greedy match for nested braces
        code_block_pattern = r'```(?:json)?\s*(\{[\s\S]*?\})\s*```'
        matches = re.findall(code_block_pattern, text)

        for match in matches:
            # Try to parse, and if it fails due to incomplete JSON, expand the match
            try:
                data = json.loads(match)
                normalized = normalize_tool_call(data)
                if normalized:
                    return normalized
            except json.JSONDecodeError:
                continue

        # Try to find JSON objects with "tool" key using a more robust approach
        # Look for complete JSON objects by counting braces
        start_idx = 0
        while True:
            start = text.find('{"tool"', start_idx)
            if start == -1:
                break

            # Find matching closing brace
            depth = 0
            end = start
            for i, char in enumerate(text[start:], start):
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break

            if depth == 0 and end > start:
                json_str = text[start:end]
                try:
                    data = json.loads(json_str)
                    normalized = normalize_tool_call(data)
                    if normalized:
                        return normalized
                except json.JSONDecodeError:
                    pass

            start_idx = end if end > start else start + 1

        return None

    def chat_sync(self, message: str, stream: bool = False) -> str:
        """Synchronous chat that returns just the content.

        Args:
            message: User message
            stream: Whether to stream (ignored, always non-streaming)

        Returns:
            Assistant response content
        """
        import asyncio

        result = ""

        async def run():
            nonlocal result
            async for event in self.chat(message, stream=False):
                if event.type == EventType.STREAM_END:
                    result = event.data
                elif event.type == EventType.ERROR:
                    result = f"Error: {event.data}"

        asyncio.run(run())
        return result

    # === Session Management ===

    def save_session(self, name: Optional[str] = None) -> str:
        """Save current session.

        Args:
            name: Optional session name

        Returns:
            Session name
        """
        return self.session.save(name)

    def load_session(self, name: str) -> bool:
        """Load a saved session.

        Args:
            name: Session name

        Returns:
            True if loaded successfully
        """
        return self.session.load(name)

    def list_sessions(self) -> List[SessionInfo]:
        """List saved sessions.

        Returns:
            List of SessionInfo objects
        """
        return self.session.list_sessions()

    def clear_history(self):
        """Clear conversation history."""
        self.session.clear()

    def get_history(self) -> List[Dict[str, str]]:
        """Get conversation history as dicts.

        Returns:
            List of message dicts
        """
        return self.session.get_messages_as_dicts()

    def export_conversation(self, filename: Optional[str] = None) -> Path:
        """Export conversation to markdown.

        Args:
            filename: Optional filename

        Returns:
            Path to exported file
        """
        return self.session.export(filename)

    def get_usage(self) -> Dict[str, Any]:
        """Get usage statistics.

        Returns:
            Usage stats dict
        """
        return self.session.get_usage()

    # === Status ===

    def get_status(self) -> Dict[str, Any]:
        """Get current engine status.

        Returns:
            Status dictionary
        """
        return {
            "provider": self.provider_name,
            "model": self.model,
            "tools_enabled": self.tools_enabled,
            "tool_count": len(self.tool_manager.list_tools()) if self.tools_enabled else 0,
            "auto_inject_context": self.auto_inject_context,
            "has_api_key": self.provider is not None,
            "message_count": len(self.session.messages)
        }

    # === Cleanup ===

    async def cleanup(self):
        """Clean up resources."""
        await self.tool_manager.cleanup()
