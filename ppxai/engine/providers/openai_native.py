"""
Native OpenAI provider using the OpenAI Python SDK.

Provides direct access to OpenAI-specific features:
- Chat Completions API for GPT-4.1, GPT-5.x, o-series models
- Responses API for Codex models (gpt-5.1-codex, gpt-5.1-codex-mini)
- Proper max_completion_tokens handling for newer models
- Reasoning token support (o1, o3, o4 series)
- Web search via Responses API (web_search_preview tool)
- Native function calling with streaming tool call assembly

Unlike OpenAICompatibleProvider, this provider:
- Does NOT use base_url (always targets api.openai.com)
- Has model classification built-in (no _is_openai_native() checks)
- Routes codex models to Responses API automatically
- Handles restricted generation params natively
"""

import json
import os
from typing import List, AsyncIterator, Optional, Dict, Any

import httpx
from openai import OpenAI

from ...common.logger import get_logger
from ..types import Message, Event, EventType, ProviderCapabilities, ModelInfo, UsageStats


logger = get_logger("openai_native")


# Model classification constants
MAX_COMPLETION_TOKENS_PREFIXES = ("gpt-5", "o1", "o3", "o4")
RESTRICTED_PARAM_PREFIXES = ("gpt-5", "o1", "o3", "o4")
# Models that require Responses API instead of Chat Completions API
# Codex models and Pro models return 404 on /v1/chat/completions
RESPONSES_API_PREFIXES = ("gpt-5.1-codex", "codex", "gpt-5.2-pro", "gpt-5-pro", "gpt-6-pro")
REASONING_MODEL_PREFIXES = ("o1", "o3", "o4")

# Generation params unsupported by GPT-5.x and o-series
RESTRICTED_GENERATION_PARAMS = ("temperature", "top_p", "frequency_penalty", "presence_penalty")


