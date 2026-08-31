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

import asyncio
import json
import re
import traceback
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import httpx
import openai
from openai import OpenAI

from ...common.logger import get_logger
from ...config.tls import tls_verify
from ..model_facts import shipped_facts_for_model
from ..types import Event, EventType, Message, ProviderCapabilities
from .base import BaseProvider
from .wire import get_handler

logger = get_logger("openai_native")


# Model classification constants
MAX_COMPLETION_TOKENS_PREFIXES = ("gpt-5", "o1", "o3", "o4")
RESTRICTED_PARAM_PREFIXES = ("gpt-5", "o1", "o3", "o4")
# Models that require Responses API instead of Chat Completions API
# Codex models and Pro models return 404 on /v1/chat/completions
#
# ADR 0012 W2: kept as SEED DATA for `shipped_model_facts` below — routing no
# longer consults it. `_is_responses_api_model()` remains as the seed's
# predicate form and for the 404 auto-fallback's log message; the live router
# reads `get_facts_for_model(model).wire_protocol`.
RESPONSES_API_PREFIXES = ("gpt-5.1-codex", "codex", "gpt-5.2-pro", "gpt-5-pro", "gpt-6-pro")

#: Which models speak the Responses wire, as reviewed globs (ADR 0012 §3).
#: Replaces prefix matching, which drifted from the declared `api_path` table
#: in BOTH directions — measured on 2026-08-30, three disagreements:
#:
#:   gpt-5.3-codex  declared responses, routed chat  (prefix "gpt-5.1-codex"
#:                  does not match "gpt-5.3-codex"; "codex" is a PREFIX, not a
#:                  substring) -> a live 404 on oneshot, which has no fallback
#:   gpt-5.2-pro    declared chat, routed responses  -> router correct
#:   gpt-5-pro      declared chat, routed responses  -> router correct
#:
#: The pro rows are resolved in the ROUTER's favour on measured evidence:
#: commit 5e1ace2f ("Route gpt-5.2-pro to Responses API + add 404
#: auto-fallback") added them after OpenAI returned "not a chat model" for
#: Chat Completions. The declared `chat` was never exercised, because nothing
#: ever routed on `api_path`. The codex row is resolved in the PROFILE's
#: favour for the same reason: codex models 404 on Chat Completions, so
#: `responses` is what the model actually needs.
#:
#: gpt-5.5-pro was found in the same sweep: a pro model that NEITHER mechanism
#: sent to Responses (no prefix entry, profile says `chat`), registered by
#: c4b6f431 alongside gpt-5.3-codex without updating the routing tuple.
#:
#: Its row began as an ANALOGY with its siblings and is now MEASURED:
#: probed live 2026-08-31, `gpt-5.5-pro` on `/v1/chat/completions` returns
#: **404 "This is not a chat model and thus not supported in the
#: v1/chat/completions endpoint"** — the same error, verbatim, that put its
#: siblings on this list. Every row in this table now rests on an observed
#: response rather than on pattern-matching a model name.
RESPONSES_WIRE_GLOBS = (
    "gpt-5.1-codex*",
    "gpt-5.3-codex*",
    "codex*",
    "gpt-5-pro*",
    "gpt-5.2-pro*",
    "gpt-5.5-pro*",
    "gpt-6-pro*",
)
REASONING_MODEL_PREFIXES = ("o1", "o3", "o4")

# Models that perform better with prompt-based tool calling than native.
# Benchmark evidence:
#   o4-mini: 10.9% native → 62.5% prompt-based (native returns empty responses)
#   gpt-4.1-mini: 60.9% native → 71.9% prompt-based (hybrid tool_json_in_content)
PROMPT_BASED_MODEL_PREFIXES = ("o4-mini", "gpt-4.1-mini")

# Generation params unsupported by GPT-5.x and o-series
RESTRICTED_GENERATION_PARAMS = ("temperature", "top_p", "frequency_penalty", "presence_penalty")


