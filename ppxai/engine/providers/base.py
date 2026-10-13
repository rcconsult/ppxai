"""
Base provider abstract class.

All AI providers must implement this interface.
"""

import asyncio
import traceback
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ...common.logger import get_logger
from ...config import (
    get_extra_body,
    get_generation_params,
    get_model_max_tokens,
    get_reasoning_trigger,
)
from .. import facts_config as _facts_config
from ..model_facts import ModelFacts, shipped_facts_for_model
from ..types import Event, Message, ModelInfo, ProviderCapabilities, UsageStats
from .wire import get_handler

logger = get_logger(__name__)


class BaseProvider(ABC):
    """Abstract base class for all AI providers.

    Providers handle communication with AI APIs and emit events that clients consume.
    Wire-neutral: no provider SDK is imported here (ADR 0016 §4). Each
    subclass builds its own client; the two that call through the OpenAI SDK
    get its client builder and error mapping from `openai_wire`.
    """

    # Class attributes to be overridden
    name: str = "base"
    default_capabilities: ProviderCapabilities = ProviderCapabilities()

    #: This provider's own per-model rows, `{model_or_glob: ModelFacts}`,
    #: consulted BEFORE the global shipped table (ADR 0012 §2 Q0e).
    #:
    #: The provider dimension exists because one model id is not one model:
    #: `anthropic/claude-sonnet-5` is reached over `responses` on Perplexity
    #: and `chat_completions` on OpenRouter, so its `wire_protocol` has no
    #: single correct global value. Rows here are complete records and win
    #: whole — there is no field-level merge against the global table.
    shipped_model_facts: dict[str, ModelFacts] = {}

    #: The floor for a model no table names, when the GLOBAL floor would be
    #: wrong for this provider (ADR 0012 §2 Q0e). A COMPLETE record, chosen
    #: whole — never merged field-by-field, so there is still nothing to
    #: arbitrate.
    #:
    #: `None` means the global `UNMEASURED` applies, which is right for
    #: every provider that speaks `chat_completions`. `GeminiProvider`
    #: overrides it because it can ONLY speak `generate_content`: routing an
    #: unlisted Gemini model to a chat-completions handler is not a
    #: conservative default, it is a wire the provider does not have.
    unmeasured_facts: ModelFacts | None = None

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        models: dict[str, dict[str, str]] | None = None,
        capabilities: ProviderCapabilities | None = None,
        provider_id: str | None = None,
        **kwargs
    ):
        """Initialize the provider.

        Args:
            api_key: API key for authentication
            base_url: Base URL for the API, kept for subclasses that use one
            models: Dictionary of available models
            capabilities: Provider capabilities (native features)
            provider_id: Provider identifier (e.g., "openai", "custom") for config lookup
            **kwargs: Additional provider-specific options
        """
        self.api_key = api_key
        self.base_url = base_url
        self.models = models or {}
        self.capabilities = capabilities or self.default_capabilities
        self.provider_id = provider_id  # Used by _get_generation_params(), _get_max_tokens()

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        model: str,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[Event]:
        """Send a chat request and yield events.

        Args:
            messages: Conversation history
            model: Model ID to use
            stream: Whether to stream the response
            tools: Optional list of tools in OpenAI format (for native tool calling)

        Yields:
            Event objects (STREAM_START, STREAM_CHUNK, STREAM_END, ERROR, TOOL_CALL)
        """
        pass

    @abstractmethod
    def oneshot(
        self,
        prompt: str,
        model: str,
        system: str | None = None,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Stateless single-turn completion (the v1 gateway contract).

        Backs `POST /v1/oneshot` and the tool-FREE `POST /v1/agent/run`
        tier. No history, no tools, no streaming. Every provider must
        implement this so those tiers are provider-agnostic (v1.19.x: was
        only on OpenAICompatibleProvider, which forced an
        isinstance-by-class guard on the v1 routes).

        Returns:
            ``{"content": str, "finish_reason": str | None,
              "model": str, "usage": {prompt_tokens, completion_tokens,
              total_tokens} | None}``
        """
        ...

    def chat_sync(
        self,
        messages: list[Message],
        model: str,
        stream: bool = False
    ) -> list[Event]:
        """Synchronous chat method.

        Args:
            messages: Conversation history
            model: Model ID to use
            stream: Whether to stream the response

        Returns:
            List of Event objects
        """
        events = []

        async def collect():
            async for event in self.chat(messages, model, stream):
                events.append(event)

        asyncio.run(collect())
        return events

    def list_models(self) -> list[ModelInfo]:
        """Return available models for this provider.

        Returns:
            List of ModelInfo objects
        """
        return [
            ModelInfo(
                # Use actual model ID from info dict (numbered format has id inside)
                id=info.get("id", model_key),
                name=info.get("name", info.get("id", model_key)),
                description=info.get("description", ""),
                context_length=info.get("context_length")
            )
            for model_key, info in self.models.items()
        ]

    def get_capabilities(self) -> ProviderCapabilities:
        """What this ENDPOINT can do, with operator config applied.

        `ProviderCapabilities` is a statement about the *service* — built-in
        search, fetch, weather, citations, streaming — so it takes no model
        argument (ADR 0012 §2 Q0e). Measured across the shipped example
        config, every one of these fields is stated per provider and none is
        stated per model, because no model changes whether the endpoint it
        sits behind has a search index.

        The per-model half of the old signature moved to
        :meth:`get_facts_for_model`, which answers a disjoint set of
        questions. Nothing can be asked of both.

        Returns:
            ProviderCapabilities for this provider
        """
        provider_key = self.provider_id or self.name
        if not provider_key:
            return self.capabilities
        try:
            return _facts_config.apply_provider_overrides(
                self.capabilities, provider_key
            )
        except Exception:  # noqa: BLE001 — config must never break a request
            return self.capabilities

    def shipped_facts_for_model(self, model: str) -> ModelFacts:
        """What THIS provider's own code says about `model`.

        Override this, not `get_facts_for_model`. The default consults the
        shipped table, which is where a provider's benchmark-derived rows
        live; a provider overrides only when it knows something the table
        cannot express.

        Split from the public accessor so operator config sits ABOVE every
        provider without each one remembering to consult it — a subclass that
        overrode the public method would otherwise silently drop the config
        layer, the same "override bypasses the shared path" shape that made
        the per-model hook unreachable in the first place (plan I1).

        Args:
            model: Model ID (e.g., "gpt-5.2", "o4-mini")

        Returns:
            ModelFacts as shipped, before operator overrides
        """
        return shipped_facts_for_model(
            model, self.shipped_model_facts, self.unmeasured_facts
        )

    def get_facts_for_model(self, model: str) -> ModelFacts:
        """Effective per-model facts — the accessor callers use.

        Two rungs and no arbitration (ADR 0012 §2 Q0e): the shipped row, then
        `providers.<p>.models.<m>.facts`. A provider-level block cannot reach
        this result, because none of these fields is a provider field — which
        is precisely what makes the debt Item 43 regression structurally
        impossible rather than merely tested-against.

        Args:
            model: Model ID (e.g., "gpt-5.2", "o4-mini")

        Returns:
            ModelFacts for the model
        """
        shipped = self.shipped_facts_for_model(model)
        provider_key = self.provider_id or self.name
        if not provider_key:
            return shipped
        try:
            return _facts_config.resolve_model_facts(shipped, provider_key, model)
        except Exception:  # noqa: BLE001 — config must never break a request
            return shipped

    def _get_generation_params(self, model: str) -> dict[str, Any]:
        """Get generation parameters (temperature, top_p, etc.) from config.

        Args:
            model: Model ID to check

        Returns:
            Dict of generation params to pass to API (empty if none configured)
        """
        try:
            provider = self.provider_id or self.name
            return get_generation_params(provider, model)
        except AttributeError:
            return {}

    def _get_max_tokens(self, model: str) -> int | None:
        """Get max_tokens for output generation from config.

        Args:
            model: Model ID to check

        Returns:
            max_tokens value or None to use provider default
        """
        try:
            return get_model_max_tokens(self.provider_id, model)
        except AttributeError:
            return None

    def _get_extra_body(self, model: str) -> dict[str, Any]:
        """Get vendor-specific ``extra_body`` payload for a model.

        v1.18.3: thin instance wrapper over :func:`get_extra_body` so
        provider subclasses can override / extend the resolved payload
        without having to re-import config helpers. Returns an empty dict
        when no provider/model entry is configured.
        """
        try:
            return get_extra_body(self.provider_id, model)
        except AttributeError:
            return {}

    def _apply_reasoning_trigger(
        self,
        api_messages: list[dict[str, Any]],
        model: str,
    ) -> list[dict[str, Any]]:
        """Append the configured reasoning trigger to the system message.

        v1.18.3: nemotron's reasoning toggle is an in-prompt convention
        — ``/think`` enables it, ``/no_think`` disables it. This helper
        looks up :func:`get_reasoning_trigger` for ``self.provider_id``
        + ``model`` and (when configured) appends the marker on its own
        line to the FIRST ``role == 'system'`` message. Idempotent: if
        the trigger is already present at the end of that system
        message, the helper is a no-op.

        When no system message exists, a new one is prepended carrying
        only the trigger — so users get correct behavior without having
        to also specify a base system_prompt.

        Returns a new list (does not mutate the input). Callers pass the
        result downstream; if the trigger is unconfigured, the input is
        returned unchanged.
        """
        try:
            trigger = get_reasoning_trigger(self.provider_id, model)
        except AttributeError:
            trigger = None
        if not trigger:
            return api_messages

        # Locate the first system message.
        for idx, msg in enumerate(api_messages):
            if msg.get("role") == "system":
                content = msg.get("content") or ""
                if isinstance(content, str) and content.rstrip().endswith(trigger):
                    return api_messages  # already applied — idempotent
                new_content = (content + ("\n\n" if content else "") + trigger) if isinstance(content, str) else content
                # Build a shallow copy so the original isn't mutated.
                updated = list(api_messages)
                new_msg = dict(msg)
                new_msg["content"] = new_content
                updated[idx] = new_msg
                return updated

        # No system message present — prepend one carrying only the trigger.
        return [{"role": "system", "content": trigger}, *api_messages]

    def _convert_messages(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert Message objects to Chat Completions wire format.

        ADR 0012 W4: the body moved to
        `wire.chat_completions.ChatCompletionsHandler.convert_messages`. It
        stays reachable here because most providers speak this wire and call
        it directly, but it is now one protocol's converter *delegated to*
        rather than one protocol's emitter *installed as the shared default*
        — the distinction debt Item 62 (b) is about. A provider on another
        wire asks its own handler instead of overriding this with an
        incompatible return type.
        """
        return get_handler("chat_completions").convert_messages(messages)

    def _parse_usage(self, usage) -> UsageStats | None:
        """Parse usage from API response.

        Args:
            usage: Usage object from API response

        Returns:
            UsageStats object or None
        """
        if not usage:
            return None
        return UsageStats(
            prompt_tokens=getattr(usage, 'prompt_tokens', 0) or 0,
            completion_tokens=getattr(usage, 'completion_tokens', 0) or 0,
            total_tokens=getattr(usage, 'total_tokens', 0) or 0,
        )

    def _format_error(self, e: Exception) -> str:
        """Format exception into user-friendly error message.

        Provides clear, actionable messages for common errors while preserving
        technical details for debugging when needed.

        Args:
            e: The exception to format

        Returns:
            User-friendly error message
        """
        error_type = type(e).__name__
        error_str = str(e)

        # SDK-specific errors are mapped by the subclass's wire layer
        # (`openai_wire.OpenAIWireMixin`) or by the provider itself, which
        # then falls back here.

        # httpx-level connection errors
        if isinstance(e, httpx.ConnectError):
            return "Connection failed: Unable to connect to the server."

        # Fallback: return the exception type and message without full traceback
        return f"{error_type}: {error_str}"

    def _classify_throttle(self, e: Exception) -> dict[str, Any] | None:
        """Structured payload for ``EventType.PROVIDER_THROTTLED``, or None.

        A subclass returns ``{status_code, provider, message, retry_after}``
        for a provider-side 403/429 so the caller can emit a throttle event
        instead of ``EventType.ERROR``. The base knows no SDK exception
        (ADR 0016 §4); the OpenAI wire (`openai_wire.OpenAIWireMixin`),
        Gemini and Anthropic override this.
        """
        return None

    def _log_error_traceback(self, e: Exception) -> None:
        """Log full exception traceback to debug log for troubleshooting.

        This preserves detailed error information for debugging while keeping
        the user-facing message clean.

        Args:
            e: The exception to log
        """
        try:
            logger = get_logger("tui")
            if logger.enabled:
                logger.error(f"Provider error: {type(e).__name__}: {e}")
                logger.debug(f"Full traceback:\n{traceback.format_exc()}")
        except Exception:
            pass  # Logger not available, skip
