"""
Base provider abstract class.

All AI providers must implement this interface.
"""

import asyncio
import re
import traceback
from abc import ABC, abstractmethod
from typing import List, Dict, Any, AsyncIterator, Optional
import os
import httpx
import openai
from openai import OpenAI

from ..model_facts import ModelFacts, shipped_facts_for_model
from ..model_profiles import ModelProfile, get_profile
from ..types import Message, Event, EventType, ProviderCapabilities, ModelInfo, UsageStats
from ..uploaded_file import flatten_uploaded_file_blocks, assert_wire_blocks_clean
from .wire import get_handler
from ...config import (
    get_generation_params,
    get_model_max_tokens,
    get_extra_body,
    get_reasoning_trigger,
)
from ...config.tls import tls_verify
from ...common.logger import get_logger


class BaseProvider(ABC):
    """Abstract base class for all AI providers.

    Providers handle communication with AI APIs and emit events that clients consume.
    Subclasses that don't use the OpenAI SDK (e.g., GeminiProvider) should pass
    base_url=None and create their own client after calling super().__init__().
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
    shipped_model_facts: Dict[str, ModelFacts] = {}

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
    unmeasured_facts: Optional[ModelFacts] = None

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        models: Optional[Dict[str, Dict[str, str]]] = None,
        capabilities: Optional[ProviderCapabilities] = None,
        provider_id: Optional[str] = None,
        **kwargs
    ):
        """Initialize the provider.

        Args:
            api_key: API key for authentication
            base_url: Base URL for the API (None skips OpenAI client creation)
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

        # Skip OpenAI client creation when base_url is None
        # (providers like GeminiProvider and OpenAINativeProvider create their own clients)
        if base_url is None:
            return

        # TLS verification: env (SSL_VERIFY / SSL_CERT_FILE) then
        # network.ssl.* in ppxai-config.json. Resolved in ONE place so this
        # site cannot drift from the other outbound clients — it already had
        # (see ppxai/config/tls.py). tls_verify() returns False (off) or an
        # SSLContext — never True — so the client always carries an explicit
        # policy; a `verify is True` fast path would be dead code.
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=httpx.Client(verify=tls_verify()),
        )

    @abstractmethod
    async def chat(
        self,
        messages: List[Message],
        model: str,
        stream: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None
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
        system: Optional[str] = None,
        response_format: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
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
        messages: List[Message],
        model: str,
        stream: bool = False
    ) -> List[Event]:
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

    def list_models(self) -> List[ModelInfo]:
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

    def validate_config(self) -> bool:
        """Validate provider configuration.

        Default: requires api_key. Providers that need base_url (e.g.,
        OpenAICompatibleProvider) should override.

        Returns:
            True if configuration is valid
        """
        return bool(self.api_key)

    def needs_tool(self, tool_category: str) -> bool:
        """Check if provider needs a tool (doesn't have native capability).

        Args:
            tool_category: Category like 'web_search', 'weather', etc.

        Returns:
            True if provider needs this tool (doesn't have native capability)
        """
        return not getattr(self.capabilities, tool_category, False)

    def get_model_profile(self, model: str) -> ModelProfile:
        """Get the behavioral profile for a model.

        Returns the ModelProfile that controls tool calling strategy, API
        routing, and parameter handling. Providers can override this to
        return custom profiles; the default looks up the built-in registry.

        Args:
            model: Model ID (e.g., "gpt-5.2", "sonar-pro")

        Returns:
            ModelProfile for the model
        """
        return get_profile(model)

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
            from ...config.facts_config import apply_provider_overrides

            return apply_provider_overrides(self.capabilities, provider_key)
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
            from ...config.facts_config import resolve_model_facts

            return resolve_model_facts(shipped, provider_key, model)
        except Exception:  # noqa: BLE001 — config must never break a request
            return shipped

    def _get_generation_params(self, model: str) -> Dict[str, Any]:
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

    def _get_max_tokens(self, model: str) -> Optional[int]:
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

    def _get_extra_body(self, model: str) -> Dict[str, Any]:
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
        api_messages: List[Dict[str, Any]],
        model: str,
    ) -> List[Dict[str, Any]]:
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

    def _convert_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
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

    def _parse_usage(self, usage) -> Optional[UsageStats]:
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

        # Connection errors (no network, DNS failure, VPN required)
        if isinstance(e, openai.APIConnectionError):
            # Extract the root cause
            if "getaddrinfo failed" in error_str:
                return (
                    f"Connection failed: Unable to resolve hostname.\n"
                    f"Check that:\n"
                    f"  - You have network connectivity\n"
                    f"  - VPN is connected (if required for this endpoint)\n"
                    f"  - The API endpoint URL is correct"
                )
            elif "Connection refused" in error_str:
                return (
                    f"Connection refused: Server is not reachable.\n"
                    f"Check that:\n"
                    f"  - The server is running\n"
                    f"  - The port number is correct\n"
                    f"  - Firewall is not blocking the connection"
                )
            elif "timed out" in error_str.lower():
                return (
                    f"Connection timed out: Server did not respond.\n"
                    f"Check that:\n"
                    f"  - The server is running and responsive\n"
                    f"  - Network latency is acceptable"
                )
            else:
                return f"Connection failed: Unable to reach the server."

        # Authentication errors
        if isinstance(e, openai.AuthenticationError):
            return (
                f"Authentication failed: Invalid API key.\n"
                f"Check that your API key is correct in .env or ppxai-config.json"
            )

        # Rate limiting
        if isinstance(e, openai.RateLimitError):
            return f"Rate limit exceeded. Please wait before retrying."

        # Bad request (invalid parameters)
        if isinstance(e, openai.BadRequestError):
            # Extract just the error message, not the full JSON
            if "'message':" in error_str:
                match = re.search(r"'message':\s*'([^']+)'", error_str)
                if match:
                    return f"Invalid request: {match.group(1)}"
            return f"Invalid request: {error_str}"

        # API errors (server-side issues)
        if isinstance(e, openai.APIStatusError):
            # v1.18.3: provider-side throttle / quota — recognize NIM-style
            # "operation not allowed" 403 + generic 429 with cleaner messages
            # so users learn this is a provider quota block, not a model bug.
            if e.status_code == 403:
                if "operation not allowed" in error_str.lower():
                    return (
                        f"Provider quota / permission error (403): "
                        f"endpoint refused the call. On NVIDIA NIM free tier "
                        f"this typically means the per-model rate limit was "
                        f"exhausted — wait, switch model, or use paid tier."
                    )
                return f"Provider permission error (403): {error_str}"
            if e.status_code == 429:
                return (
                    f"Provider rate limit (429): {error_str}. "
                    f"Wait before retrying or switch to another model."
                )
            return f"API error ({e.status_code}): {error_str}"

        # httpx-level connection errors
        if isinstance(e, httpx.ConnectError):
            return f"Connection failed: Unable to connect to the server."

        # Fallback: return the exception type and message without full traceback
        return f"{error_type}: {error_str}"

    def _classify_throttle(self, e: Exception) -> Optional[Dict[str, Any]]:
        """Detect provider-side rate-limit / quota errors and return a
        structured payload for ``EventType.PROVIDER_THROTTLED``.

        Returns a dict with keys ``status_code``, ``provider``, ``message``,
        ``retry_after`` when the exception is a 429 ``RateLimitError`` or
        a 403 ``APIStatusError``; otherwise ``None`` so the caller falls
        back to ``EventType.ERROR``.

        v1.18.3: introduced alongside NVIDIA NIM provider work — free-tier
        NIM returns HTTP 403 ``{"message":"Operation not allowed"}`` when
        per-model quota exhausts, indistinguishable from a model failure
        until you know to look at the status code.
        """
        if not isinstance(e, openai.APIStatusError):
            return None
        status = getattr(e, "status_code", None)
        if status not in (403, 429):
            return None
        retry_after: Optional[float] = None
        try:
            response = getattr(e, "response", None)
            if response is not None:
                header = response.headers.get("retry-after")
                if header:
                    retry_after = float(header)
        except (AttributeError, TypeError, ValueError):
            retry_after = None
        return {
            "status_code": int(status),
            "provider": self.provider_id or "",
            "message": self._format_error(e),
            "retry_after": retry_after,
        }

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
