"""
Perplexity AI provider.

Perplexity has native web search and citation capabilities.
"""

import re
from typing import List, AsyncIterator, Optional
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
                # Streaming response with usage tracking
                response_stream = self.client.chat.completions.create(
                    model=model,
                    messages=api_messages,
                    stream=True,
                    stream_options={"include_usage": True}
                )

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

                # Inject citation URLs into response text for clickable links
                if citations:
                    content = inject_citation_urls(content, citations)

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
