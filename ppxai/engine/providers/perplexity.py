"""
Perplexity AI provider.

Perplexity has native web search and citation capabilities.
"""

from typing import List, AsyncIterator, Optional
from ..types import Message, Event, EventType, ProviderCapabilities
from .base import BaseProvider


class PerplexityProvider(BaseProvider):
    """Provider for Perplexity AI API.

    Perplexity has built-in:
    - Web search (always on for sonar models)
    - Citations
    - Real-time information
    """

    name = "perplexity"
    default_capabilities = ProviderCapabilities(
        web_search=True,
        web_fetch=True,
        weather=True,  # Can answer weather via search
        citations=True,
        streaming=True
    )

    async def chat(
        self,
        messages: List[Message],
        model: str,
        stream: bool = False
    ) -> AsyncIterator[Event]:
        """Send chat request to Perplexity API.

        Args:
            messages: Conversation history
            model: Model ID to use
            stream: Whether to stream the response

        Yields:
            Event objects including citations when available
        """
        try:
            api_messages = self._convert_messages(messages)

            yield Event(EventType.STREAM_START, {"model": model})

            if stream:
                # Streaming response
                response_stream = self.client.chat.completions.create(
                    model=model,
                    messages=api_messages,
                    stream=True
                )

                full_response = []
                for chunk in response_stream:
                    if chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_response.append(content)
                        yield Event(EventType.STREAM_CHUNK, content)

                final_content = "".join(full_response)
                yield Event(EventType.STREAM_END, final_content)

            else:
                # Non-streaming response
                response = self.client.chat.completions.create(
                    model=model,
                    messages=api_messages,
                    stream=False
                )

                content = response.choices[0].message.content or ""
                usage = self._parse_usage(response.usage)

                # Extract citations if available (Perplexity-specific)
                citations = []
                if hasattr(response, 'citations'):
                    citations = response.citations or []

                metadata = {"usage": usage}
                if citations:
                    metadata["citations"] = citations

                yield Event(EventType.STREAM_END, content, metadata)

        except Exception as e:
            yield Event(EventType.ERROR, str(e))

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

        response = self.client.chat.completions.create(
            model=model,
            messages=api_messages,
            stream=False
        )

        return response.choices[0].message.content or ""
