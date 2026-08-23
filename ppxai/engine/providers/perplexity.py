"""
Perplexity AI provider.

Perplexity has native web search and citation capabilities.
"""

import asyncio
import json
import re
from typing import List, AsyncIterator, Optional, Dict, Any
from ..types import Message, Event, EventType, ProviderCapabilities
from .base import BaseProvider


def inject_citation_urls(content: str, citations: List[str]) -> str:
    """
    Inject citation URLs into response text.

    Perplexity returns citations as a separate array, but the response text
    only contains [1], [2], etc. markers. This function converts them to
    clickable markdown links like [1](url).

    Args:
        content: Response text with [1], [2] markers
        citations: List of citation URLs from Perplexity API

    Returns:
        Content with [1](url), [2](url) format for clickable links
    """
    if not citations:
        return content

    # Replace [N] with [N](url) where N is 1-indexed
    def replace_citation(match):
        num = int(match.group(1))
        # Citations are 1-indexed in text, 0-indexed in array
        if 1 <= num <= len(citations):
            url = citations[num - 1]
            return f'[{num}]({url})'
        return match.group(0)  # Leave unchanged if out of range

    # Match [N] but NOT already [N](url)
    # Negative lookahead ensures we don't match already-linked citations
    pattern = r'\[(\d+)\](?!\()'
    return re.sub(pattern, replace_citation, content)


# Which Sonar models accept a `tools` array, measured live against
# api.perplexity.ai (2026-08-13, re-verified 2026-08-23):
#
#   sonar                 400  "Tool calling is not supported for this model"
#   sonar-pro             200  emits tool_calls  (full round-trip canary-verified)
#   sonar-reasoning-pro   200  emits tool_calls
#   sonar-deep-research   400  "Tool parameters must be a JSON object."
#
# The capability was per-PROVIDER until v1.19.1 and hardcoded False with the
# comment "Sonar models don't support native API tool_calls" — true when
# written, false since Perplexity shipped tool calling. That stale flag
# forced `profile.mode=prompt_based`, and debt Item 43's refusals /
# confabulations / external mis-grounding were all the prompt-based fallback
# failing, not the API. Data, not branches: add a row rather than a code path.
#
# NB the two 400s differ in kind. `sonar` states the capability is absent;
# `sonar-deep-research` complains about the SHAPE of the parameters, so it
# may be usable with a stricter schema — not chased, and it is being dropped
# from the shipped model list, so it is recorded here only as a known 400.
PERPLEXITY_NATIVE_TOOL_MODELS = frozenset({
    "sonar-pro",
    "sonar-reasoning-pro",
})

#: Models that reject a `tools` array with HTTP 400 rather than degrading.
#: The distinction matters: a tool-capable request to one of these must be
#: refused up front, NOT routed to the prompt-based fallback, because that
#: fallback is precisely what produces Item 43's confabulated answers.
PERPLEXITY_TOOL_REJECTING_MODELS = frozenset({
    "sonar",
    "sonar-deep-research",
})


