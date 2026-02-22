"""
Perplexity AI provider.

Perplexity has native web search and citation capabilities.
"""

import re
from typing import List, AsyncIterator, Optional, Dict, Any
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
        streaming=True,
        native_tool_calling=False  # Sonar models don't support native API tool_calls
    )

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
            tools: Converted to prompt-based tool calling. Perplexity Sonar models
                   do not support native function calling via the API (tool_calls response).
                   Instead, tool definitions are injected into the system prompt and
                   responses are parsed for JSON tool call format.

                   Note: Perplexity's Agentic Research API supports native tools for
                   third-party models (openai/gpt-*, etc.) but NOT for Sonar models.

                   See: https://docs.perplexity.ai/docs/agentic-research/tools

        Yields:
            Event objects including citations when available
        """
        # Note: tools parameter is ignored - Perplexity has native search
        try:
            api_messages = self._convert_messages(messages)

            # Load generation params from config (v1.15.2)
            generation_params = self._get_generation_params(model)

            yield Event(EventType.STREAM_START, {"model": model})

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
                response = self.client.chat.completions.create(**request_kwargs)

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

        request_kwargs = {
            "model": model,
            "messages": api_messages,
            "stream": False
        }
        if generation_params:
            request_kwargs.update(generation_params)

        response = self.client.chat.completions.create(**request_kwargs)

        return response.choices[0].message.content or ""