class OpenAINativeProvider(BaseProvider):
    """Native provider for OpenAI API.

    Uses the OpenAI Python SDK directly for OpenAI-specific features:
    - Chat Completions API (GPT-4.1, GPT-5.x, o-series)
    - Responses API (Codex models, web search)
    - Native function calling with proper tool call streaming
    - Reasoning token extraction

    Inherits from BaseProvider (v1.16.0) for shared interface: needs_tool(),
    get_facts_for_model(), list_models(), validate_config(), _parse_usage(),
    _convert_messages(), _get_generation_params(), _get_max_tokens().
    """

    name = "openai"
    default_capabilities = ProviderCapabilities(
        web_search=False,
        web_fetch=False,
        weather=False,
        citations=False,
        streaming=True,
    )

    def __init__(
        self,
        api_key: str,
        models: dict[str, dict[str, str]] | None = None,
        capabilities: ProviderCapabilities | None = None,
        enable_web_search: bool = False,
        provider_id: str | None = None,
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
        self.enable_web_search = enable_web_search

        # Set capabilities, enabling web_search if configured
        if not capabilities:
            capabilities = ProviderCapabilities(
                web_search=enable_web_search,
                web_fetch=enable_web_search,
                weather=enable_web_search,
                citations=enable_web_search,
                streaming=True,
            )

        # Remove base_url from kwargs if passed for compat (we don't use it)
        kwargs.pop("base_url", None)

        # base_url=None skips OpenAI client creation in BaseProvider
        super().__init__(
            api_key=api_key,
            base_url=None,
            models=models,
            capabilities=capabilities,
            provider_id=provider_id or "openai",
            **kwargs,
        )

        # Create our own OpenAI client (no base_url = api.openai.com default).
        # TLS comes from the shared resolver (env, then network.ssl.*).
        # tls_verify() returns False (off) or an SSLContext — never True — so
        # the explicit http_client is always supplied.
        self.client = OpenAI(
            api_key=api_key,
            http_client=httpx.Client(verify=tls_verify()),
        )

    #: Benchmark-derived per-model rows (ADR 0012 §2 Q0e). Was
    #: `shipped_capabilities_for_model`, which answered only the tool-calling
    #: boolean while `BUILTIN_PROFILES` answered mode, limits and routing for
    #: the same models — the two-systems split this ADR removes.
    #:
    #: `PROMPT_BASED_MODEL_PREFIXES` are benchmark-proven to score
    #: significantly HIGHER with prompt-based tool calling (o4-mini: 10.9%%
    #: native -> 62.5%% prompt-based, native returns empty responses;
    #: gpt-4.1-mini: 60.9%% -> 71.9%%, hybrid tool_json_in_content).
    #:
    #: `RESPONSES_WIRE_GLOBS` (ADR 0012 W2) carry the OTHER fact: which wire
    #: the model speaks. Both sets write into ONE table because they are
    #: fields of one record — that is the whole point of Q0e. A model in both
    #: sets would need one row stating both facts; none is today, and the
    #: disjointness fence would catch it if that changed.
    #:
    #: A wire row overrides ONLY `wire_protocol`, so `codex*` and `gpt-6-pro*`
    #: (which have no built-in profile) keep the conservative `prompt_based`
    #: floor while still routing to Responses. That asymmetry is deliberate
    #: per Q0a: the wire is a property of the endpoint and is knowable without
    #: measuring, tool support is not.
    shipped_model_facts = {
        **{
            prefix + "*": replace(shipped_facts_for_model(prefix), tool_mode="prompt_based")
            for prefix in PROMPT_BASED_MODEL_PREFIXES
        },
        **{
            glob: replace(
                shipped_facts_for_model(glob.rstrip("*")), wire_protocol="responses"
            )
            for glob in RESPONSES_WIRE_GLOBS
        },
    }

    # ------------------------------------------------------------------
    # Model classification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_responses_api_model(model: str) -> bool:
        """Seed predicate: does this model's NAME match the legacy prefixes?

        ADR 0012 W2: this is no longer the router. It survives as the seed
        form of `RESPONSES_WIRE_GLOBS` and for the 404 auto-fallback's log
        line. Routing asks `_wire_for(model)`, which reads the per-model
        fact and therefore honours an operator override — the thing
        `api_path` was declared for and never did (debt Item 61).
        """
        return model.lower().startswith(RESPONSES_API_PREFIXES)

    def _wire_for(self, model: str) -> str:
        """The wire protocol this model speaks. The single routing question.

        One reader, so an operator override of `wire_protocol` reaches every
        send path at once — previously each of the three call sites asked the
        hardcoded prefix tuple independently.
        """
        return self.get_facts_for_model(model).wire_protocol

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
    # Public interface
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[Message],
        model: str,
        stream: bool = True,
        tools: list[dict[str, Any]] | None = None,
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
        if self._wire_for(model) == "responses":
            async for event in get_handler("responses").chat(
                self, messages, model, stream, tools
            ):
                yield event
        else:
            async for event in self._chat_completions_api(messages, model, stream, tools):
                yield event

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
        # Codex / Pro models 404 on Chat Completions — route them through the
        # Responses API just like chat() / oneshot() do.
        if self._wire_for(model) == "responses":
            return get_handler("responses").oneshot(
                self, messages, model, self._get_max_tokens(model)
            ).get("content", "")

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

        Same return shape as OpenAICompatibleProvider.oneshot
        ({content, finish_reason, model, usage}). Native OpenAI uses the
        same Chat Completions SDK path as the compat provider, so this
        composes the existing message conversion + token-param handling.

        Codex / Pro models (RESPONSES_API_PREFIXES) 404 on Chat Completions,
        so they route through the Responses API here exactly as `chat()` does
        — otherwise `/v1/oneshot` and `/v1/agent/run` would raise for a whole
        model class that works fine over `/chat`. (response_format is not
        forwarded on the Responses path — structured output there uses a
        different knob; out of scope for this stateless call.)
        """
        messages: list[Message] = []
        if system:
            messages.append(Message(role="system", content=system))
        messages.append(Message(role="user", content=prompt))

        if self._wire_for(model) == "responses":
            return get_handler("responses").oneshot(self, messages, model, max_tokens)

        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._convert_messages(messages),
            "stream": False,
        }

        use_completion_tokens = self._needs_max_completion_tokens(model)
        token_key = "max_completion_tokens" if use_completion_tokens else "max_tokens"
        if max_tokens is not None:
            request_kwargs[token_key] = max_tokens
        else:
            configured_max = self._get_max_tokens(model)
            if configured_max:
                request_kwargs[token_key] = configured_max

        if temperature is not None and not use_completion_tokens:
            # o-series / GPT-5.x reject temperature; only set when supported.
            request_kwargs["temperature"] = temperature
        if response_format is not None:
            request_kwargs["response_format"] = response_format

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

    async def _chat_completions_api(
        self,
        messages: list[Message],
        model: str,
        stream: bool = True,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Event]:
        """Chat Completions API path for standard models.

        Handles GPT-4.1, GPT-5.x, o-series with proper parameter handling.
        """
        try:
            api_messages = self._convert_messages(messages)

            yield Event(EventType.STREAM_START, {"model": model})

            # Build request kwargs
            request_kwargs: dict[str, Any] = {
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

            # Per-model, not per-provider: get_facts_for_model()
            # is the hook that lets a provider mark individual models
            # prompt-based. Reading self.capabilities here ignored it --
            # o4-mini resolved False but was sent native tools anyway.
            if tools and self.get_facts_for_model(model).tool_mode != "prompt_based":
                request_kwargs["tools"] = tools
                request_kwargs["tool_choice"] = "auto"

            # v1.18.3 follow-up: vendor-specific extra_body pass-through.
            # Forwarded only when configured to keep wire payloads clean.
            extra_body = self._get_extra_body(model)
            if extra_body:
                request_kwargs["extra_body"] = extra_body

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
                async for event in get_handler("responses").chat(
                    self, messages, model, stream, tools
                ):
                    yield event
                return
            # v1.18.3 follow-up: typed throttle event + persistent telemetry.
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

    async def _stream_chat_completions(
        self,
        request_kwargs: dict[str, Any],
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
        request_kwargs: dict[str, Any],
    ) -> AsyncIterator[Event]:
        """Handle non-streaming Chat Completions response."""
        # Off-load the blocking SDK call so a non-streaming agent-tier run
        # doesn't starve the event loop (v1.19.x — see openai_compat.chat).
        response = await asyncio.to_thread(
            lambda: self.client.chat.completions.create(
                **request_kwargs,
                stream=False,
            )
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

        metadata: dict[str, Any] = {"usage": usage}
        if hasattr(message, "tool_calls") and message.tool_calls:
            metadata["tool_calls"] = [
                {"id": tc.id, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in message.tool_calls
            ]
        if reasoning_content:
            metadata["reasoning"] = reasoning_content
        yield Event(EventType.STREAM_END, content, metadata)


    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    @staticmethod
    def _format_error(e: Exception) -> str:
        """Format exception into user-friendly error message."""
        error_type = type(e).__name__
        error_str = str(e)

        if isinstance(e, openai.APIConnectionError):
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

        if isinstance(e, openai.AuthenticationError):
            return (
                "Authentication failed: Invalid OpenAI API key.\n"
                "Check your OPENAI_API_KEY in ~/.ppxai/.env"
            )

        if isinstance(e, openai.RateLimitError):
            return "Rate limit exceeded. Please wait before retrying."

        if isinstance(e, openai.BadRequestError):
            # Check for model not found (codex 404s on Chat Completions)
            if "404" in error_str or "not found" in error_str.lower():
                return (
                    "Model not found or unsupported API. "
                    "If using a Codex model, ensure it's routed to Responses API."
                )
            if "'message':" in error_str:
                match = re.search(r"'message':\s*'([^']+)'", error_str)
                if match:
                    return f"Invalid request: {match.group(1)}"
            return f"Invalid request: {error_str}"

        if isinstance(e, openai.APIStatusError):
            return f"OpenAI API error ({e.status_code}): {error_str}"

        if isinstance(e, httpx.ConnectError):
            return "Connection failed: Unable to connect to OpenAI API."

        return f"{error_type}: {error_str}"

    @staticmethod
    def _log_error_traceback(e: Exception) -> None:
        """Log full exception traceback for debugging."""
        if logger.enabled:
            logger.error(f"OpenAI native provider error: {type(e).__name__}: {e}")
            logger.debug(f"Full traceback:\n{traceback.format_exc()}")