class PerplexityProvider(BaseProvider):
    """Provider for Perplexity AI API.

    Perplexity has built-in:
    - Web search (always on for sonar models)
    - Citations
    - Real-time information

    Tool calling is per-MODEL — see PERPLEXITY_NATIVE_TOOL_MODELS.
    """

    name = "perplexity"
    default_capabilities = ProviderCapabilities(
        web_search=True,
        web_fetch=True,
        weather=True,  # Can answer weather via search
        citations=True,
        streaming=True,
        # Per-model, resolved by shipped_capabilities_for_model below. False
        # is the safe default: an unknown/new model is assumed non-tool-capable
        # until measured, so it degrades rather than 400ing a user's request.
        native_tool_calling=False,
    )

    def shipped_capabilities_for_model(self, model: str) -> ProviderCapabilities:
        """Native tool calling per model (plan layer 2).

        Operator config can still override this per model — see
        `ppxai/config/capabilities.py` — which is the escape hatch if
        Perplexity changes a model's support before we ship a new table.
        """
        model_id = (model or "").strip().lower()
        if model_id not in PERPLEXITY_NATIVE_TOOL_MODELS:
            return self.capabilities
        return ProviderCapabilities(
            web_search=self.capabilities.web_search,
            web_fetch=self.capabilities.web_fetch,
            weather=self.capabilities.weather,
            citations=self.capabilities.citations,
            streaming=self.capabilities.streaming,
            native_tool_calling=True,
        )

    async def chat(
        self,
        messages: List[Message],
        model: str,
        stream: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncIterator[Event]:
        """Send chat request to Perplexity API.

        Args:
            messages: Conversation history
            model: Model ID to use
            stream: Whether to stream the response
            tools: Converted to prompt-based tool calling. Perplexity Sonar models
                   do not support native function calling via the API (tool_calls response).
                   Instead, tool definitions are injected into the system prompt and
                   responses are parsed for JSON tool call format.

                   Note: Perplexity's Agentic Research API supports native tools for
                   third-party models (openai/gpt-*, etc.) but NOT for Sonar models.

                   See: https://docs.perplexity.ai/docs/agentic-research/tools

        Yields:
            Event objects including citations when available
        """
        # Note: tools parameter is ignored - Perplexity has native search
        try:
            api_messages = self._convert_messages(messages)

            # Load generation params from config (v1.15.2)
            generation_params = self._get_generation_params(model)

            yield Event(EventType.STREAM_START, {"model": model})

            # v1.18.3: vendor-specific extra_body pass-through (e.g.
            # Perplexity-only ``search_recency_filter``,
            # ``search_domain_filter``, ``return_images``). Only sent when
            # configured; empty dict skipped.
            extra_body = self._get_extra_body(model)

            # Native tool calling, per MODEL (v1.19.1, debt Item 43).
            # Until now this method ignored `tools` outright — the docstring
            # said Sonar had no native function calling, true when written.
            # Measured 2026-08-13/23: sonar-pro and sonar-reasoning-pro emit
            # real tool_calls; sonar and sonar-deep-research answer HTTP 400.
            # Gated on the capability table so the two that 400 never see a
            # tools array, and so an unmeasured model degrades instead.
            native_tools = bool(
                tools and self.get_capabilities_for_model(model).native_tool_calling
            )

            if stream:
                # Streaming response with usage tracking
                request_kwargs = {
                    "model": model,
                    "messages": api_messages,
                    "stream": True,
                    "stream_options": {"include_usage": True}
                }
                # Add generation params if configured
                if generation_params:
                    request_kwargs.update(generation_params)
                if extra_body:
                    request_kwargs["extra_body"] = extra_body
                if native_tools:
                    request_kwargs["tools"] = tools
                    request_kwargs["tool_choice"] = "auto"
                response_stream = self.client.chat.completions.create(**request_kwargs)

                full_response = []
                usage = None
                citations = []
                for chunk in response_stream:
                    # Check for usage in final chunk (when include_usage is True)
                    if hasattr(chunk, 'usage') and chunk.usage:
                        usage = self._parse_usage(chunk.usage)
                    # Check for citations (Perplexity-specific)
                    if hasattr(chunk, 'citations') and chunk.citations:
                        citations = chunk.citations
                    # Process content chunks
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_response.append(content)
                        yield Event(EventType.STREAM_CHUNK, content)

                final_content = "".join(full_response)
                # Inject citation URLs into response text
                if citations:
                    final_content = inject_citation_urls(final_content, citations)

                metadata = {}
                if usage:
                    metadata["usage"] = usage
                if citations:
                    metadata["citations"] = citations
                yield Event(EventType.STREAM_END, final_content, metadata if metadata else None)

            else:
                # Non-streaming response
                request_kwargs = {
                    "model": model,
                    "messages": api_messages,
                    "stream": False
                }
                # Add generation params if configured
                if generation_params:
                    request_kwargs.update(generation_params)
                if extra_body:
                    request_kwargs["extra_body"] = extra_body
                if native_tools:
                    request_kwargs["tools"] = tools
                    request_kwargs["tool_choice"] = "auto"
                # Off-load the blocking SDK call so a non-streaming agent-tier
                # run doesn't starve the event loop (v1.19.x — see
                # openai_compat.chat).
                response = await asyncio.to_thread(
                    lambda: self.client.chat.completions.create(**request_kwargs)
                )

                message = response.choices[0].message
                content = message.content or ""
                usage = self._parse_usage(response.usage)

                # Emit native tool calls, same event contract as
                # openai_compat/openai_native so the tool loop is provider
                # agnostic (tool / arguments / native / tool_call_id).
                for tc in (getattr(message, "tool_calls", None) or []):
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

                # Extract citations if available (Perplexity-specific)
                citations = []
                if hasattr(response, 'citations'):
                    citations = response.citations or []

                # Inject citation URLs into response text for clickable links
                if citations:
                    content = inject_citation_urls(content, citations)

                metadata = {"usage": usage}
                if citations:
                    metadata["citations"] = citations

                yield Event(EventType.STREAM_END, content, metadata)

        except Exception as e:
            # v1.18.3: provider throttle (HTTP 403/429) → typed event +
            # persistent telemetry counter. Falls through to ERROR for
            # anything that isn't a typed APIStatusError throttle.
            throttle = self._classify_throttle(e)
            if throttle is not None:
                throttle["model"] = model
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
            self._log_error_traceback(e)

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
        generation_params = self._get_generation_params(model)
        extra_body = self._get_extra_body(model)

        request_kwargs = {
            "model": model,
            "messages": api_messages,
            "stream": False
        }
        if generation_params:
            request_kwargs.update(generation_params)
        if extra_body:
            request_kwargs["extra_body"] = extra_body

        response = self.client.chat.completions.create(**request_kwargs)

        return response.choices[0].message.content or ""

    def oneshot(
        self,
        prompt: str,
        model: str,
        system: Optional[str] = None,
        response_format: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Stateless single-turn completion (BaseProvider contract).

        Same return shape as OpenAICompatibleProvider.oneshot. Perplexity
        uses the OpenAI SDK, so this composes the existing message
        conversion + generation params.
        """
        messages: List[Message] = []
        if system:
            messages.append(Message(role="system", content=system))
        messages.append(Message(role="user", content=prompt))

        request_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": self._convert_messages(messages),
            "stream": False,
        }
        generation_params = self._get_generation_params(model)
        if generation_params:
            request_kwargs.update(generation_params)
        if temperature is not None:
            request_kwargs["temperature"] = temperature
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            request_kwargs["response_format"] = response_format
        extra_body = self._get_extra_body(model)
        if extra_body:
            request_kwargs["extra_body"] = extra_body

        response = self.client.chat.completions.create(**request_kwargs)
        msg = response.choices[0].message
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
            "finish_reason": response.choices[0].finish_reason,
            "model": getattr(response, "model", None) or model,
            "usage": usage_dict,
        }
