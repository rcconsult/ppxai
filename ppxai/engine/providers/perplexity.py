"""
Perplexity AI provider.

Perplexity has native web search and citation capabilities.

**One account, two wires (ADR 0012 W3).** Perplexity serves Sonar over Chat
Completions (`/chat/completions`) and its Agent fleet — Anthropic, OpenAI,
Google and xAI models reached through a Perplexity key — over the OpenAI
*Responses* API (`/v1/responses`). Same key, same bill, same price table, so
this stays ONE provider entry whose models pick a wire per request
(ADR 0012 §5). The wire is `ModelFacts.wire_protocol`; the handler is
`wire.get_handler(...)`; nothing here branches on a model name.

This also carries a deadline: the Sonar chat-completions endpoint retires
**2026-09-27**, after which the Responses wire is the only one Perplexity
serves.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx
from openai import OpenAI

from ... import usage as _usage
from ...config.tls import tls_verify
from ..types import Event, EventType, Message, ProviderCapabilities
from .base import BaseProvider
from .perplexity_facts import AGENT_FLEET_FACTS
from .wire import get_handler


def inject_citation_urls(content: str, citations: list[str]) -> str:
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




class _WireCtx:
    """A provider view whose `.client` is the Responses-wire client.

    `ProtocolHandler.chat/oneshot` take a host `ctx` and read `ctx.client`
    plus a handful of the host's own helpers. Perplexity's two wires sit at
    different paths on one host, so the only thing that differs between them
    is the SDK client; everything else — key, capabilities, facts, token and
    extra-body lookups, throttle classification, error formatting — belongs
    to the account and is shared.

    A thin delegating view says exactly that. The alternatives say something
    false: a second provider instance would imply a second account (and
    would double the config, the price table and the usage counters), and
    mutating `self.client` per request would make the transport a piece of
    mutable state on a shared object.
    """

    __slots__ = ("_host", "client")

    def __init__(self, host):
        self._host = host
        self.client = host.client_for_wire

    def __getattr__(self, name):
        # Only reached for names not in __slots__ — i.e. everything the
        # handler needs from the account rather than the transport.
        return getattr(self._host, name)


class PerplexityProvider(BaseProvider):
    """Provider for Perplexity AI API.

    Perplexity has built-in:
    - Web search (always on for sonar models)
    - Citations
    - Real-time information

    Tool calling is per-MODEL, resolved from the shipped seed rows via
    `get_facts_for_model()` (ADR 0012 section 2 Q0e).
    """

    name = "perplexity"
    default_capabilities = ProviderCapabilities(
        web_search=True,
        web_fetch=True,
        weather=True,  # Can answer weather via search
        citations=True,
        streaming=True,
    )

    #: The Agent fleet's Responses-wire rows (module-level
    #: `AGENT_FLEET_FACTS`). Sonar keeps the chat-completions default,
    #: so ONE provider serves both wires off one table.
    shipped_model_facts = AGENT_FLEET_FACTS

    #: Function names `/v1/responses` refuses for custom tools ("custom
    #: function name ... is reserved"), all three shipped as ppxai tools.
    #: Measured 2026-09-26 against `perplexity/sonar` by sending ppxai's
    #: full tool set (41 builtins plus `web_search`, `fetch_url`,
    #: `get_weather`) and dropping each name the API reported until the
    #: request passed. The Responses handler aliases these on the wire;
    #: see `ResponsesHandler.RESERVED_ALIAS_PREFIX`.
    reserved_function_names = frozenset({"search_files", "web_search", "fetch_url"})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The two wires live at DIFFERENT paths on the same host:
        # `/chat/completions` (what `base_url` points at) and
        # `/v1/responses`. The OpenAI SDK builds paths relative to its
        # base_url, so the Responses wire needs its own client rather than a
        # per-call override. Same key, same TLS policy, same account — only
        # the path differs, which is precisely why this is one provider.
        self._responses_client = OpenAI(
            api_key=self.api_key,
            base_url=self._responses_base_url(),
            http_client=httpx.Client(verify=tls_verify()),
        )

    def _responses_base_url(self) -> str:
        """`{base_url}/v1`, tolerating a trailing slash or an existing /v1."""
        root = (self.base_url or "https://api.perplexity.ai").rstrip("/")
        return root if root.endswith("/v1") else root + "/v1"

    @property
    def client_for_wire(self):
        """The client the Responses handler should use.

        `ResponsesHandler` reads `ctx.client`. Perplexity's `self.client`
        points at the Chat Completions root, so the handler is handed a
        `_WireCtx` view (below) whose `.client` is the Responses client.
        """
        return self._responses_client

    def _wire_ctx(self):
        """A host view for the Responses handler with the right client.

        Everything else the handler reads — `enable_web_search`,
        `get_facts_for_model`, `_get_max_tokens`, `_get_extra_body`, the
        error helpers — is this provider's own, so the view delegates by
        `__getattr__` and overrides only `client`. A subclass or a mutated
        copy would both be worse: this keeps ONE provider object owning the
        account and swaps only the transport.
        """
        return _WireCtx(self)

    def _wire_for(self, model: str) -> str:
        """Which wire this model speaks. One reader, as in `openai_native`."""
        return self.get_facts_for_model(model).wire_protocol

    async def chat(
        self,
        messages: list[Message],
        model: str,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[Event]:
        """Send chat request to Perplexity API.

        Args:
            messages: Conversation history
            model: Model ID to use
            stream: Whether to stream the response
            tools: Sent natively when `get_facts_for_model(model).tool_mode`
                   is not `prompt_based` (measured: `sonar-pro`,
                   `sonar-reasoning-pro` emit real `tool_calls`, and their
                   seed rows resolve `auto`). For any other model the array
                   is NOT sent —
                   `sonar` and `sonar-deep-research` answer HTTP 400 rather
                   than degrading, so a tool-carrying run on them is refused
                   up front by the admission guard in `task_authorizer`.

                   The capability is resolved through
                   `get_facts_for_model()`, so operator config can override
                   the shipped table per model.

                   Re-verify with `scripts/probe-perplexity-capabilities.py`
                   — there is no `/models` endpoint, so the table cannot be
                   validated by enumeration and goes stale silently.

        Yields:
            Event objects including citations when available
        """
        # ADR 0012 W3: the Agent fleet speaks the Responses wire. Same key,
        # same account — only the handler and the client path differ.
        if self._wire_for(model) == "responses":
            async for event in get_handler("responses").chat(
                self._wire_ctx(), messages, model, stream, tools
            ):
                yield event
            return

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
                tools and self.get_facts_for_model(model).tool_mode != "prompt_based"
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
                    _usage.record_provider_error(
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

    def oneshot(
        self,
        prompt: str,
        model: str,
        system: str | None = None,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Stateless single-turn completion (BaseProvider contract).

        Same return shape as OpenAICompatibleProvider.oneshot. Perplexity
        uses the OpenAI SDK, so this composes the existing message
        conversion + generation params.
        """
        messages: list[Message] = []
        if system:
            messages.append(Message(role="system", content=system))
        messages.append(Message(role="user", content=prompt))

        # ADR 0012 W3 — same routing question as chat(), one reader.
        if self._wire_for(model) == "responses":
            return get_handler("responses").oneshot(
                self._wire_ctx(), messages, model, max_tokens
            )

        request_kwargs: dict[str, Any] = {
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
