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

from ..model_profiles import ModelProfile, get_profile
from ..types import Message, Event, EventType, ProviderCapabilities, ModelInfo, UsageStats
from ..uploaded_file import flatten_uploaded_file_blocks
from ...config import get_generation_params, get_model_max_tokens, get_extra_body
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

        # Check SSL configuration
        # SSL_VERIFY=false disables SSL verification entirely
        # SSL_CERT_FILE=/path/to/cert.pem uses a custom certificate (e.g., corporate proxy)
        ssl_verify_env = os.getenv("SSL_VERIFY", "true").lower()
        ssl_cert_file = os.getenv("SSL_CERT_FILE", "")

        if ssl_verify_env == "false":
            # Disable SSL verification entirely
            http_client = httpx.Client(verify=False)
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client
            )
        elif ssl_cert_file:
            # Use custom SSL certificate (e.g., corporate proxy cert)
            http_client = httpx.Client(verify=ssl_cert_file)
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client
            )
        else:
            # Default: use system SSL certificates
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url
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

    def get_capabilities_for_model(self, model: str) -> ProviderCapabilities:
        """Get model-aware capabilities.

        Returns the provider's capabilities, potentially adjusted for specific
        models. The default returns self.capabilities unchanged. Providers like
        OpenAINativeProvider override this to disable native_tool_calling for
        models that perform better with prompt-based routing.

        Args:
            model: Model ID (e.g., "gpt-5.2", "o4-mini")

        Returns:
            ProviderCapabilities for the model
        """
        return self.capabilities

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

    def _convert_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """Convert Message objects to API format.

        R5 (v1.17.6): any `uploaded_file` content blocks are flattened
        back to their legacy `<uploaded_file>` text-marker form before
        shaping the API request. Providers (OpenAI, Perplexity, and any
        OpenAI-compatible endpoint) would reject an unknown block type
        outright, so the structured type is an engine-internal schema
        only. The flatten uses `format_uploaded_file_reference` under
        the hood, so the LLM sees byte-identical strings whether the
        producer emitted a legacy text marker (pre-R5) or a structured
        block flattened here.

        Args:
            messages: List of Message objects

        Returns:
            List of dicts with 'role', 'content', and optional tool fields
        """
        result = []
        for m in messages:
            content = flatten_uploaded_file_blocks(m.content)
            msg: Dict[str, Any] = {"role": m.role, "content": content}
            if m.tool_calls:
                msg["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                msg["tool_call_id"] = m.tool_call_id
            result.append(msg)
        return result

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