class OpenAINativeProvider:
    """Native provider for OpenAI API.

    Uses the OpenAI Python SDK directly for OpenAI-specific features:
    - Chat Completions API (GPT-4.1, GPT-5.x, o-series)
    - Responses API (Codex models, web search)
    - Native function calling with proper tool call streaming
    - Reasoning token extraction
    """

    name = "openai"
    default_capabilities = ProviderCapabilities(
        web_search=False,
        web_fetch=False,
        weather=False,
        citations=False,
        streaming=True,
        native_tool_calling=True,
    )

    def __init__(
        self,
        api_key: str,
        models: Optional[Dict[str, Dict[str, str]]] = None,
        capabilities: Optional[ProviderCapabilities] = None,
        enable_web_search: bool = False,
        provider_id: Optional[str] = None,
        **kwargs
    ):
        """Initialize the OpenAI provider.

        Args:
            api_key: OpenAI API key
            models: Dictionary of available models
            capabilities: Provider capabilities override
            enable_web_search: Enable web_search_preview in Responses API (default: False)
            provider_id: Provider identifier (for config lookup)
            **kwargs: Additional options (base_url accepted for compat, ignored)
        """
        self.api_key = api_key
        self.models = models or {}
        self.enable_web_search = enable_web_search
        self.provider_id = provider_id or "openai"

        # Set capabilities, enabling web_search if configured
        if capabilities:
            self.capabilities = capabilities
        else:
            self.capabilities = ProviderCapabilities(
                web_search=enable_web_search,
                web_fetch=enable_web_search,
                weather=enable_web_search,
                citations=enable_web_search,
                streaming=True,
                native_tool_calling=True,
            )

        # Initialize OpenAI client with SSL config
        ssl_verify_env = os.getenv("SSL_VERIFY", "true").lower()
        ssl_cert_file = os.getenv("SSL_CERT_FILE", "")

        client_kwargs = {"api_key": api_key}

        if ssl_verify_env == "false":
            client_kwargs["http_client"] = httpx.Client(verify=False)
        elif ssl_cert_file:
            client_kwargs["http_client"] = httpx.Client(verify=ssl_cert_file)

        self.client = OpenAI(**client_kwargs)

    # ------------------------------------------------------------------
    # Model classification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_responses_api_model(model: str) -> bool:
        """Check if model requires Responses API (codex, pro models)."""
        return model.lower().startswith(RESPONSES_API_PREFIXES)

    @staticmethod
    def _is_reasoning_model(model: str) -> bool:
        """Check if model is a reasoning model (o1, o3, o4 series)."""
        return model.lower().startswith(REASONING_MODEL_PREFIXES)

    @staticmethod
    def _needs_max_completion_tokens(model: str) -> bool:
        """Check if model requires max_completion_tokens instead of max_tokens."""
        return model.lower().startswith(MAX_COMPLETION_TOKENS_PREFIXES)

    @staticmethod
    def _has_restricted_params(model: str) -> bool:
        """Check if model rejects temperature/top_p etc."""
        return model.lower().startswith(RESTRICTED_PARAM_PREFIXES)

    # ------------------------------------------------------------------
    # Config lookup helpers
    # ------------------------------------------------------------------

    def _get_generation_params(self, model: str) -> Dict[str, Any]:
        """Get generation parameters from config."""
        try:
            from ...config import get_generation_params
            return get_generation_params(self.provider_id, model)
        except (ImportError, AttributeError):
            return {}

    def _get_max_tokens(self, model: str) -> Optional[int]:
        """Get max_tokens for output generation from config."""
        try:
            from ...config import get_model_max_tokens
            return get_model_max_tokens(self.provider_id, model)
        except (ImportError, AttributeError):
            return None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: List[Message],
        model: str,
        stream: bool = True,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs
    ) -> AsyncIterator[Event]:
        """Send chat request to OpenAI API.

        Routes to Chat Completions or Responses API based on model.

        Args:
            messages: Conversation history
            model: Model ID to use
            stream: Whether to stream the response
            tools: Tool definitions in OpenAI format
            **kwargs: Additional arguments (ignored)

        Yields:
            Event objects
        """
        if self._is_responses_api_model(model):
            async for event in self._chat_responses_api(messages, model, stream, tools):
                yield event
        else:
            async for event in self._chat_completions_api(messages, model, stream, tools):
                yield event

    def chat_sync_simple(
        self,
        messages: List[Message],
        model: str,
    ) -> str:
        """Simple synchronous chat that returns just the content.

        Args:
            messages: Conversation history
            model: Model ID to use

        Returns:
            Assistant's response content
        """
        api_messages = self._convert_messages(messages)

        request_kwargs = {
            "model": model,
            "messages": api_messages,
            "stream": False,
        }

        # Use correct token parameter
        max_tokens = self._get_max_tokens(model)
        if max_tokens:
            if self._needs_max_completion_tokens(model):
                request_kwargs["max_completion_tokens"] = max_tokens
            else:
                request_kwargs["max_tokens"] = max_tokens

        response = self.client.chat.completions.create(**request_kwargs)
        return response.choices[0].message.content or ""

    def list_models(self) -> List[ModelInfo]:
        """Return available models for this provider."""
        return [
            ModelInfo(
                id=info.get("id", model_key),
                name=info.get("name", info.get("id", model_key)),
                description=info.get("description", ""),
                context_length=info.get("context_length"),
            )
            for model_key, info in self.models.items()
        ]

    def validate_config(self) -> bool:
        """Validate provider configuration."""
        return bool(self.api_key)

    def needs_tool(self, tool_category: str) -> bool:
        """Check if provider needs a tool (doesn't have native capability)."""
        return not getattr(self.capabilities, tool_category, False)

    def get_capabilities_for_model(self, model: str) -> ProviderCapabilities:
        """Get model-aware capabilities.

        Responses API models (codex, pro) don't reliably use native function
        calling — they output tool calls as JSON text instead of function_call
        items.  Return native_tool_calling=False for these so the engine uses
        prompt-based tool injection.
        """
        if self._is_responses_api_model(model):
            return ProviderCapabilities(
                web_search=self.capabilities.web_search,
                web_fetch=self.capabilities.web_fetch,
                weather=self.capabilities.weather,
                citations=self.capabilities.citations,
                streaming=self.capabilities.streaming,
                native_tool_calling=False,
            )
        return self.capabilities

    # ------------------------------------------------------------------
    # Chat Completions API
    # ------------------------------------------------------------------

    async def _chat_completions_api(
        self,
        messages: List[Message],
        model: str,
        stream: bool = True,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[Event]:
        """Chat Completions API path for standard models.

        Handles GPT-4.1, GPT-5.x, o-series with proper parameter handling.
        """
        try:
            api_messages = self._convert_messages(messages)

            yield Event(EventType.STREAM_START, {"model": model})

            # Build request kwargs
            request_kwargs: Dict[str, Any] = {
                "model": model,
                "messages": api_messages,
            }

            # Add max_tokens / max_completion_tokens
            use_completion_tokens = self._needs_max_completion_tokens(model)
            max_tokens = self._get_max_tokens(model)
            if max_tokens:
                token_key = "max_completion_tokens" if use_completion_tokens else "max_tokens"
                request_kwargs[token_key] = max_tokens

            # Add generation params, stripping restricted ones for newer models
            generation_params = self._get_generation_params(model)
            if generation_params:
                if self._has_restricted_params(model):
                    # Rename max_tokens → max_completion_tokens if present
                    if "max_tokens" in generation_params:
                        generation_params["max_completion_tokens"] = generation_params.pop("max_tokens")
                    # Strip unsupported params
                    for param in RESTRICTED_GENERATION_PARAMS:
                        generation_params.pop(param, None)
                request_kwargs.update(generation_params)

            # Add tools for native tool calling
            if tools and self.capabilities.native_tool_calling:
                request_kwargs["tools"] = tools
                request_kwargs["tool_choice"] = "auto"

            if stream:
                async for event in self._stream_chat_completions(request_kwargs):
                    yield event
            else:
                async for event in self._non_stream_chat_completions(request_kwargs):
                    yield event

        except Exception as e:
            # Auto-fallback to Responses API on 404 "not a chat model"
            if hasattr(e, 'status_code') and e.status_code == 404 and "not a chat model" in str(e).lower():
                logger.warning(f"Model {model} not supported on Chat Completions API, falling back to Responses API")
                async for event in self._chat_responses_api(messages, model, stream, tools):
                    yield event
                return
            error_msg = self._format_error(e)
            yield Event(EventType.ERROR, error_msg)
            self._log_error_traceback(e)

    async def _stream_chat_completions(
        self,
        request_kwargs: Dict[str, Any],
    ) -> AsyncIterator[Event]:
        """Handle streaming Chat Completions response."""
        response_stream = self.client.chat.completions.create(
            **request_kwargs,
            stream=True,
            stream_options={"include_usage": True},
        )

        full_response = []
        reasoning_response = []
        tool_calls = []
        current_tool_call = None
        usage = None

        for chunk in response_stream:
            # Check for usage in final chunk
            if hasattr(chunk, "usage") and chunk.usage:
                usage = self._parse_usage(chunk.usage)

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta

            # Handle tool call chunks
            if hasattr(delta, "tool_calls") and delta.tool_calls:
                for tc_chunk in delta.tool_calls:
                    if tc_chunk.index is not None:
                        while len(tool_calls) <= tc_chunk.index:
                            tool_calls.append({
                                "id": "",
                                "function": {"name": "", "arguments": ""},
                            })
                        current_tool_call = tool_calls[tc_chunk.index]

                    if current_tool_call:
                        if tc_chunk.id:
                            current_tool_call["id"] = tc_chunk.id
                        if tc_chunk.function:
                            if tc_chunk.function.name:
                                current_tool_call["function"]["name"] = tc_chunk.function.name
                            if tc_chunk.function.arguments:
                                current_tool_call["function"]["arguments"] += tc_chunk.function.arguments

            # Process reasoning tokens (o-series models)
            reasoning_content = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            if reasoning_content:
                reasoning_response.append(reasoning_content)
                yield Event(EventType.REASONING_CHUNK, reasoning_content)

            # Process content chunks
            if delta.content:
                full_response.append(delta.content)
                yield Event(EventType.STREAM_CHUNK, delta.content)

        # Emit TOOL_CALL events
        if tool_calls:
            for tc in tool_calls:
                if tc["function"]["name"]:
                    try:
                        args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    yield Event(EventType.TOOL_CALL, {
                        "tool": tc["function"]["name"],
                        "arguments": args,
                        "native": True,
                        "tool_call_id": tc["id"],
                    })

        final_content = "".join(full_response)
        final_reasoning = "".join(reasoning_response)
        metadata = {"usage": usage} if usage else None
        if tool_calls:
            metadata = metadata or {}
            metadata["tool_calls"] = tool_calls
        if final_reasoning:
            metadata = metadata or {}
            metadata["reasoning"] = final_reasoning
        yield Event(EventType.STREAM_END, final_content, metadata)

    async def _non_stream_chat_completions(
        self,
        request_kwargs: Dict[str, Any],
    ) -> AsyncIterator[Event]:
        """Handle non-streaming Chat Completions response."""
        response = self.client.chat.completions.create(
            **request_kwargs,
            stream=False,
        )

        message = response.choices[0].message
        content = message.content or ""
        usage = self._parse_usage(response.usage)

        # Handle reasoning content
        reasoning_content = getattr(message, "reasoning_content", None) or getattr(message, "reasoning", None)

        # Handle native tool calls
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                yield Event(EventType.TOOL_CALL, {
                    "tool": tc.function.name,
                    "arguments": args,
                    "native": True,
                    "tool_call_id": tc.id,
                })

        metadata: Dict[str, Any] = {"usage": usage}
        if hasattr(message, "tool_calls") and message.tool_calls:
            metadata["tool_calls"] = [
                {"id": tc.id, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in message.tool_calls
            ]
        if reasoning_content:
            metadata["reasoning"] = reasoning_content
        yield Event(EventType.STREAM_END, content, metadata)

    # ------------------------------------------------------------------
    # Responses API (Codex models + web search)
    # ------------------------------------------------------------------

    async def _chat_responses_api(
        self,
        messages: List[Message],
        model: str,
        stream: bool = True,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[Event]:
        """Responses API path for Codex models.

        Uses client.responses.create() with different message format.
        Uses prompt-based tool calling (tools injected in system prompt)
        to avoid the call_id threading complexity of Responses API.
        """
        try:
            instructions, input_items = self._convert_messages_for_responses(messages)

            yield Event(EventType.STREAM_START, {"model": model})

            # Build request kwargs
            request_kwargs: Dict[str, Any] = {
                "model": model,
                "input": input_items,
            }

            if instructions:
                request_kwargs["instructions"] = instructions

            # Add max_tokens
            max_tokens = self._get_max_tokens(model)
            if max_tokens:
                request_kwargs["max_output_tokens"] = max_tokens

            # Add web_search_preview if enabled
            response_tools = []
            if self.enable_web_search:
                response_tools.append({"type": "web_search_preview"})

            # Add function tools if native tool calling enabled
            if tools and self.capabilities.native_tool_calling:
                for tool_def in self._convert_tools_for_responses(tools):
                    response_tools.append(tool_def)

            if response_tools:
                request_kwargs["tools"] = response_tools

            if stream:
                async for event in self._stream_responses(request_kwargs):
                    yield event
            else:
                async for event in self._non_stream_responses(request_kwargs):
                    yield event

        except Exception as e:
            error_msg = self._format_error(e)
            yield Event(EventType.ERROR, error_msg)
            self._log_error_traceback(e)

    async def _stream_responses(
        self,
        request_kwargs: Dict[str, Any],
    ) -> AsyncIterator[Event]:
        """Handle streaming Responses API response."""
        response_stream = self.client.responses.create(
            **request_kwargs,
            stream=True,
        )

        full_response = []
        usage = None
        # Track in-progress function calls: call_id -> {"name": str, "arguments": str}
        function_calls: Dict[str, Dict[str, str]] = {}

        for event in response_stream:
            event_type = getattr(event, "type", None)

            # Text delta events
            if event_type == "response.output_text.delta":
                delta_text = getattr(event, "delta", "")
                if delta_text:
                    full_response.append(delta_text)
                    yield Event(EventType.STREAM_CHUNK, delta_text)

            # Function call item started
            elif event_type == "response.output_item.added":
                item = getattr(event, "item", None)
                if item and getattr(item, "type", None) == "function_call":
                    call_id = getattr(item, "call_id", "") or getattr(item, "id", "")
                    name = getattr(item, "name", "")
                    if call_id:
                        function_calls[call_id] = {"name": name, "arguments": ""}

            # Function call arguments streaming
            elif event_type == "response.function_call_arguments.delta":
                call_id = getattr(event, "call_id", "")
                delta = getattr(event, "delta", "")
                if call_id in function_calls and delta:
                    function_calls[call_id]["arguments"] += delta

            # Function call arguments complete
            elif event_type == "response.function_call_arguments.done":
                call_id = getattr(event, "call_id", "")
                arguments = getattr(event, "arguments", "")
                name = getattr(event, "name", "")
                if call_id in function_calls:
                    function_calls[call_id]["arguments"] = arguments
                    if name:
                        function_calls[call_id]["name"] = name

            # Response completed — extract usage
            elif event_type == "response.completed":
                resp = getattr(event, "response", None)
                if resp:
                    usage = self._parse_responses_usage(getattr(resp, "usage", None))

        # Emit TOOL_CALL events for all completed function calls
        tool_calls_metadata = []
        for call_id, fc in function_calls.items():
            if fc.get("name"):
                try:
                    args = json.loads(fc["arguments"]) if fc["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                yield Event(EventType.TOOL_CALL, {
                    "tool": fc["name"],
                    "arguments": args,
                    "native": True,
                    "tool_call_id": call_id,
                })
                tool_calls_metadata.append({
                    "id": call_id,
                    "function": {"name": fc["name"], "arguments": fc["arguments"]},
                })

        final_content = "".join(full_response)
        metadata: Dict[str, Any] = {}
        if usage:
            metadata["usage"] = usage
        if tool_calls_metadata:
            metadata["tool_calls"] = tool_calls_metadata
        yield Event(EventType.STREAM_END, final_content, metadata or None)

    async def _non_stream_responses(
        self,
        request_kwargs: Dict[str, Any],
    ) -> AsyncIterator[Event]:
        """Handle non-streaming Responses API response."""
        response = self.client.responses.create(
            **request_kwargs,
            stream=False,
        )

        content = ""
        tool_calls_metadata = []

        if hasattr(response, "output"):
            for item in response.output:
                item_type = getattr(item, "type", None)

                if item_type == "message":
                    for part in getattr(item, "content", []):
                        if getattr(part, "type", None) == "output_text":
                            content += getattr(part, "text", "")

                elif item_type == "function_call":
                    call_id = getattr(item, "call_id", "") or getattr(item, "id", "")
                    name = getattr(item, "name", "")
                    arguments = getattr(item, "arguments", "")
                    if name:
                        try:
                            args = json.loads(arguments) if arguments else {}
                        except json.JSONDecodeError:
                            args = {}
                        yield Event(EventType.TOOL_CALL, {
                            "tool": name,
                            "arguments": args,
                            "native": True,
                            "tool_call_id": call_id,
                        })
                        tool_calls_metadata.append({
                            "id": call_id,
                            "function": {"name": name, "arguments": arguments},
                        })

        # Fallback: output_text convenience attribute
        if not content and not tool_calls_metadata and hasattr(response, "output_text"):
            content = response.output_text or ""

        usage = self._parse_responses_usage(getattr(response, "usage", None))

        metadata: Dict[str, Any] = {"usage": usage}
        if tool_calls_metadata:
            metadata["tool_calls"] = tool_calls_metadata
        yield Event(EventType.STREAM_END, content, metadata)

    # ------------------------------------------------------------------
    # Message conversion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_messages(messages: List[Message]) -> List[Dict[str, str]]:
        """Convert Message objects to Chat Completions API format."""
        return [{"role": m.role, "content": m.content} for m in messages]

    @staticmethod
    def _convert_messages_for_responses(messages: List[Message]) -> tuple:
        """Convert Messages to Responses API format.

        Returns:
            Tuple of (instructions string or None, input items list)
        """
        instructions_parts = []
        input_items = []

        for m in messages:
            if m.role == "system":
                instructions_parts.append(m.content)
            else:
                role = "assistant" if m.role == "assistant" else "user"
                input_items.append({
                    "role": role,
                    "content": m.content,
                })

        instructions = "\n\n".join(instructions_parts) if instructions_parts else None
        return instructions, input_items

    @staticmethod
    def _convert_tools_for_responses(openai_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert OpenAI chat tools format to Responses API format.

        Chat Completions: {"type": "function", "function": {"name": ..., "parameters": ...}}
        Responses API:    {"type": "function", "name": ..., "parameters": ...}
        """
        response_tools = []
        for tool in openai_tools:
            if tool.get("type") == "function" and "function" in tool:
                func = tool["function"]
                response_tool = {
                    "type": "function",
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                }
                if "parameters" in func:
                    response_tool["parameters"] = func["parameters"]
                response_tools.append(response_tool)
        return response_tools

    # ------------------------------------------------------------------
    # Usage parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_usage(usage) -> Optional[UsageStats]:
        """Parse usage from Chat Completions API response."""
        if not usage:
            return None
        return UsageStats(
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
        )

    @staticmethod
    def _parse_responses_usage(usage) -> Optional[UsageStats]:
        """Parse usage from Responses API response.

        Responses API uses input_tokens/output_tokens instead of
        prompt_tokens/completion_tokens.
        """
        if not usage:
            return None
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        return UsageStats(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    @staticmethod
    def _format_error(e: Exception) -> str:
        """Format exception into user-friendly error message."""
        import openai as openai_module

        error_type = type(e).__name__
        error_str = str(e)

        if isinstance(e, openai_module.APIConnectionError):
            if "getaddrinfo failed" in error_str:
                return (
                    "Connection failed: Unable to resolve hostname.\n"
                    "Check that:\n"
                    "  - You have network connectivity\n"
                    "  - The API endpoint URL is correct"
                )
            elif "Connection refused" in error_str:
                return (
                    "Connection refused: Server is not reachable.\n"
                    "Check that the server is running and the port is correct."
                )
            elif "timed out" in error_str.lower():
                return "Connection timed out: Server did not respond."
            else:
                return "Connection failed: Unable to reach OpenAI API."

        if isinstance(e, openai_module.AuthenticationError):
            return (
                "Authentication failed: Invalid OpenAI API key.\n"
                "Check your OPENAI_API_KEY in ~/.ppxai/.env"
            )

        if isinstance(e, openai_module.RateLimitError):
            return "Rate limit exceeded. Please wait before retrying."

        if isinstance(e, openai_module.BadRequestError):
            # Check for model not found (codex 404s on Chat Completions)
            if "404" in error_str or "not found" in error_str.lower():
                return (
                    f"Model not found or unsupported API. "
                    f"If using a Codex model, ensure it's routed to Responses API."
                )
            if "'message':" in error_str:
                import re
                match = re.search(r"'message':\s*'([^']+)'", error_str)
                if match:
                    return f"Invalid request: {match.group(1)}"
            return f"Invalid request: {error_str}"

        if isinstance(e, openai_module.APIStatusError):
            return f"OpenAI API error ({e.status_code}): {error_str}"

        if isinstance(e, httpx.ConnectError):
            return "Connection failed: Unable to connect to OpenAI API."

        return f"{error_type}: {error_str}"

    @staticmethod
    def _log_error_traceback(e: Exception) -> None:
        """Log full exception traceback for debugging."""
        import traceback
        try:
            from ppxai.common.logger import get_logger
            log = get_logger("openai_native")
            if log.enabled:
                log.error(f"OpenAI native provider error: {type(e).__name__}: {e}")
                log.debug(f"Full traceback:\n{traceback.format_exc()}")
        except ImportError:
            pass
