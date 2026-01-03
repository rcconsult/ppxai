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
    """

    name = "openai_compatible"
    default_capabilities = ProviderCapabilities(
        web_search=False,
        web_fetch=False,
        weather=False,
        citations=False,
        streaming=True,
        native_tool_calling=False  # Override per-provider if vLLM has tool calling enabled
    )

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

            yield Event(EventType.STREAM_START, {"model": model})

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
                metadata = {"usage": usage} if usage else None
                if tool_calls:
                    metadata = metadata or {}
                    metadata["tool_calls"] = tool_calls
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
                yield Event(EventType.STREAM_END, content, metadata)

        except Exception as e:
            yield Event(EventType.ERROR, str(e))

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
