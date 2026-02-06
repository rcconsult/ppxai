"""
Native Google Gemini provider using google-genai SDK.

Provides access to Gemini-specific features:
- Google Search Grounding (citations from web search)
- Native function calling (v1.15.2+) with automatic tool execution
- Prompt-based tool calling fallback (v1.13.3+)
- Usage tracking with detailed token counts
- Streaming support

IMPORTANT: Multi-tool use (combining GoogleSearch grounding with function_declarations)
is only supported in Gemini's Live API. The standard generate_content API returns
400 INVALID_ARGUMENT if both are used together. When ppxai tools are enabled,
native function calling takes priority and grounding is disabled. To use
grounding for web search, disable tools with `/tools off`.
See: https://ai.google.dev/gemini-api/docs/live-tools

Requires: pip install ppxai[gemini]
"""

import json
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
    - Native function calling (v1.15.2+) for structured tool use
    - Citations from grounding chunks
    - Detailed usage metadata

    v1.15.2: Native tool calling enabled by default. Note that Gemini API
    does NOT allow combining grounding with function calling - when ppxai
    tools are enabled, function calling takes priority and grounding is
    disabled for that request.
    """

    name = "gemini"
    default_capabilities = ProviderCapabilities(
        web_search=True,   # Via Google Search Grounding
        web_fetch=True,    # Can answer about URLs via grounding
        weather=True,      # Can answer weather via grounding
        citations=True,    # Grounding provides citations
        streaming=True,
        native_tool_calling=True  # v1.15.2: Enable native function calling
    )

    def __init__(
        self,
        api_key: str,
        models: Optional[Dict[str, Dict[str, str]]] = None,
        capabilities: Optional[ProviderCapabilities] = None,
        enable_grounding: bool = True,
        enable_thinking: bool = True,
        thinking_budget: Optional[int] = None,
        provider_id: Optional[str] = None,
        **kwargs
    ):
        """Initialize the Gemini provider.

        Args:
            api_key: Google AI API key
            models: Dictionary of available models
            capabilities: Provider capabilities
            enable_grounding: Whether to enable Google Search Grounding (default: True)
            enable_thinking: Whether to include thinking summaries (default: True)
            thinking_budget: Token budget for thinking (None = dynamic, 0 = disabled)
            provider_id: Provider identifier (for config lookup consistency)
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
        self.enable_thinking = enable_thinking
        self.thinking_budget = thinking_budget
        self.provider_id = provider_id or "gemini"  # For config lookup

        # Initialize the Gemini client
        self.client = genai.Client(api_key=api_key)

    def _get_generation_params(self, model: str) -> Dict[str, Any]:
        """Get generation parameters (temperature, top_p, etc.) from config.

        v1.15.2: Allows setting temperature and other params to reduce hallucinations.
        Lower temperature (0.0-0.5) produces more deterministic, factual responses.

        Args:
            model: Model ID to check

        Returns:
            Dict of generation params to pass to API (empty if none configured)
        """
        try:
            from ...config import get_generation_params
            return get_generation_params(self.provider_id, model)
        except (ImportError, AttributeError):
            return {}  # No params configured

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
            tools: Tool definitions in OpenAI format - converted to Gemini
                   function_declarations for native tool calling (v1.15.2)
            **kwargs: Additional arguments (ignored for compatibility)

        Yields:
            Event objects including TOOL_CALL events for function calls

        Note:
            v1.15.2: Native function calling enabled. Tools are passed as
            Gemini function_declarations alongside grounding for web search.
            Both capabilities work together.
        """
        try:
            # Convert messages to Gemini format (now returns tuple with system instruction)
            contents, system_instruction = self._convert_messages(messages)

            # Load generation params from config (v1.15.2)
            generation_params = self._get_generation_params(model)

            # v1.15.2: Pass tools to config for native function calling
            # Both grounding AND function calling can work together
            config = self._build_config(
                use_grounding=self.enable_grounding,
                system_instruction=system_instruction,
                generation_params=generation_params,
                tools=tools  # OpenAI format tools, converted internally
            )

            yield Event(EventType.STREAM_START, {"model": model})

            if stream:
                # Streaming response
                full_response = []
                reasoning_response = []
                tool_calls = []
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
                    # Extract text and function calls from chunk
                    if chunk.candidates and chunk.candidates[0].content:
                        content = chunk.candidates[0].content
                        if content.parts:
                            for part in content.parts:
                                # Handle text parts
                                if hasattr(part, 'text') and part.text:
                                    text = part.text
                                    # Check if this is a thinking/reasoning part
                                    is_thought = getattr(part, 'thought', False)
                                    if is_thought:
                                        reasoning_response.append(text)
                                        yield Event(EventType.REASONING_CHUNK, text)
                                    else:
                                        full_response.append(text)
                                        yield Event(EventType.STREAM_CHUNK, text)

                                # Handle function call parts (v1.15.2)
                                if hasattr(part, 'function_call') and part.function_call:
                                    fc = part.function_call
                                    tool_call = self._parse_function_call(fc)
                                    if tool_call:
                                        tool_calls.append(tool_call)

                    # Check for usage in final chunk
                    if chunk.usage_metadata:
                        usage = self._parse_usage(chunk.usage_metadata)

                    # Check for grounding metadata (citations)
                    if chunk.candidates and chunk.candidates[0].grounding_metadata:
                        citations = self._parse_grounding(chunk.candidates[0].grounding_metadata)

                # Emit TOOL_CALL events for any function calls (v1.15.2)
                for tc in tool_calls:
                    yield Event(EventType.TOOL_CALL, {
                        "tool": tc["name"],
                        "arguments": tc["arguments"],
                        "native": True,  # Mark as native tool call
                    })

                final_content = "".join(full_response)
                final_reasoning = "".join(reasoning_response)

                # Inject citation URLs if we have grounding
                if citations:
                    final_content = self._inject_citations(final_content, citations)

                metadata = {}
                if usage:
                    metadata["usage"] = usage
                if citations:
                    metadata["citations"] = [c["url"] for c in citations]
                if final_reasoning:
                    metadata["reasoning"] = final_reasoning
                if tool_calls:
                    metadata["tool_calls"] = tool_calls
                yield Event(EventType.STREAM_END, final_content, metadata if metadata else None)

            else:
                # Non-streaming response
                response = self.client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config
                )

                content = ""
                reasoning = ""
                tool_calls = []
                if response.candidates and response.candidates[0].content:
                    for part in response.candidates[0].content.parts:
                        # Handle text parts
                        if hasattr(part, 'text') and part.text:
                            # Check if this is a thinking/reasoning part
                            is_thought = getattr(part, 'thought', False)
                            if is_thought:
                                reasoning += part.text
                            else:
                                content += part.text

                        # Handle function call parts (v1.15.2)
                        if hasattr(part, 'function_call') and part.function_call:
                            fc = part.function_call
                            tool_call = self._parse_function_call(fc)
                            if tool_call:
                                tool_calls.append(tool_call)

                usage = self._parse_usage(response.usage_metadata)

                # Extract grounding citations
                citations = []
                if response.candidates and response.candidates[0].grounding_metadata:
                    citations = self._parse_grounding(response.candidates[0].grounding_metadata)

                # Emit TOOL_CALL events for any function calls (v1.15.2)
                for tc in tool_calls:
                    yield Event(EventType.TOOL_CALL, {
                        "tool": tc["name"],
                        "arguments": tc["arguments"],
                        "native": True,
                    })

                # Inject citation URLs
                if citations:
                    content = self._inject_citations(content, citations)

                metadata = {"usage": usage}
                if citations:
                    metadata["citations"] = citations
                if reasoning:
                    metadata["reasoning"] = reasoning
                if tool_calls:
                    metadata["tool_calls"] = tool_calls

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
        contents, system_instruction = self._convert_messages(messages)
        generation_params = self._get_generation_params(model)
        config = self._build_config(
            use_grounding=self.enable_grounding,
            system_instruction=system_instruction,
            generation_params=generation_params
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
        system_instruction: Optional[str] = None,
        generation_params: Optional[Dict[str, Any]] = None,
        tools: Optional[List] = None
    ) -> "genai_types.GenerateContentConfig":
        """Build generation config with optional grounding, thinking, system instruction, tools, and generation params.

        Args:
            use_grounding: Whether to enable Google Search Grounding
            system_instruction: System prompt/instruction for the model
            generation_params: Generation parameters (temperature, top_p, max_tokens, etc.)
            tools: Tool definitions in OpenAI format (converted to Gemini function_declarations)

        Returns:
            GenerateContentConfig with tools, thinking_config, generation params, and/or system_instruction
        """
        config_kwargs = {}

        # Add system instruction if provided (v1.13.3: enables tool prompts)
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        # Build tools list
        # IMPORTANT: Gemini API does NOT support combining GoogleSearch grounding
        # with function_declarations in the same request (400 INVALID_ARGUMENT).
        # When ppxai tools are provided, prioritize function calling over grounding.
        gemini_tools = []

        # Add function declarations from ppxai tools (v1.15.2)
        # This takes priority over grounding when tools are enabled
        if tools and self.capabilities.native_tool_calling:
            function_declarations = self._convert_tools_to_gemini(tools)
            if function_declarations:
                gemini_tools.append(genai_types.Tool(function_declarations=function_declarations))

        # Add Google Search Grounding ONLY if no function declarations
        # (they cannot coexist in the same request)
        if use_grounding and not gemini_tools:
            gemini_tools.append(genai_types.Tool(google_search=genai_types.GoogleSearch()))

        if gemini_tools:
            config_kwargs["tools"] = gemini_tools

        # Add thinking configuration for Gemini 2.5+ models
        # include_thoughts=True returns thinking summaries in response parts
        if self.enable_thinking:
            thinking_config = {"include_thoughts": True}
            if self.thinking_budget is not None:
                thinking_config["thinking_budget"] = self.thinking_budget
            config_kwargs["thinking_config"] = thinking_config

        # Add generation parameters from config (v1.15.2)
        # Gemini SDK uses same parameter names as OpenAI: temperature, top_p, max_output_tokens
        if generation_params:
            # Map OpenAI param names to Gemini param names
            if "temperature" in generation_params:
                config_kwargs["temperature"] = generation_params["temperature"]
            if "top_p" in generation_params:
                config_kwargs["top_p"] = generation_params["top_p"]
            if "max_tokens" in generation_params:
                # Gemini uses max_output_tokens instead of max_tokens
                config_kwargs["max_output_tokens"] = generation_params["max_tokens"]
            if "stop" in generation_params:
                config_kwargs["stop_sequences"] = generation_params["stop"]

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

    def _convert_tools_to_gemini(self, openai_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert OpenAI-format tools to Gemini function_declarations format.

        OpenAI format:
            {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}

        Gemini format:
            {"name": "...", "description": "...", "parameters": {...}}

        Args:
            openai_tools: List of tools in OpenAI format

        Returns:
            List of function declarations in Gemini format
        """
        declarations = []
        for tool in openai_tools:
            if tool.get("type") == "function" and "function" in tool:
                func = tool["function"]
                declaration = {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                }
                # Parameters are in JSON Schema format, same for both APIs
                if "parameters" in func:
                    declaration["parameters"] = func["parameters"]
                declarations.append(declaration)
        return declarations

    def _parse_function_call(self, function_call) -> Optional[Dict[str, Any]]:
        """Parse a Gemini function_call part into tool call dict.

        Args:
            function_call: Gemini FunctionCall object with name and args

        Returns:
            Dict with 'name' and 'arguments', or None if invalid
        """
        if not function_call:
            return None

        name = getattr(function_call, 'name', None)
        if not name:
            return None

        # Args can be a dict or a Struct-like object
        args = getattr(function_call, 'args', {})
        if args is None:
            args = {}
        elif hasattr(args, 'items'):
            # Already dict-like
            args = dict(args)
        elif isinstance(args, str):
            # Try to parse as JSON
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}

        return {"name": name, "arguments": args}

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

    def _format_error(self, e: Exception) -> str:
        """Format exception into user-friendly error message.

        Args:
            e: The exception to format

        Returns:
            User-friendly error message
        """
        error_type = type(e).__name__
        error_str = str(e)

        # API key errors
        if "API_KEY" in error_str.upper() or "INVALID_API_KEY" in error_str.upper():
            return "Gemini API key error. Check your GEMINI_API_KEY in ~/.ppxai/.env"

        # Quota/rate limit errors
        if "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
            return "Gemini quota exceeded. Please wait before trying again."

        # Safety filter errors
        if "SAFETY" in error_str.upper() or "blocked" in error_str.lower():
            return "Response blocked by Gemini safety filters."

        # Model not found
        if "NOT_FOUND" in error_str or "model" in error_str.lower() and "not found" in error_str.lower():
            return f"Gemini model not found. Check model ID is valid."

        # Connection errors
        if "connect" in error_str.lower() or "timeout" in error_str.lower():
            return f"Connection to Gemini API failed: {error_str}"

        # Generic error with type
        return f"Gemini error ({error_type}): {error_str}"

    def _log_error_traceback(self, e: Exception) -> None:
        """Log full error traceback for debugging.

        Args:
            e: The exception to log
        """
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Gemini error traceback:\n{traceback.format_exc()}")
