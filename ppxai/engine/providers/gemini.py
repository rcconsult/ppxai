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

import asyncio
import json
import logging
import os
import traceback
from typing import List, AsyncIterator, Optional, Dict, Any

import httpx

from ...common.logger import get_logger
from ..types import Message, Event, EventType, ProviderCapabilities, UsageStats
from ..uploaded_file import flatten_uploaded_file_blocks
from .base import BaseProvider


# Try to import google-genai package (optional dependency, v1.12.5+)
_genai_available = False
try:
    from google import genai
    from google.genai import types as genai_types
    from google.genai import errors as genai_errors
    _genai_available = True
except ImportError:
    genai = None
    genai_types = None
    genai_errors = None

# Initialize logger
logger = get_logger("gemini")


def is_available() -> bool:
    """Check if google-genai package is installed."""
    return _genai_available


class GeminiProvider(BaseProvider):
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

    Inherits from BaseProvider (v1.16.0) for shared interface: needs_tool(),
    get_model_profile(), list_models(), validate_config(), get_capabilities_for_model(),
    _get_generation_params(), _get_max_tokens().
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
        thinking_level: Optional[str] = None,
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
            thinking_level: Reasoning depth — "minimal", "low", "medium", "high"
                (None = model default, which is "high" for Gemini 3.x)
            provider_id: Provider identifier (for config lookup consistency)
            **kwargs: Additional options (ignored for compatibility)
        """
        if not _genai_available:
            raise ImportError(
                "google-genai package not installed. "
                "Install with: pip install ppxai[gemini]"
            )

        self.enable_grounding = enable_grounding
        self.enable_thinking = enable_thinking
        self.thinking_level = thinking_level

        # Remove base_url from kwargs if passed for compat (we don't use it)
        kwargs.pop("base_url", None)

        # base_url=None skips OpenAI client creation in BaseProvider
        super().__init__(
            api_key=api_key,
            base_url=None,
            models=models,
            capabilities=capabilities,
            provider_id=provider_id or "gemini",
            **kwargs,
        )

        # Initialize the Gemini client with SSL configuration
        # Respects SSL_VERIFY and SSL_CERT_FILE env vars (consistent with BaseProvider)
        ssl_verify_env = os.getenv("SSL_VERIFY", "true").lower()
        ssl_cert_file = os.getenv("SSL_CERT_FILE", "")

        http_options = None
        if ssl_verify_env == "false" or ssl_cert_file:
            verify = False if ssl_verify_env == "false" else ssl_cert_file
            http_options = genai_types.HttpOptions(
                httpx_client=httpx.Client(verify=verify)
            )

        self.client = genai.Client(
            api_key=api_key,
            http_options=http_options
        )

    def _filter_empty_parts(self, parts: List[Any], context: str = "") -> List[Any]:
        """Filter out empty parts to work around SDK v1.57.0+ regression.

        SDK is pinned to <1.57.0 in pyproject.toml. This workaround is kept as
        a defensive layer in case the pin is ever relaxed. See docs/known-issues.md
        for full context, affected versions, and upgrade verification steps.

        Issue: https://github.com/googleapis/python-genai/issues/1789
        SDK versions 1.57.0+ removed validation on empty text parts, causing
        incomplete responses (e.g., patches missing imports) to pass through.

        Args:
            parts: List of response parts from Gemini API
            context: Context string for logging (e.g., "streaming", "non-streaming")

        Returns:
            Filtered list with only non-empty parts
        """
        if not parts:
            return parts

        # Enhanced debug logging
        logger.debug(f"[{context}] Processing {len(parts)} parts")

        filtered_parts = []
        empty_count = 0

        for i, part in enumerate(parts):
            # Keep function call parts always
            if hasattr(part, 'function_call') and part.function_call:
                logger.debug(f"[{context}] Part {i}: function_call (kept)")
                filtered_parts.append(part)
                continue

            # Check text parts
            if hasattr(part, 'text'):
                text = part.text
                text_len = len(text) if text else 0
                has_strip = text.strip() if text else ""
                strip_len = len(has_strip)

                if text and has_strip:
                    # Keep non-empty text
                    logger.debug(
                        f"[{context}] Part {i}: text len={text_len}, "
                        f"stripped={strip_len}, preview='{text[:50]}...' (kept)"
                    )
                    filtered_parts.append(part)
                else:
                    # Filter empty/whitespace text
                    empty_count += 1
                    logger.warning(
                        f"[{context}] Part {i}: text len={text_len}, "
                        f"stripped={strip_len}, content='{text}' (FILTERED)"
                    )
            else:
                # Part has no text or function_call
                empty_count += 1
                logger.warning(
                    f"[{context}] Part {i}: unknown type, "
                    f"has_text={hasattr(part, 'text')}, "
                    f"has_function_call={hasattr(part, 'function_call')} (FILTERED)"
                )

        if empty_count > 0:
            logger.warning(
                f"Gemini SDK workaround: Filtered {empty_count}/{len(parts)} empty parts "
                f"from {context} response (Issue #1789)"
            )

        return filtered_parts

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
            model: Model ID to use (e.g., 'gemini-2.5-flash')
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
                # Non-streaming response. Off-load the blocking SDK call so a
                # non-streaming agent-tier run doesn't starve the event loop
                # (v1.19.x — see openai_compat.chat).
                response = await asyncio.to_thread(
                    lambda: self.client.models.generate_content(
                        model=model,
                        contents=contents,
                        config=config,
                    )
                )

                content = ""
                reasoning = ""
                tool_calls = []
                if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
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
            # v1.18.3 follow-up: typed throttle event + persistent telemetry.
            # Gemini overrides _classify_throttle to handle google.genai
            # errors (APIError with code 403/429) since the base class
            # only knows about openai.APIStatusError.
            throttle = self._classify_throttle(e)
            if throttle is not None:
                throttle["model"] = model
                try:
                    from ...usage import record_provider_error
                    record_provider_error(
                        provider=throttle["provider"] or self.provider_id or "",
                        status_code=throttle["status_code"],
                        model=model,
                    )
                except Exception:
                    pass
                yield Event(EventType.PROVIDER_THROTTLED, throttle)
            else:
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
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'text') and part.text:
                    content += part.text

        return content

    def oneshot(
        self,
        prompt: str,
        model: str,
        system: Optional[str] = None,
        response_format: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Stateless single-turn completion (BaseProvider contract).

        Same return shape as OpenAICompatibleProvider.oneshot
        ({content, finish_reason, model, usage}). Gemini uses
        generate_content (not the OpenAI SDK), so usage is parsed from
        `usage_metadata` via the existing `_parse_usage`. `system` maps to
        Gemini's system_instruction; response_format is not forwarded
        (Gemini structured output uses a different config knob — out of
        scope for this stateless path).
        """
        messages: List[Message] = []
        if system:
            messages.append(Message(role="system", content=system))
        messages.append(Message(role="user", content=prompt))

        contents, system_instruction = self._convert_messages(messages)
        generation_params = dict(self._get_generation_params(model) or {})
        if temperature is not None:
            generation_params["temperature"] = temperature
        if max_tokens is not None:
            # Gemini SDK uses max_output_tokens.
            generation_params["max_output_tokens"] = max_tokens
        config = self._build_config(
            use_grounding=self.enable_grounding,
            system_instruction=system_instruction,
            generation_params=generation_params,
        )

        response = self.client.models.generate_content(
            model=model, contents=contents, config=config
        )

        content = ""
        finish_reason = None
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    content += part.text
            finish_reason = getattr(response.candidates[0], "finish_reason", None)
            if finish_reason is not None:
                finish_reason = str(finish_reason)

        usage_dict = None
        usage_stats = self._parse_usage(getattr(response, "usage_metadata", None))
        if usage_stats is not None:
            usage_dict = {
                "prompt_tokens": usage_stats.prompt_tokens,
                "completion_tokens": usage_stats.completion_tokens,
                "total_tokens": usage_stats.total_tokens,
            }
        return {
            "content": content,
            "finish_reason": finish_reason,
            "model": model,
            "usage": usage_dict,
        }

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
                # Collect system messages for system_instruction. Gemini's
                # system_instruction is text-only, so flatten any multimodal
                # content to its text representation.
                system_parts.append(m.text_content())
            else:
                role = "model" if m.role == "assistant" else "user"
                contents.append({
                    "role": role,
                    "parts": self._content_to_gemini_parts(m.content),
                })

        # Combine all system messages into one instruction
        system_instruction = "\n\n".join(system_parts) if system_parts else None
        return contents, system_instruction

    @staticmethod
    def _content_to_gemini_parts(content: Any) -> List[Dict[str, Any]]:
        """Convert Message.content to Gemini `parts` list.

        String content → single text part. List content (OpenAI multimodal
        format) → mix of `{"text": ...}` and `{"inline_data": {mime_type, data}}`
        parts. Data URIs (`data:image/png;base64,...`) are split into mime_type
        and base64 payload. Remote `http(s)://` URLs are unsupported — Gemini
        requires the caller to fetch and embed the bytes.

        R5 (v1.17.6): `uploaded_file` blocks are flattened to legacy
        text markers before the shape conversion, so the block-type
        walk below only has to know about `text` and `image_url`.
        """
        if isinstance(content, str):
            return [{"text": content}]
        if not isinstance(content, list):
            return [{"text": str(content)}]

        # R5: collapse any uploaded_file blocks to their legacy text form
        # before we walk the list. Keeps the block-type dispatch simple
        # and guarantees Gemini sees the exact same marker string it did
        # pre-R5.
        content = flatten_uploaded_file_blocks(content)

        parts: List[Dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append({"text": block.get("text", "")})
            elif btype == "image_url":
                url = (block.get("image_url") or {}).get("url", "")
                if url.startswith("data:"):
                    # data:image/png;base64,AAAA...
                    try:
                        header, data = url.split(",", 1)
                        mime_type = header[5:].split(";", 1)[0] or "image/png"
                    except ValueError:
                        # Malformed data URI — skip rather than crash.
                        continue
                    parts.append({
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": data,
                        }
                    })
                # Non-data URIs are silently skipped; the preprocessing layer
                # is responsible for inlining remote images before they reach
                # the provider.
        # Gemini rejects empty parts — fall back to a blank text part so the
        # turn stays valid even if every block was filtered out.
        if not parts:
            parts.append({"text": ""})
        return parts

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
            if self.thinking_level is not None:
                thinking_config["thinking_level"] = self.thinking_level
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
        if not openai_tools:
            return declarations
        for tool in openai_tools:
            if not isinstance(tool, dict):
                continue
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

    def _classify_throttle(self, e: Exception) -> Optional[Dict[str, Any]]:
        """Detect Gemini-side rate-limit / quota errors.

        v1.18.3 follow-up: the base class checks ``openai.APIStatusError``
        which never matches google-genai exceptions. Gemini's
        ``google.genai.errors.APIError`` carries an integer ``code`` and
        a string ``status`` (e.g. ``RESOURCE_EXHAUSTED``); we map 403 /
        429 onto throttle and let everything else fall through to the
        generic ERROR path.

        Returns the same dict shape as the base implementation
        (``status_code``, ``provider``, ``message``, ``retry_after``)
        so the SSE consumer can be polymorphic across providers.

        Returns ``None`` when:
        * google-genai isn't installed (defensive — should never happen
          if a request is in flight, but the guard keeps the helper
          callable in test contexts that build the provider without
          the dep).
        * Exception isn't an ``APIError`` or its ``code`` isn't a
          throttle status.
        """
        if genai_errors is None:
            return None
        if not isinstance(e, genai_errors.APIError):
            return None
        code = getattr(e, "code", None)
        if code not in (403, 429):
            return None
        retry_after: Optional[float] = None
        # google-genai's APIError carries an httpx.Response-like object
        # on `.response` for live API calls; replay shims set it to None.
        try:
            response = getattr(e, "response", None)
            if response is not None:
                headers = getattr(response, "headers", None) or {}
                header = headers.get("retry-after") if hasattr(headers, "get") else None
                if header:
                    retry_after = float(header)
        except (AttributeError, TypeError, ValueError):
            retry_after = None
        return {
            "status_code": int(code),
            "provider": self.provider_id or "gemini",
            "message": self._format_error(e),
            "retry_after": retry_after,
        }

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
        logger = logging.getLogger(__name__)
        logger.debug(f"Gemini error traceback:\n{traceback.format_exc()}")
