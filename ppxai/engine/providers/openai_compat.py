"""
OpenAI-compatible provider.

This provider works with any API that follows the OpenAI API format,
including OpenAI, OpenRouter, Gemini (via compatibility layer), local models, etc.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from ...config import (  # noqa: F401 — patched/read by tests
    get_context_warn_percent,
    get_default_provider,
    get_extra_body,
    get_model_context_limit,
)
from ..types import Event, EventType, Message, ProviderCapabilities
from .base import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    """Provider for OpenAI-compatible APIs.

    Works with:
    - OpenAI (ChatGPT)
    - OpenRouter
    - Google Gemini (via OpenAI compatibility)
    - Local models (Ollama, vLLM, LM Studio)
    - Any other OpenAI-compatible endpoint

    Supports native tool calling per model (ADR 0012 §2 Q0e): the answer is
    `get_facts_for_model(model).tool_mode`, not a provider-wide boolean.
    This is used by vLLM with --enable-auto-tool-choice flag.

    v1.13.9: Detects OpenAI native reasoning models (o1, o3, o4) and warns about
    limitations when using Chat Completions API (no streaming, no system prompts).
    """

    name = "openai_compatible"

    # OpenAI reasoning model prefixes (o1, o3, o4 series)
    REASONING_MODEL_PREFIXES = ("o1", "o3", "o4")

    # OpenAI models that require max_completion_tokens instead of max_tokens
    # GPT-5.x, o-series, and newer models reject the legacy max_tokens parameter
    MAX_COMPLETION_TOKENS_PREFIXES = ("gpt-5", "o1", "o3", "o4")

    # Generation params unsupported by GPT-5.x and o-series (only temperature=1.0 allowed)
    RESTRICTED_GENERATION_PARAMS = ("temperature", "top_p", "frequency_penalty", "presence_penalty")
    default_capabilities = ProviderCapabilities(
        web_search=False,
        web_fetch=False,
        weather=False,
        citations=False,
        streaming=True,
    )

    # OpenAI native endpoint detection
    OPENAI_NATIVE_HOSTS = ("api.openai.com",)

    # Token estimation for context overflow prevention
    # Conservative estimate: ~4 chars per token for English text
    CHARS_PER_TOKEN = 4
    # Reserve tokens for response generation
    MIN_RESPONSE_TOKENS = 2048

    def _get_response_reservation(self, model: str) -> int:
        """Tokens to subtract from context_limit when validating prompt size.

        Backends reject the request when `prompt_tokens + max_tokens >
        max_model_len`. Reserving the configured `max_tokens` (when set)
        keeps ppxai's pre-flight aligned with what the wire actually
        accepts; the 2048 floor preserves the legacy guard for models
        that omit `max_tokens`.
        """
        try:
            configured = self._get_max_tokens(model) or 0
        except Exception:
            configured = 0
        return max(self.MIN_RESPONSE_TOKENS, configured)

    def _get_context_limit(self, model: str) -> int:
        """Get context limit for the current model from config.

        Args:
            model: Model ID to check

        Returns:
            Context limit in tokens
        """
        try:
            return get_model_context_limit(get_default_provider(), model)
        except AttributeError:
            return 128_000  # Default fallback

    def _get_warn_percent(self) -> int:
        """Get context warning threshold percentage.

        Returns:
            Warning threshold (0-100, 0 = disabled)
        """
        try:
            return get_context_warn_percent()
        except AttributeError:
            return 80  # Default

    def _needs_max_completion_tokens(self, model: str) -> bool:
        """Check if model requires max_completion_tokens instead of max_tokens.

        OpenAI GPT-5.x and o-series models reject the legacy max_tokens parameter
        and require max_completion_tokens. Only applies to OpenAI native endpoints.
        """
        if not self._is_openai_native():
            return False
        model_lower = model.lower()
        return any(model_lower.startswith(p) for p in self.MAX_COMPLETION_TOKENS_PREFIXES)

    def validate_config(self) -> bool:
        """Validate provider configuration.

        OpenAI-compatible providers require both api_key and base_url.
        """
        return bool(self.api_key and self.base_url)

    def _estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
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
        messages: list[Message],
        model: str,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None
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
            # v1.18.3: nemotron / similar models toggle reasoning via an
            # in-prompt marker (`/think` / `/no_think`). Apply when
            # configured — no-op for everyone else.
            api_messages = self._apply_reasoning_trigger(api_messages, model)

            # Estimate token count and check for context overflow
            # This prevents the "max_tokens must be at least 1" error from vLLM
            estimated_tokens = self._estimate_tokens(api_messages)
            context_limit = self._get_context_limit(model)
            max_allowed = context_limit - self._get_response_reservation(model)
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

            # Warn about OpenAI reasoning model limitations via Chat API
            if self._is_openai_native() and self._is_reasoning_model(model):
                yield Event(
                    EventType.INFO,
                    f"Note: {model} has limited support via Chat Completions API "
                    "(no streaming, system prompts converted to user messages). "
                    "For full features, use OpenAI's Responses API directly."
                )

            # Build request kwargs
            request_kwargs: dict[str, Any] = {
                "model": model,
                "messages": api_messages,
            }

            # Add max_tokens if configured for this model or provider
            # This ensures vLLM and other backends don't use too-small defaults
            # v1.16.0: GPT-5.x and o-series require max_completion_tokens
            use_completion_tokens = self._needs_max_completion_tokens(model)
            max_tokens = self._get_max_tokens(model)
            if max_tokens:
                token_key = "max_completion_tokens" if use_completion_tokens else "max_tokens"
                request_kwargs[token_key] = max_tokens

            # Add generation params (temperature, top_p, etc.) if configured
            # v1.15.0: Lower temperature reduces hallucinations
            generation_params = self._get_generation_params(model)
            if generation_params:
                # v1.16.0: GPT-5.x and o-series only accept temperature=1.0
                # Strip unsupported params to avoid API errors
                if use_completion_tokens:
                    if "max_tokens" in generation_params:
                        generation_params["max_completion_tokens"] = generation_params.pop("max_tokens")
                    for param in self.RESTRICTED_GENERATION_PARAMS:
                        generation_params.pop(param, None)
                request_kwargs.update(generation_params)

            # Per-model, not per-provider: get_facts_for_model()
            # is the hook that lets a provider mark individual models
            # prompt-based. Reading self.capabilities here ignored it --
            # o4-mini resolved False but was sent native tools anyway.
            if tools and self.get_facts_for_model(model).tool_mode != "prompt_based":
                request_kwargs["tools"] = tools
                request_kwargs["tool_choice"] = "auto"

            # v1.18.3: vendor-specific extra_body pass-through (e.g.
            # NVIDIA NIM / vLLM ``chat_template_kwargs.enable_thinking``).
            # Only sent when configured — empty dict skipped to keep wire
            # payloads clean and avoid confusing endpoints that reject
            # unknown top-level keys.
            extra_body = self._get_extra_body(model)
            if extra_body:
                request_kwargs["extra_body"] = extra_body

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
                reasoning_response = []  # Collect reasoning tokens
                tool_calls = []
                current_tool_call = None
                usage = None
                _in_think = False  # State for inline <think>...</think> parsing (Qwen3, Hermes via vLLM)

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

                    # Process reasoning tokens from various providers
                    # DeepSeek R1, GPT-OSS: reasoning_content field
                    # OpenRouter: reasoning field
                    reasoning_content = getattr(delta, 'reasoning_content', None) or getattr(delta, 'reasoning', None)
                    if reasoning_content:
                        reasoning_response.append(reasoning_content)
                        yield Event(EventType.REASONING_CHUNK, reasoning_content)

                    # Process content chunks
                    # v1.16.2: Parse inline <think>...</think> blocks (Qwen3, Hermes via vLLM without
                    # reasoning parser). Route them as REASONING_CHUNK so TUI/web handle them like
                    # DeepSeek R1 — clean final content, collapsible thinking section.
                    if delta.content:
                        remaining = delta.content
                        while remaining:
                            if not _in_think:
                                think_start = remaining.find('<think>')
                                if think_start == -1:
                                    full_response.append(remaining)
                                    yield Event(EventType.STREAM_CHUNK, remaining)
                                    remaining = ''
                                else:
                                    if think_start > 0:
                                        pre = remaining[:think_start]
                                        full_response.append(pre)
                                        yield Event(EventType.STREAM_CHUNK, pre)
                                    _in_think = True
                                    remaining = remaining[think_start + 7:]  # len('<think>') == 7
                            else:
                                think_end = remaining.find('</think>')
                                if think_end == -1:
                                    reasoning_response.append(remaining)
                                    yield Event(EventType.REASONING_CHUNK, remaining)
                                    remaining = ''
                                else:
                                    if think_end > 0:
                                        reason = remaining[:think_end]
                                        reasoning_response.append(reason)
                                        yield Event(EventType.REASONING_CHUNK, reason)
                                    _in_think = False
                                    remaining = remaining[think_end + 8:]  # len('</think>') == 8

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
                final_reasoning = "".join(reasoning_response)
                metadata = {"usage": usage} if usage else None
                if tool_calls:
                    metadata = metadata or {}
                    metadata["tool_calls"] = tool_calls
                # Include reasoning in metadata if present
                if final_reasoning:
                    metadata = metadata or {}
                    metadata["reasoning"] = final_reasoning
                yield Event(EventType.STREAM_END, final_content, metadata)

            else:
                # Non-streaming response. The OpenAI SDK call is SYNCHRONOUS
                # and blocks for the entire round-trip; run it off the event
                # loop so a long agent-tier call (/v1/agent/task uses
                # stream=False) doesn't starve every other request on the
                # server. LLM calls are I/O-bound, so to_thread releases the
                # GIL during the socket wait → concurrent runs genuinely
                # interleave (v1.19.x; surfaced by the agent-behavior bench).
                response = await asyncio.to_thread(
                    lambda: self.client.chat.completions.create(
                        **request_kwargs,
                        stream=False,
                    )
                )

                message = response.choices[0].message
                content = message.content or ""
                usage = self._parse_usage(response.usage)

                # v1.13.9+: Handle reasoning content in non-streaming response
                # DeepSeek R1, GPT-OSS: reasoning_content field
                # OpenRouter: reasoning field
                reasoning_content = getattr(message, 'reasoning_content', None) or getattr(message, 'reasoning', None)

                # v1.16.2: Strip inline <think>...</think> blocks (Qwen3, Hermes via vLLM)
                if not reasoning_content and '<think>' in content:
                    think_blocks = re.findall(r'<think>(.*?)</think>', content, re.DOTALL)
                    if think_blocks:
                        reasoning_content = '\n'.join(think_blocks)
                        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()

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

                metadata: dict[str, Any] = {"usage": usage}
                if hasattr(message, 'tool_calls') and message.tool_calls:
                    metadata["tool_calls"] = [
                        {"id": tc.id, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in message.tool_calls
                    ]
                # Include reasoning in metadata if present
                if reasoning_content:
                    metadata["reasoning"] = reasoning_content
                yield Event(EventType.STREAM_END, content, metadata)

        except Exception as e:
            # v1.18.3: separate provider throttle (HTTP 403/429) from generic
            # ERROR so callers can skip-not-fail (benchmarks) or render with
            # a different UI affordance (toast vs banner). Falls through to
            # ERROR for anything that isn't a typed APIStatusError throttle.
            throttle = self._classify_throttle(e)
            if throttle is not None:
                throttle["model"] = model
                # v1.18.3 Tier 2 #5: record throttle in persistent usage so
                # users can see "NIM returned 12 quota errors today" without
                # re-running benchmarks. Best-effort — never break chat on
                # telemetry failure.
                try:
                    from ...usage import record_provider_error
                    record_provider_error(
                        provider=throttle["provider"] or self.provider_id or "",
                        status_code=throttle["status_code"],
                        model=model,
                    )
                except Exception:
                    pass
                yield Event(EventType.PROVIDER_THROTTLED, throttle)
            else:
                error_msg = self._format_error(e)
                yield Event(EventType.ERROR, error_msg)
            # Log full traceback to debug log for troubleshooting
            self._log_error_traceback(e)

    def chat_sync_simple(
        self,
        messages: list[Message],
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
        api_messages = self._apply_reasoning_trigger(api_messages, model)

        response = self.client.chat.completions.create(
            model=model,
            messages=api_messages,
            stream=False
        )

        return response.choices[0].message.content or ""

    def oneshot(
        self,
        prompt: str,
        model: str,
        system: str | None = None,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Stateless single-turn completion.

        v1.18.3: backs the `POST /v1/oneshot` gateway endpoint. No
        history, no tools, no streaming. Designed for external agents
        (classifiers, routers, structured-extraction pipelines) that
        want ppxai-server as a thin LLM gateway without having to
        manage sessions per call.

        Request-level overrides (`max_tokens`, `temperature`,
        `response_format`) take precedence over per-model config.
        `extra_body` from config is still applied so vendor-specific
        knobs (NVIDIA NIM `chat_template_kwargs.enable_thinking` etc.)
        carry through.

        Args:
            prompt: The user message content.
            model: Model ID to use (e.g. "qwen/qwen3.5-122b-a10b").
            system: Optional system message prepended.
            response_format: Optional OpenAI-style response_format
                dict, e.g. ``{"type": "json_object"}`` or
                ``{"type": "json_schema", "json_schema": {...}}``.
                Forwarded to the provider as-is.
            max_tokens: Optional cap. Overrides per-model config.
            temperature: Optional sampling temperature. Overrides
                per-model generation_params if set.

        Returns:
            ``{"content": str, "finish_reason": str | None,
              "model": str, "usage": {prompt_tokens, completion_tokens,
              total_tokens} | None}``
        """
        messages: list[Message] = []
        if system:
            messages.append(Message(role="system", content=system))
        messages.append(Message(role="user", content=prompt))

        api_messages = self._convert_messages(messages)
        api_messages = self._apply_reasoning_trigger(api_messages, model)

        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "stream": False,
        }

        # max_tokens: request override > per-model config > omit
        use_completion_tokens = self._needs_max_completion_tokens(model)
        token_key = "max_completion_tokens" if use_completion_tokens else "max_tokens"
        if max_tokens is not None:
            request_kwargs[token_key] = max_tokens
        else:
            configured_max = self._get_max_tokens(model)
            if configured_max:
                request_kwargs[token_key] = configured_max

        # temperature: request override wins; otherwise pull configured
        # generation_params (filtered for restricted models).
        if temperature is not None:
            if not (use_completion_tokens and "temperature" in self.RESTRICTED_GENERATION_PARAMS):
                request_kwargs["temperature"] = temperature
        else:
            generation_params = self._get_generation_params(model)
            if generation_params:
                if use_completion_tokens:
                    if "max_tokens" in generation_params:
                        generation_params["max_completion_tokens"] = generation_params.pop("max_tokens")
                    for param in self.RESTRICTED_GENERATION_PARAMS:
                        generation_params.pop(param, None)
                request_kwargs.update(generation_params)

        if response_format is not None:
            request_kwargs["response_format"] = response_format

        extra_body = self._get_extra_body(model)
        if extra_body:
            request_kwargs["extra_body"] = extra_body

        response = self.client.chat.completions.create(**request_kwargs)

        msg = response.choices[0].message
        finish_reason = response.choices[0].finish_reason
        usage_obj = getattr(response, "usage", None)
        usage_dict = None
        if usage_obj is not None:
            usage_dict = {
                "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
                "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
            }

        return {
            "content": msg.content or "",
            "finish_reason": finish_reason,
            "model": getattr(response, "model", None) or model,
            "usage": usage_dict,
        }
