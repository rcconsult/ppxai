"""
Base provider abstract class.

All AI providers must implement this interface.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, AsyncIterator, Optional
import os
import httpx
from openai import OpenAI

from ..types import Message, Event, EventType, ProviderCapabilities, ModelInfo, UsageStats


class BaseProvider(ABC):
    """Abstract base class for all AI providers.

    Providers handle communication with AI APIs and emit events that clients consume.
    """

    # Class attributes to be overridden
    name: str = "base"
    default_capabilities: ProviderCapabilities = ProviderCapabilities()

    def __init__(
        self,
        api_key: str,
        base_url: str,
        models: Optional[Dict[str, Dict[str, str]]] = None,
        capabilities: Optional[ProviderCapabilities] = None,
        **kwargs
    ):
        """Initialize the provider.

        Args:
            api_key: API key for authentication
            base_url: Base URL for the API
            models: Dictionary of available models
            capabilities: Provider capabilities (native features)
            **kwargs: Additional provider-specific options
        """
        self.api_key = api_key
        self.base_url = base_url
        self.models = models or {}
        self.capabilities = capabilities or self.default_capabilities

        # Check if SSL verification should be disabled
        ssl_verify = os.getenv("SSL_VERIFY", "true").lower() != "false"

        if not ssl_verify:
            http_client = httpx.Client(verify=False)
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client
            )
        else:
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url
            )

    @abstractmethod
    async def chat(
        self,
        messages: List[Message],
        model: str,
        stream: bool = False
    ) -> AsyncIterator[Event]:
        """Send a chat request and yield events.

        Args:
            messages: Conversation history
            model: Model ID to use
            stream: Whether to stream the response

        Yields:
            Event objects (STREAM_START, STREAM_CHUNK, STREAM_END, ERROR)
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
        import asyncio
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

        Returns:
            True if configuration is valid
        """
        return bool(self.api_key and self.base_url)

    def needs_tool(self, tool_category: str) -> bool:
        """Check if provider needs a tool (doesn't have native capability).

        Args:
            tool_category: Category like 'web_search', 'weather', etc.

        Returns:
            True if provider needs this tool (doesn't have native capability)
        """
        return not getattr(self.capabilities, tool_category, False)

    def _convert_messages(self, messages: List[Message]) -> List[Dict[str, str]]:
        """Convert Message objects to API format.

        Args:
            messages: List of Message objects

        Returns:
            List of dicts with 'role' and 'content' keys
        """
        return [{"role": m.role, "content": m.content} for m in messages]

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
