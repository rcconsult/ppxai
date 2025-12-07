"""
OpenAI-compatible provider.

This provider works with any API that follows the OpenAI API format,
including OpenAI, OpenRouter, Gemini (via compatibility layer), local models, etc.
"""

from typing import List, AsyncIterator, Optional, Dict
from ..types import Message, Event, EventType, ProviderCapabilities
from .base import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    """Provider for OpenAI-compatible APIs.

    Works with:
    - OpenAI (ChatGPT)
    - OpenRouter
    - Google Gemini (via OpenAI compatibility)
    - Local models (Ollama, vLLM, LM Studio)
    - Any other OpenAI-compatible endpoint
    """

    name = "openai_compatible"
    default_capabilities = ProviderCapabilities(
        web_search=False,
        web_fetch=False,
        weather=False,
        citations=False,
        streaming=True
    )

    async def chat(
        self,
        messages: List[Message],
        model: str,
        stream: bool = False
    ) -> AsyncIterator[Event]:
        """Send chat request to OpenAI-compatible API.

        Args:
            messages: Conversation history
            model: Model ID to use
            stream: Whether to stream the response

        Yields:
            Event objects
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

                yield Event(EventType.STREAM_END, content, {"usage": usage})

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
