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
from dataclasses import replace
from typing import List, AsyncIterator, Optional, Dict, Any

import httpx
from openai import OpenAI

from ...config.tls import tls_verify
from ..model_facts import ModelFacts, shipped_facts_for_model
from ..types import Message, Event, EventType, ProviderCapabilities
from .base import BaseProvider
from .wire import get_handler


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
# ⚠ NO PRODUCTION READERS. Kept as the RECORD of a live measurement, not
# as a routing table — ADR 0012 §2 Q0e made tool mode a per-model fact, so
# the shipped seed rows decide: `sonar-pro` and `sonar-reasoning-pro`
# resolve `auto` (native with a prompt-based fallback) and `sonar` resolves
# `prompt_based`. A provider override forcing `native` here would silently
# DROP that fallback, which is why there is no override.
#
# The probe derives its expectations from the RESOLVER (see
# `expected_verdict`), not from these sets: a probe validating a table
# production does not consult reports agreement while behaviour drifts,
# which is debt Item 61's shape. `test_perplexity_model_capabilities.py`
# asserts the two still agree, so a drift between measurement and seed rows
# fails a test rather than passing silently.
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


#: The Agent fleet: models reached through a Perplexity key over the
#: OpenAI **Responses** wire (ADR 0012 §5 / W3). Namespaced glob per
#: vendor, because that is exactly how Perplexity names them — a row per
#: model would be 38 rows restating one fact.
#:
#: Measured live at `https://api.perplexity.ai/v1/responses`:
#: 2026-08-15 (`anthropic/claude-sonnet-5` answered; a `tools=[...]`
#: request produced a real `function_call` item; the stock OpenAI SDK
#: drove it unchanged) and re-verified **2026-08-31** by
#: `scripts/probe-perplexity-capabilities.py --api-path responses`,
#: which reported NATIVE and the model actually calling the tool.
#:
#: `max_tokens` is NOT decoration here. The Agent API answers **400 for
#: `anthropic/*` without `max_output_tokens`** (measured at plan I2), and
#: the Responses handler only sends that key when the budget is non-zero
#: — so a fleet row resolving `max_tokens=0` would 400 on every request.
#: The budget is per-model request shaping expressed as table data,
#: which is the whole point: no code branch names a vendor.
AGENT_FLEET_GLOBS = (
    "anthropic/*",
    "openai/*",
    "google/*",
    "xai/*",
    # Sonar's OWN namespaced IDs. The bare form (`sonar`) is the
    # chat-completions name and keeps that wire; the namespaced form exists
    # on the Responses wire, and MEASURED 2026-08-31 it behaves differently
    # there — `perplexity/sonar` accepted a tools array and called the tool,
    # while bare `sonar` answers 400 "Tool calling is not supported for this
    # model" on chat-completions.
    #
    # That is the clearest evidence for this ADR's premise anywhere in the
    # tree: the SAME model has different capabilities on different wires, so
    # capability cannot be a property of the provider. Routing the namespaced
    # ID to chat-completions (which is where it landed before this row) sent
    # it to a wire that may not serve it at all.
    "perplexity/*",
)

#: The fleet does NATIVE tool calling — measured, not assumed. Without this
#: the rows would inherit the conservative `prompt_based` floor (Q0a), which
#: is the right default for an unmeasured model and simply wrong for a model
#: whose native `function_call` we have watched arrive twice:
#: 2026-08-15 (plan I2: a `tools=[...]` request produced
#: `{"type": "function_call", "name": "read_file", "call_id": "toolu_..."}`)
#: and 2026-08-31 (the probe reported NATIVE with the tool actually called).
#:
#: `auto` rather than `native`: native attempt, prompt-based fallback. The
#: fleet spans four vendors behind one wire and the roster changes without
#: notice, so a model that stops accepting a tools array degrades instead of
#: erroring. Sonar's own rows use `auto` for exactly this reason.
AGENT_FLEET_TOOL_MODE = "auto"

#: Default output budget for the fleet. Conservative and uniform: the
#: requirement being satisfied is "a budget is present", not any
#: particular size, and an operator `facts.max_tokens` override replaces
#: it per model.
AGENT_FLEET_MAX_TOKENS = 4096

#: The fleet's seed rows, assembled once at module scope. (These live here
#: rather than in the class body because a comprehension inside a class body
#: cannot see the class's own names — only module and function scopes are
#: visible to it.)
AGENT_FLEET_FACTS = {
    glob: replace(
        shipped_facts_for_model(glob.rstrip("*")),
        wire_protocol="responses",
        max_tokens=AGENT_FLEET_MAX_TOKENS,
        tool_mode=AGENT_FLEET_TOOL_MODE,
    )
    for glob in AGENT_FLEET_GLOBS
}


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

        # ADR 0012 W3 — same routing question as chat(), one reader.
        if self._wire_for(model) == "responses":
            return get_handler("responses").oneshot(
                self._wire_ctx(), messages, model, max_tokens
            )

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
