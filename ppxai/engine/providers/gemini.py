"""
Native Google Gemini provider using google-genai SDK.

Provides access to Gemini-specific features:
- Google Search Grounding (citations from web search)
- Prompt-based tool calling (v1.13.3+)
- Usage tracking with detailed token counts
- Streaming support

Requires: pip install ppxai[gemini]
"""

from typing import List, AsyncIterator, Optional, Dict, Any
from ..types import Message, Event, EventType, ProviderCapabilities, ModelInfo, UsageStats


# Try to import google-genai package (optional dependency, v1.12.5+)
_genai_available = False
try:
    from google import genai
    from google.genai import types as genai_types
    _genai_available = True
except ImportError:
    genai = None
    genai_types = None


def is_available() -> bool:
    """Check if google-genai package is installed."""
    return _genai_available


class GeminiProvider:
    """Native provider for Google Gemini API.

    Uses the google-genai SDK directly for Gemini-specific features:
    - Google Search Grounding for real-time web information
    - Citations from grounding chunks
    - Detailed usage metadata

    v1.13.3: When ppxai tools are enabled (tools parameter provided),
    grounding is disabled to allow prompt-based tool calling to work.
    """

    name = "gemini"
    default_capabilities = ProviderCapabilities(
        web_search=True,   # Via Google Search Grounding
        web_fetch=True,    # Can answer about URLs via grounding
        weather=True,      # Can answer weather via grounding
        citations=True,    # Grounding provides citations
        streaming=True
    )

    def __init__(
        self,
        api_key: str,
        models: Optional[Dict[str, Dict[str, str]]] = None,
        capabilities: Optional[ProviderCapabilities] = None,
        enable_grounding: bool = True,
        **kwargs
    ):
        """Initialize the Gemini provider.

        Args:
            api_key: Google AI API key
            models: Dictionary of available models
            capabilities: Provider capabilities
            enable_grounding: Whether to enable Google Search Grounding (default: True)
            **kwargs: Additional options (ignored for compatibility)
        """
        if not _genai_available:
            raise ImportError(
                "google-genai package not installed. "
                "Install with: pip install ppxai[gemini]"
            )

        self.api_key = api_key
        self.models = models or {}
        self.capabilities = capabilities or self.default_capabilities
        self.enable_grounding = enable_grounding

        # Initialize the Gemini client
        self.client = genai.Client(api_key=api_key)

    async def chat(
        self,
        messages: List[Message],
        model: str,
        stream: bool = True,
        tools: Optional[List] = None,
        **kwargs
    ) -> AsyncIterator[Event]:
        """Send chat request to Gemini API with streaming.

        Args:
            messages: Conversation history
            model: Model ID to use (e.g., 'gemini-2.0-flash')
            stream: Whether to stream the response (default: True)
            tools: Tool definitions - when provided, grounding is disabled
                   so model follows prompt-based tool instructions
            **kwargs: Additional arguments (ignored for compatibility)

        Yields:
            Event objects including grounding citations when available

        Note:
            v1.13.3: System messages are now passed via system_instruction config.
            Both grounding AND system_instruction work together - grounding for
            native web search, system_instruction for tool definitions.
        """
        try:
            # Convert messages to Gemini format (now returns tuple with system instruction)
            contents, system_instruction = self._convert_messages(messages)

            # v1.13.3: Enable both grounding AND system_instruction
            # Grounding provides native web search, system_instruction provides tool prompt
            # Both should work together - grounding for web search, tools for other capabilities
            config = self._build_config(
                use_grounding=self.enable_grounding,
                system_instruction=system_instruction
            )

            yield Event(EventType.STREAM_START, {"model": model})

            if stream:
                # Streaming response
                full_response = []
                usage = None
                citations = []

                response_stream = self.client.models.generate_content_stream(
                    model=model,
                    contents=contents,
                    config=config
                )

                if response_stream is None:
                    yield Event(EventType.ERROR, "Gemini API returned no response stream")
                    return

                for chunk in response_stream:
                    # Extract text from chunk
                    if chunk.candidates and chunk.candidates[0].content:
                        content = chunk.candidates[0].content
                        if content.parts:
                            for part in content.parts:
                                if hasattr(part, 'text') and part.text:
                                    text = part.text
                                    full_response.append(text)
                                    yield Event(EventType.STREAM_CHUNK, text)

                    # Check for usage in final chunk
                    if chunk.usage_metadata:
                        usage = self._parse_usage(chunk.usage_metadata)

                    # Check for grounding metadata (citations)
                    if chunk.candidates and chunk.candidates[0].grounding_metadata:
                        citations = self._parse_grounding(chunk.candidates[0].grounding_metadata)

                final_content = "".join(full_response)

                # Inject citation URLs if we have grounding
                if citations:
                    final_content = self._inject_citations(final_content, citations)

                metadata = {}
                if usage:
                    metadata["usage"] = usage
                if citations:
                    metadata["citations"] = [c["url"] for c in citations]
                yield Event(EventType.STREAM_END, final_content, metadata if metadata else None)

            else:
                # Non-streaming response
                response = self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config
                )

                content = ""
                if response.candidates and response.candidates[0].content:
                    for part in response.candidates[0].content.parts:
                        if hasattr(part, 'text') and part.text:
                            content += part.text

                usage = self._parse_usage(response.usage_metadata)

                # Extract grounding citations
                citations = []
                if response.candidates and response.candidates[0].grounding_metadata:
                    citations = self._parse_grounding(response.candidates[0].grounding_metadata)

                # Inject citation URLs
                if citations:
                    content = self._inject_citations(content, citations)

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
        contents, system_instruction = self._convert_messages(messages)
        config = self._build_config(
            use_grounding=self.enable_grounding,
            system_instruction=system_instruction
        )

        response = self.client.models.generate_content(
            model=model,
            contents=contents,
            config=config
        )

        content = ""
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    content += part.text

        return content

    def list_models(self) -> List[ModelInfo]:
        """Return available models for this provider.

        Returns:
            List of ModelInfo objects
        """
        return [
            ModelInfo(
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
        return bool(self.api_key)

    def needs_tool(self, tool_category: str) -> bool:
        """Check if provider needs a tool (doesn't have native capability).

        Args:
            tool_category: Category like 'web_search', 'weather', etc.

        Returns:
            True if provider needs this tool (doesn't have native capability)
        """
        return not getattr(self.capabilities, tool_category, False)

    def _convert_messages(self, messages: List[Message]) -> tuple:
        """Convert Message objects to Gemini format.

        Gemini uses a different format than OpenAI:
        - 'user' and 'model' roles (not 'assistant')
        - 'parts' array instead of 'content' string
        - System messages become system_instruction in config

        Args:
            messages: List of Message objects

        Returns:
            Tuple of (contents list, system_instruction string or None)
        """
        contents = []
        system_parts = []

        if not messages:
            return contents, None

        for m in messages:
            if m.role == "system":
                # Collect system messages for system_instruction
                system_parts.append(m.content)
            else:
                role = "model" if m.role == "assistant" else "user"
                contents.append({
                    "role": role,
                    "parts": [{"text": m.content}]
                })

        # Combine all system messages into one instruction
        system_instruction = "\n\n".join(system_parts) if system_parts else None
        return contents, system_instruction

    def _build_config(
        self,
        use_grounding: bool = True,
        system_instruction: Optional[str] = None
    ) -> "genai_types.GenerateContentConfig":
        """Build generation config with optional grounding and system instruction.

        Args:
            use_grounding: Whether to enable Google Search Grounding
            system_instruction: System prompt/instruction for the model

        Returns:
            GenerateContentConfig with tools and/or system_instruction
        """
        config_kwargs = {}

        # Add system instruction if provided (v1.13.3: enables tool prompts)
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        # Add Google Search Grounding if enabled
        if use_grounding:
            config_kwargs["tools"] = [genai_types.Tool(google_search=genai_types.GoogleSearch())]

        # Return config if we have any settings, else None
        if config_kwargs:
            return genai_types.GenerateContentConfig(**config_kwargs)
        return None

    def _parse_usage(self, usage_metadata) -> Optional[UsageStats]:
        """Parse usage from Gemini response.

        Args:
            usage_metadata: Usage metadata from response

        Returns:
            UsageStats object or None
        """
        if not usage_metadata:
            return None

        prompt_tokens = getattr(usage_metadata, 'prompt_token_count', 0) or 0
        completion_tokens = getattr(usage_metadata, 'candidates_token_count', 0) or 0
        total_tokens = getattr(usage_metadata, 'total_token_count', 0) or 0

        # If total not provided, calculate it
        if not total_tokens:
            total_tokens = prompt_tokens + completion_tokens

        return UsageStats(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    def _parse_grounding(self, grounding_metadata) -> List[Dict[str, str]]:
        """Parse grounding metadata to extract citations.

        Args:
            grounding_metadata: Grounding metadata from response

        Returns:
            List of citation dicts with 'title', 'url', 'domain'
        """
        citations = []
        if not grounding_metadata:
            return citations

        grounding_chunks = getattr(grounding_metadata, 'grounding_chunks', None)
        if not grounding_chunks:
            return citations

        for chunk in grounding_chunks:
            web = getattr(chunk, 'web', None)
            if web:
                citations.append({
                    "title": getattr(web, 'title', '') or '',
                    "url": getattr(web, 'uri', '') or '',
                    "domain": getattr(web, 'domain', '') or ''
                })

        return citations

    def _inject_citations(self, content: str, citations: List[Dict[str, str]]) -> str:
        """Inject citation URLs into response text.

        Unlike Perplexity which uses [1], [2] markers, Gemini doesn't
        automatically number citations. We append them at the end.

        Args:
            content: Response text
            citations: List of citation dicts

        Returns:
            Content with citations appended
        """
        if not citations:
            return content

        # Append citations at the end as a reference section
        citation_lines = []
        for i, citation in enumerate(citations[:5], 1):  # Limit to 5 citations
            title = citation.get("title", "Source")
            url = citation.get("url", "")
            if url:
                citation_lines.append(f"[{i}]({url}) - {title}")

        if citation_lines:
            content += "\n\n**Sources:**\n" + "\n".join(citation_lines)

        return content
