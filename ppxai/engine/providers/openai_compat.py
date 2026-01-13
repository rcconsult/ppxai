"""
OpenAI-compatible provider.

This provider works with any API that follows the OpenAI API format,
including OpenAI, OpenRouter, Gemini (via compatibility layer), local models, etc.
"""

import json
from typing import List, AsyncIterator, Optional, Dict, Any
from ..types import Message, Event, EventType, ProviderCapabilities
from .base import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    """Provider for OpenAI-compatible APIs.

    Works with:
    - OpenAI (ChatGPT)
    - OpenRouter
    - Google Gemini (via OpenAI compatibility)
    - Local models (Ollama, vLLM, LM Studio)
    - Any other OpenAI-compatible endpoint

    Supports native tool calling when enabled via capabilities.native_tool_calling.
    This is used by vLLM with --enable-auto-tool-choice flag.

    v1.13.9: Detects OpenAI native reasoning models (o1, o3, o4) and warns about
    limitations when using Chat Completions API (no streaming, no system prompts).
    """

    name = "openai_compatible"

    # v1.13.9: OpenAI reasoning model prefixes (o1, o3, o4 series)
    REASONING_MODEL_PREFIXES = ("o1", "o3", "o4")
    default_capabilities = ProviderCapabilities(
        web_search=False,
        web_fetch=False,
        weather=False,
        citations=False,
        streaming=True,
        native_tool_calling=False  # Override per-provider if vLLM has tool calling enabled
    )

    # v1.13.9: OpenAI native endpoint detection
    OPENAI_NATIVE_HOSTS = ("api.openai.com",)

    # v1.13.9: Token estimation for context overflow prevention
    # Conservative estimate: ~4 chars per token for English text
    CHARS_PER_TOKEN = 4
    # Reserve tokens for response generation
    MIN_RESPONSE_TOKENS = 2048

    def _get_context_limit(self, model: str) -> int:
        """Get context limit for the current model from config.

        Args:
            model: Model ID to check

        Returns:
            Context limit in tokens
        """
        try:
            from ...config import get_model_context_limit, MODEL_PROVIDER
            return get_model_context_limit(MODEL_PROVIDER, model)
        except ImportError:
            return 128_000  # Default fallback

    def _get_warn_percent(self) -> int:
        """Get context warning threshold percentage.

        Returns:
            Warning threshold (0-100, 0 = disabled)
        """
        try:
            from ...config import get_context_warn_percent
            return get_context_warn_percent()
        except ImportError:
            return 80  # Default

    def _estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Estimate token count for messages.

        This is a rough estimate using character count / 4.
        Actual tokenization varies by model, but this is good enough
        for preventing obvious context overflow.

        Args:
            messages: API-formatted messages

        Returns:
            Estimated token count
        """
        total_chars = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                # Multimodal content (list of text/image blocks)
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        total_chars += len(part.get("text", ""))
            # Add overhead for role, etc.
            total_chars += 20

        return total_chars // self.CHARS_PER_TOKEN

    def _is_openai_native(self) -> bool:
        """Check if this provider is using native OpenAI API endpoint.

        Returns:
            True if base_url points to api.openai.com
        """
        if not self.base_url:
            return False
        return any(host in self.base_url for host in self.OPENAI_NATIVE_HOSTS)

    def _is_reasoning_model(self, model: str) -> bool:
        """Check if model is an OpenAI reasoning model (o1, o3, o4 series).

        Args:
            model: Model ID to check

        Returns:
            True if model is a reasoning model
        """
        return model.startswith(self.REASONING_MODEL_PREFIXES)

    async def chat(
        self,
        messages: List[Message],
        model: str,
        stream: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncIterator[Event]:
        """Send chat request to OpenAI-compatible API.

        Args:
            messages: Conversation history
            model: Model ID to use
            stream: Whether to stream the response
            tools: Optional list of tools in OpenAI format (for native tool calling)

        Yields:
            Event objects
        """
        try:
            api_messages = self._convert_messages(messages)

            # v1.13.9: Estimate token count and check for context overflow
            # This prevents the "max_tokens must be at least 1" error from vLLM
            estimated_tokens = self._estimate_tokens(api_messages)
            context_limit = self._get_context_limit(model)
            max_allowed = context_limit - self.MIN_RESPONSE_TOKENS
            warn_percent = self._get_warn_percent()

            if estimated_tokens > max_allowed:
                yield Event(EventType.ERROR, (
                    f"Context too large: ~{estimated_tokens:,} tokens estimated, "
                    f"but model limit is {context_limit:,} tokens. "
                    f"Try removing some @file references or starting a new conversation."
                ))
                return

            # Warn if approaching context limit
            if warn_percent > 0:
                usage_percent = (estimated_tokens / context_limit) * 100
                if usage_percent >= warn_percent:
                    yield Event(EventType.INFO, (
                        f"Context usage: ~{estimated_tokens:,}/{context_limit:,} tokens "
                        f"({usage_percent:.0f}%). Consider starting a new conversation soon."
                    ))

            yield Event(EventType.STREAM_START, {"model": model})

            # v1.13.9: Warn about OpenAI reasoning model limitations via Chat API
            if self._is_openai_native() and self._is_reasoning_model(model):
                yield Event(
                    EventType.INFO,
                    f"Note: {model} has limited support via Chat Completions API "
                    "(no streaming, system prompts converted to user messages). "
                    "For full features, use OpenAI's Responses API directly."
                )

            # Build request kwargs
            request_kwargs: Dict[str, Any] = {
                "model": model,
                "messages": api_messages,
            }

            # Add tools if native tool calling is enabled
            if tools and self.capabilities.native_tool_calling:
                request_kwargs["tools"] = tools
                request_kwargs["tool_choice"] = "auto"

            if stream:
                # Streaming response with usage tracking
                # Try with stream_options first, fall back if not supported (e.g., vLLM, Ollama)
                try:
                    response_stream = self.client.chat.completions.create(
                        **request_kwargs,
                        stream=True,
                        stream_options={"include_usage": True}
                    )
                except Exception as e:
                    # Some OpenAI-compatible APIs don't support stream_options
                    if "stream_options" in str(e).lower() or "unknown" in str(e).lower():
                        response_stream = self.client.chat.completions.create(
                            **request_kwargs,
                            stream=True
                        )
                    else:
                        raise

                full_response = []
                reasoning_response = []  # v1.13.9: Collect reasoning tokens
                tool_calls = []
                current_tool_call = None
                usage = None

                for chunk in response_stream:
                    # Check for usage in final chunk (when include_usage is True)
                    if hasattr(chunk, 'usage') and chunk.usage:
                        usage = self._parse_usage(chunk.usage)

                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    # Handle tool call chunks (native tool calling)
                    if hasattr(delta, 'tool_calls') and delta.tool_calls:
                        for tc_chunk in delta.tool_calls:
                            # Start of new tool call
                            if tc_chunk.index is not None:
                                while len(tool_calls) <= tc_chunk.index:
                                    tool_calls.append({
                                        "id": "",
                                        "function": {"name": "", "arguments": ""}
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

                    # v1.13.9+: Process reasoning tokens from various providers
                    # DeepSeek R1, GPT-OSS: reasoning_content field
                    # OpenRouter: reasoning field
                    reasoning_content = getattr(delta, 'reasoning_content', None) or getattr(delta, 'reasoning', None)
                    if reasoning_content:
                        reasoning_response.append(reasoning_content)
                        yield Event(EventType.REASONING_CHUNK, reasoning_content)

                    # Process content chunks
                    if delta.content:
                        content = delta.content
                        full_response.append(content)
                        yield Event(EventType.STREAM_CHUNK, content)

                # If we got tool calls, emit them as TOOL_CALL events
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
                                "native": True,  # Mark as native tool call
                                "tool_call_id": tc["id"]
                            })

                final_content = "".join(full_response)
                final_reasoning = "".join(reasoning_response)  # v1.13.9
                metadata = {"usage": usage} if usage else None
                if tool_calls:
                    metadata = metadata or {}
                    metadata["tool_calls"] = tool_calls
                # v1.13.9: Include reasoning in metadata if present
                if final_reasoning:
                    metadata = metadata or {}
                    metadata["reasoning"] = final_reasoning
                yield Event(EventType.STREAM_END, final_content, metadata)

            else:
                # Non-streaming response
                response = self.client.chat.completions.create(
                    **request_kwargs,
                    stream=False
                )

                message = response.choices[0].message
                content = message.content or ""
                usage = self._parse_usage(response.usage)

                # v1.13.9+: Handle reasoning content in non-streaming response
                # DeepSeek R1, GPT-OSS: reasoning_content field
                # OpenRouter: reasoning field
                reasoning_content = getattr(message, 'reasoning_content', None) or getattr(message, 'reasoning', None)

                # Handle native tool calls
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    for tc in message.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                        except json.JSONDecodeError:
                            args = {}
                        yield Event(EventType.TOOL_CALL, {
                            "tool": tc.function.name,
                            "arguments": args,
                            "native": True,
                            "tool_call_id": tc.id
                        })

                metadata: Dict[str, Any] = {"usage": usage}
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    metadata["tool_calls"] = [
                        {"id": tc.id, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in message.tool_calls
                    ]
                # v1.13.9: Include reasoning in metadata if present
                if reasoning_content:
                    metadata["reasoning"] = reasoning_content
                yield Event(EventType.STREAM_END, content, metadata)

        except Exception as e:
            import traceback
            error_detail = f"{str(e)}\n{traceback.format_exc()}"
            yield Event(EventType.ERROR, error_detail)

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

        response = self.client.chat.completions.create(
            model=model,
            messages=api_messages,
            stream=False
        )

        return response.choices[0].message.content or ""
