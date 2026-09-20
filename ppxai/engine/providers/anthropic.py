"""Native provider for the Anthropic Messages API (ROADMAP Phase 1).

The fourth account type, speaking the fourth wire. `AnthropicProvider` owns
the account — key, model list, price table, error classification — and
delegates message conversion to `wire.messages.MessagesHandler`, exactly the
split ADR 0012 defines.

**Why not OpenAI-compatible.** Anthropic publishes an OpenAI-compatible
shim, and routing Claude through `OpenAICompatibleProvider` would have been
a config entry rather than a module. It would also have cost every
Claude-specific capability this file exists to reach: adaptive thinking and
`effort`, prompt caching (and its three input-token billing classes),
`stop_reason: "refusal"` with structured `stop_details`, and server tools.
The shim flattens all of that into the chat-completions shape.

**Async client on purpose.** `chat()` is an async generator on a running
event loop. The Gemini provider bridges its sync SDK with
`asyncio.to_thread`, which is correct for a single call and wrong for a
stream — every chunk would hop threads. `anthropic.AsyncAnthropic` streams
natively, so the loop is never blocked.

**TLS.** `anthropic` 1.x is built on **httpx2**, not httpx. Passing the
`httpx.Client` the other providers build (`ppxai/config/tls.py` ->
`tls_verify()`) is rejected at request time, so the verify policy goes
through `anthropic.DefaultAsyncHttpxClient`, which subclasses `httpx2.Client`
and keeps the SDK's own timeout and connection-limit defaults. The policy
itself is still the shared resolver's — one place decides TLS for every
outbound client in ppxai.

**Thinking is configured, never prompted.** `budget_tokens` is rejected with
a 400 on Claude Opus 5, Sonnet 5 and the 4.7/4.8 family; the fixed-budget
concept is replaced by adaptive thinking plus `output_config.effort`. This
provider sends `{"type": "adaptive", "display": "summarized"}` so ppxai's
existing `REASONING_CHUNK` event has something to carry — the default is
`"omitted"`, which streams empty thinking blocks and would make the reasoning
pane look like a long pause.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from ...common.logger import get_logger
from ...config.tls import tls_verify
from ..model_facts import ModelFacts
from ..types import Event, EventType, Message, ProviderCapabilities, UsageStats
from .base import BaseProvider
from .wire import get_handler

logger = get_logger("provider")

# Optional dependency, gated behind the `[anthropic]` extra so users opt into
# it — same shape as the gemini extra.
_anthropic_available = False
try:
    import anthropic
    _anthropic_available = True
except ImportError:
    anthropic = None


def is_available() -> bool:
    """True when the `anthropic` SDK is importable."""
    return _anthropic_available


#: Streaming default. The guidance for agentic work is 64k, and a low cap is
#: not a cost control: hitting it truncates mid-thought and buys a retry,
#: so cost per COMPLETED task gets worse, not better.
DEFAULT_MAX_TOKENS = 64000

#: Non-streaming default, kept under the SDK's 10-minute HTTP timeout.
DEFAULT_ONESHOT_MAX_TOKENS = 16000


class AnthropicProvider(BaseProvider):
    """Claude over `POST /v1/messages`.

    Inherits the shared surface from `BaseProvider` (`list_models`,
    `get_facts_for_model`, `get_capabilities`, `_get_generation_params`,
    `_get_max_tokens`).
    """

    name = "anthropic"

    #: Stands in when a caller builds a config with no target model.
    default_model_for_facts = "claude-opus-5"

    #: An UNLISTED Claude model still speaks `messages` — this provider has
    #: no other wire. The global floor says `chat_completions`, which is safe
    #: everywhere else and simply wrong here, so this supplies its own
    #: complete floor (ADR 0012 §2 Q0e), exactly as Gemini does.
    #:
    #: `tool_mode` stays at the conservative default: the wire is a fact
    #: about the endpoint, tool support is a fact about the model, and only
    #: the first is knowable without measuring.
    unmeasured_facts = ModelFacts(wire_protocol="messages")

    #: Per-model rows, consulted BEFORE the global shipped table. Every
    #: current Claude model is native-tool-capable over `messages` and
    #: supports vision and reasoning.
    shipped_model_facts: dict[str, ModelFacts] = {
        "claude-*": ModelFacts(
            wire_protocol="messages",
            tool_mode="native",
            parallel_tool_calls=True,
            supports_reasoning=True,
            supports_vision=True,
            max_tokens=DEFAULT_MAX_TOKENS,
        ),
    }

    default_capabilities = ProviderCapabilities(
        web_search=False,   # server-side web_search is a per-request tool, not an account fact
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
        effort: str | None = None,
        enable_thinking: bool = True,
        enable_prompt_caching: bool = True,
        provider_id: str | None = None,
        **kwargs,
    ):
        """Initialize the Anthropic provider.

        Args:
            api_key: Anthropic API key (`ANTHROPIC_API_KEY`).
            models: Available models.
            capabilities: Provider capabilities.
            effort: `low`|`medium`|`high`|`xhigh`|`max`. None leaves the
                model's own default (`high`).
            enable_thinking: Send adaptive thinking (default True).
            enable_prompt_caching: Ask the API to cache the stable prefix
                (default True). This is the single largest cost lever on an
                agent loop, and it is only measurable because
                `calculate_cost` now prices cache reads and writes as their
                own token classes.
            provider_id: Provider identifier for config lookup.
        """
        if not _anthropic_available:
            raise ImportError(
                "anthropic package not installed. "
                "Install with: pip install ppxai[anthropic]"
            )

        self.effort = effort
        self.enable_thinking = enable_thinking
        self.enable_prompt_caching = enable_prompt_caching

        kwargs.pop("base_url", None)

        # base_url=None skips the OpenAI client BaseProvider would build.
        super().__init__(
            api_key=api_key,
            base_url=None,
            models=models,
            capabilities=capabilities,
            provider_id=provider_id or "anthropic",
            **kwargs,
        )

        self.client = anthropic.AsyncAnthropic(
            api_key=api_key,
            http_client=anthropic.DefaultAsyncHttpxClient(verify=tls_verify()),
        )
        self.sync_client = anthropic.Anthropic(
            api_key=api_key,
            http_client=anthropic.DefaultHttpxClient(verify=tls_verify()),
        )

    # -- request shaping ---------------------------------------------------

    def _request_kwargs(self, model: str, max_tokens: int) -> dict[str, Any]:
        """The parameters every request on this wire carries.

        Deliberately NOT here: `temperature` / `top_p` / `top_k`, which are
        rejected with a 400 on Claude Opus 5, Sonnet 5 and the 4.7/4.8
        family. `_get_generation_params()` may well return them from an
        operator's config — they are filtered rather than forwarded, because
        a config written for another provider must not make every Claude
        request fail.
        """
        kwargs: dict[str, Any] = {"model": model, "max_tokens": max_tokens}

        params = dict(self._get_generation_params(model) or {})
        dropped = [k for k in ("temperature", "top_p", "top_k") if k in params]
        if dropped:
            logger.debug(
                f"anthropic: dropping sampling params {dropped} for {model} — "
                f"rejected on this wire"
            )

        if self.enable_thinking:
            # `display: summarized` is opt-in: the API default is `omitted`,
            # which streams empty thinking blocks.
            kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}

        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}

        if self.enable_prompt_caching:
            # Top-level auto-caching: caches the last cacheable block, which
            # on this wire is the tools+system prefix ppxai resends on every
            # turn of an agent loop.
            kwargs["cache_control"] = {"type": "ephemeral"}

        return kwargs

    @staticmethod
    def _convert_tools(openai_tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """OpenAI tool schemas -> Anthropic `tools`.

        `{"type": "function", "function": {...}}` becomes a flat
        `{name, description, input_schema}`.
        """
        if not openai_tools:
            return None
        out = []
        for t in openai_tools:
            fn = t.get("function", t)
            out.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return out or None

    @staticmethod
    def _usage(raw) -> UsageStats | None:
        """Anthropic usage -> UsageStats, keeping the cache classes apart.

        Folding cache reads into `prompt_tokens` would over-report cost by
        up to 10x on the cached portion — the reason `UsageStats` grew the
        two cache fields.
        """
        if raw is None:
            return None
        prompt = getattr(raw, "input_tokens", 0) or 0
        completion = getattr(raw, "output_tokens", 0) or 0
        cache_write = getattr(raw, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(raw, "cache_read_input_tokens", 0) or 0
        return UsageStats(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion + cache_write + cache_read,
            cache_creation_input_tokens=cache_write,
            cache_read_input_tokens=cache_read,
        )

    @staticmethod
    def _refusal_message(response) -> str | None:
        """Human-readable text when the model declined, else None.

        `stop_details` is populated ONLY for `stop_reason == "refusal"` and
        is None for every other stop reason, so it is guarded rather than
        read directly.
        """
        if getattr(response, "stop_reason", None) != "refusal":
            return None
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) if details else None
        explanation = getattr(details, "explanation", None) if details else None
        parts = ["The model declined this request"]
        if category:
            parts.append(f"(category: {category})")
        if explanation:
            parts.append(f"— {explanation}")
        return " ".join(parts)

    # -- BaseProvider contract --------------------------------------------

    async def chat(
        self,
        messages: list[Message],
        model: str,
        stream: bool = True,
        tools: list[dict[str, Any]] | None = None,
        **kwargs,
    ) -> AsyncIterator[Event]:
        """Stream a turn, emitting engine events."""
        system, wire_messages = get_handler("messages").convert_messages(messages)
        max_tokens = self._get_max_tokens(model) or DEFAULT_MAX_TOKENS

        request = self._request_kwargs(model, max_tokens)
        request["messages"] = wire_messages
        if system:
            request["system"] = system
        converted = self._convert_tools(tools)
        if converted:
            request["tools"] = converted

        yield Event(type=EventType.STREAM_START, data={"model": model})

        try:
            async with self.client.messages.stream(**request) as stream_ctx:
                async for event in stream_ctx:
                    etype = getattr(event, "type", "")
                    if etype == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        dtype = getattr(delta, "type", "")
                        if dtype == "text_delta":
                            yield Event(
                                type=EventType.STREAM_CHUNK,
                                data={"content": delta.text},
                            )
                        elif dtype == "thinking_delta":
                            yield Event(
                                type=EventType.REASONING_CHUNK,
                                data={"content": getattr(delta, "thinking", "")},
                            )

                final = await stream_ctx.get_final_message()

            refusal = self._refusal_message(final)
            if refusal:
                yield Event(type=EventType.ERROR, data={"error": refusal})
                return

            for block in final.content:
                if getattr(block, "type", "") == "tool_use":
                    yield Event(
                        type=EventType.TOOL_CALL,
                        data={
                            "id": getattr(block, "id", "") or f"call_{uuid.uuid4().hex[:8]}",
                            "name": block.name,
                            # Already a decoded object on this wire — no
                            # json.loads of a string, and never string
                            # matching on the serialized form.
                            "arguments": block.input if isinstance(block.input, dict) else {},
                        },
                    )

            text = "".join(
                b.text for b in final.content if getattr(b, "type", "") == "text"
            )
            yield Event(
                type=EventType.STREAM_END,
                data={"content": text},
                metadata={"usage": self._usage(getattr(final, "usage", None))},
            )

        except Exception as e:  # noqa: BLE001 — classified below
            throttle = self._classify_throttle(e)
            if throttle is not None:
                yield Event(type=EventType.PROVIDER_THROTTLED, data=throttle)
                return
            logger.error(f"anthropic chat failed: {self._format_error(e)}")
            yield Event(type=EventType.ERROR, data={"error": self._format_error(e)})

    def oneshot(
        self,
        prompt: str,
        model: str,
        system: str | None = None,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Stateless single turn (the v1 gateway contract).

        `temperature` is accepted and ignored: the parameter is rejected on
        this wire, and the alternative — forwarding it and 400-ing — would
        make `/v1/oneshot` fail for any caller that sets it out of habit.
        """
        wire_messages_src: list[Message] = []
        if system:
            wire_messages_src.append(Message(role="system", content=system))
        wire_messages_src.append(Message(role="user", content=prompt))

        sys_text, wire_messages = get_handler("messages").convert_messages(wire_messages_src)

        request = self._request_kwargs(
            model, max_tokens or DEFAULT_ONESHOT_MAX_TOKENS
        )
        request["messages"] = wire_messages
        if sys_text:
            request["system"] = sys_text
        if response_format:
            # Structured outputs go through output_config.format — never the
            # deprecated top-level output_format, and never an assistant
            # prefill (a 400 on every current Claude model).
            oc = dict(request.get("output_config") or {})
            oc["format"] = response_format
            request["output_config"] = oc

        response = self.sync_client.messages.create(**request)

        refusal = self._refusal_message(response)
        content = "".join(
            b.text for b in response.content if getattr(b, "type", "") == "text"
        )
        reasoning = "".join(
            getattr(b, "thinking", "") or ""
            for b in response.content
            if getattr(b, "type", "") == "thinking"
        )

        usage_stats = self._usage(getattr(response, "usage", None))
        usage_dict = None
        if usage_stats is not None:
            usage_dict = {
                "prompt_tokens": usage_stats.prompt_tokens,
                "completion_tokens": usage_stats.completion_tokens,
                "total_tokens": usage_stats.total_tokens,
                "cache_creation_input_tokens": usage_stats.cache_creation_input_tokens,
                "cache_read_input_tokens": usage_stats.cache_read_input_tokens,
            }

        result = {
            "content": content if not refusal else "",
            "finish_reason": getattr(response, "stop_reason", None),
            "model": getattr(response, "model", model),
            "usage": usage_dict,
        }
        if reasoning:
            result["reasoning"] = reasoning
        if refusal:
            # Surfaced rather than raised: a refusal is a 200 with a reason,
            # and a caller that only reads `content` must not mistake it for
            # an empty completion.
            result["refusal"] = refusal
        return result

    # -- error classification ---------------------------------------------

    def _classify_throttle(self, e: Exception) -> dict[str, Any] | None:
        """429/403 -> the PROVIDER_THROTTLED payload, else None."""
        if not _anthropic_available:
            return None
        status = getattr(e, "status_code", None)
        if status not in (403, 429):
            return None
        retry_after = None
        response = getattr(e, "response", None)
        if response is not None:
            raw = getattr(response, "headers", {}).get("retry-after")
            if raw:
                try:
                    retry_after = float(raw)
                except (TypeError, ValueError):
                    retry_after = None
        return {
            "status_code": status,
            "provider": self.name,
            "model": "",
            "message": self._format_error(e),
            "retry_after": retry_after,
        }

    def _format_error(self, e: Exception) -> str:
        """Typed chain, most specific first — a single broad handler would
        lose the retryable/non-retryable distinction the caller needs."""
        if not _anthropic_available:
            return str(e)
        if isinstance(e, anthropic.AuthenticationError):
            return "Anthropic rejected the API key (check ANTHROPIC_API_KEY)."
        if isinstance(e, anthropic.PermissionDeniedError):
            return "The API key lacks permission for this model or feature."
        if isinstance(e, anthropic.NotFoundError):
            return "Unknown model or endpoint — check the configured model id."
        if isinstance(e, anthropic.RateLimitError):
            return "Rate limited by Anthropic. Retry after the cooldown."
        if isinstance(e, anthropic.BadRequestError):
            return f"Anthropic rejected the request: {getattr(e, 'message', e)}"
        if isinstance(e, anthropic.APIStatusError):
            status = getattr(e, "status_code", "?")
            if isinstance(status, int) and status >= 500:
                return f"Anthropic server error ({status}). Retry later."
            return f"Anthropic API error ({status}): {getattr(e, 'message', e)}"
        if isinstance(e, anthropic.APIConnectionError):
            return "Could not reach the Anthropic API (network or TLS)."
        return f"{type(e).__name__}: {e}"
