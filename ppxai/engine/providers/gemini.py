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
import base64
import json
import logging
import traceback
import uuid
from typing import List, AsyncIterator, Optional, Dict, Any

import httpx

from ...common.logger import get_logger
from ...config.tls import tls_verify
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


# JSON-Schema keys the google-genai ``Schema`` model accepts (camelCase alias
# form, verified against SDK 1.56.0). Any OTHER key is rejected by pydantic
# with ``extra_forbidden``, which fails the WHOLE request client-side — one
# incompatible tool schema kills the run before anything reaches the API.
_GEMINI_SCHEMA_KEYS = frozenset({
    "type", "format", "title", "description", "nullable", "default",
    "enum", "example", "pattern",
    "minimum", "maximum", "minLength", "maxLength",
    "minItems", "maxItems", "minProperties", "maxProperties",
    "items", "properties", "required", "propertyOrdering",
    "additionalProperties", "anyOf",
})

# Keys whose value is itself a schema / collection of schemas — recurse.
_GEMINI_SUBSCHEMA_LIST_KEYS = ("anyOf",)


def _sanitize_schema_for_gemini(schema):
    """Downgrade a JSON-Schema fragment to the subset Gemini accepts.

    OpenAI-compatible providers take raw JSON Schema, but Gemini's
    function-declaration ``Schema`` is a strict OpenAPI-style subset:
    ``oneOf`` and friends are ``extra_forbidden`` (caught live on v1.19.0
    ``/task`` — ``spawn_subagent.allow_outbound`` uses ``items.oneOf`` and
    the ValidationError failed the run instantly). Applied to EVERY tool's
    parameters in :meth:`GeminiProvider._convert_tools_to_gemini` so future
    tools can't reintroduce the failure.

    Lossy on purpose, in the permissive direction — the model may produce
    arguments the original schema would have constrained further; the tool
    itself remains the enforcement point:

      * ``oneOf`` -> ``anyOf`` (the union form the SDK supports)
      * ``allOf`` -> shallow merge of its (sanitized) variants
      * list-form ``type`` (``["string", "null"]``) -> single type + nullable
      * unsupported keys -> dropped
    """
    if not isinstance(schema, dict):
        return schema

    out = {}
    for key, value in schema.items():
        if key == "oneOf":
            variants = [_sanitize_schema_for_gemini(v) for v in value] \
                if isinstance(value, list) else []
            out.setdefault("anyOf", []).extend(variants)
        elif key == "allOf":
            # Shallow-merge the variants: properties/required union,
            # first-wins for scalar keys.
            merged = {}
            for variant in (value if isinstance(value, list) else []):
                variant = _sanitize_schema_for_gemini(variant)
                if not isinstance(variant, dict):
                    continue
                for k, v in variant.items():
                    if k == "properties" and isinstance(merged.get(k), dict):
                        merged[k] = {**v, **merged[k]}
                    elif k == "required" and isinstance(merged.get(k), list):
                        merged[k] = list(dict.fromkeys(merged[k] + v))
                    else:
                        merged.setdefault(k, v)
            for k, v in merged.items():
                out.setdefault(k, v)
        elif key == "type" and isinstance(value, list):
            non_null = [t for t in value if t != "null"]
            if non_null:
                out["type"] = non_null[0]
            if "null" in value:
                out["nullable"] = True
        elif key not in _GEMINI_SCHEMA_KEYS:
            continue  # unsupported keyword — drop rather than fail the request
        elif key == "properties" and isinstance(value, dict):
            out[key] = {name: _sanitize_schema_for_gemini(sub)
                        for name, sub in value.items()}
        elif key in ("items", "additionalProperties"):
            out[key] = _sanitize_schema_for_gemini(value)
        elif key in _GEMINI_SUBSCHEMA_LIST_KEYS and isinstance(value, list):
            existing = out.setdefault(key, [])
            existing.extend(_sanitize_schema_for_gemini(v) for v in value)
        else:
            out[key] = value
    return out


# ── OpenAI `response_format` → Gemini structured output ──────────────────────
# Every other provider forwards `response_format` straight to an
# OpenAI-compatible endpoint (openai_compat.py, openai_native.py,
# perplexity.py). Gemini can't: it uses generate_content, whose equivalent
# knobs are `response_mime_type` + `response_schema`. Until v1.19.1 the
# parameter was accepted and silently dropped here, so a caller pinning a
# JSON schema got a 200 and unconstrained prose-shaped JSON with no error
# anywhere — see docs/handoff-seam-watcher.md.
#
# `response_schema` and a function declaration's `parameters` are the same
# google-genai `Schema` model, so the structural work is shared:
# `_sanitize_schema_for_gemini` above, reused rather than reimplemented — a
# second whitelist would drift from the one verified against the SDK, and it
# already handles oneOf→anyOf, allOf merging and list-form `type`.
#
# But the two are NOT interchangeable, and the difference is invisible
# client-side. The SDK's pydantic Schema model ACCEPTS `additionalProperties`
# (hence its presence in _GEMINI_SCHEMA_KEYS, and no ValidationError), while
# the REST API rejects it under this key specifically. Observed live,
# 2026-08-08, gemini-3.1-pro-preview:
#
#   400 INVALID_ARGUMENT — Unknown name "additional_properties" at
#   'generation_config.response_schema': Cannot find field.
#
# `"additionalProperties": false` is emitted by virtually every
# OpenAI-generated schema, so this is the common case, not an edge one.
# Passing SDK validation is NOT evidence the API will accept a payload.
_RESPONSE_SCHEMA_REJECTED_KEYS = frozenset({"additionalProperties"})


def _strip_response_schema_rejects(node):
    """Remove keys valid on a function declaration but not on response_schema."""
    if isinstance(node, list):
        return [_strip_response_schema_rejects(v) for v in node]
    if not isinstance(node, dict):
        return node
    return {
        k: _strip_response_schema_rejects(v)
        for k, v in node.items()
        if k not in _RESPONSE_SCHEMA_REJECTED_KEYS
    }
def response_format_to_gemini(response_format: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Map an OpenAI-shaped `response_format` onto Gemini config kwargs.

    `{"type": "json_object"}`  → JSON mime type, model picks the shape.
    `{"type": "json_schema", "json_schema": {"schema": {...}}}`
                               → JSON mime type + a filtered schema.

    Returns `{}` for anything unrecognised (including None), so an unknown
    shape degrades to today's behaviour rather than raising.
    """
    if not isinstance(response_format, dict):
        return {}
    kind = response_format.get("type")
    if kind == "json_object":
        return {"response_mime_type": "application/json"}
    if kind == "json_schema":
        block = response_format.get("json_schema")
        out: Dict[str, Any] = {"response_mime_type": "application/json"}
        schema = block.get("schema") if isinstance(block, dict) else None
        if isinstance(schema, dict):
            out["response_schema"] = _strip_response_schema_rejects(
                _sanitize_schema_for_gemini(schema)
            )
        return out
    return {}


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

        # Initialize the Gemini client with TLS configuration resolved by the
        # shared resolver (env SSL_VERIFY/SSL_CERT_FILE, then network.ssl.*).
        # tls_verify() returns False (off) or an SSLContext — never True — so
        # the explicit httpx client is always supplied.
        self.client = genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(
                httpx_client=httpx.Client(verify=tls_verify())
            ),
        )

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
                                    tool_call = self._parse_function_call(fc, part)
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
                    payload = {
                        "tool": tc["name"],
                        "arguments": tc["arguments"],
                        "tool_call_id": tc["tool_call_id"],
                        "native": True,  # Mark as native tool call
                    }
                    # Item 45: carry Gemini 3.x's opaque signature so the
                    # engine can echo it back on the follow-up turn.
                    if tc.get("thought_signature"):
                        payload["thought_signature"] = tc["thought_signature"]
                    yield Event(EventType.TOOL_CALL, payload)

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
                            tool_call = self._parse_function_call(fc, part)
                            if tool_call:
                                tool_calls.append(tool_call)

                usage = self._parse_usage(response.usage_metadata)

                # Extract grounding citations
                citations = []
                if response.candidates and response.candidates[0].grounding_metadata:
                    citations = self._parse_grounding(response.candidates[0].grounding_metadata)

                # Emit TOOL_CALL events for any function calls (v1.15.2)
                for tc in tool_calls:
                    payload = {
                        "tool": tc["name"],
                        "arguments": tc["arguments"],
                        "tool_call_id": tc["tool_call_id"],
                        "native": True,
                    }
                    # Item 45: see the streaming branch above.
                    if tc.get("thought_signature"):
                        payload["thought_signature"] = tc["thought_signature"]
                    yield Event(EventType.TOOL_CALL, payload)

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
        Gemini's system_instruction.

        v1.19.1: `response_format` IS now honoured — mapped onto Gemini's
        `response_mime_type` / `response_schema` by
        `response_format_to_gemini`. It was previously accepted and dropped,
        which meant a caller pinning a JSON schema got a 200 and
        unconstrained output with no error raised anywhere.

        Structured output and Google Search grounding COEXIST — verified live
        2026-08-09. Only function declarations conflict with grounding.
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
            response_format=response_format,
        )

        response = self.client.models.generate_content(
            model=model, contents=contents, config=config
        )

        content = ""
        reasoning = ""
        finish_reason = None
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    # v1.19.1 Item 51: a thinking model returns its internal
                    # monologue as parts flagged `thought=True`. The streaming
                    # chat() path has always split these out (REASONING_CHUNK
                    # vs STREAM_CHUNK); oneshot concatenated everything, so the
                    # caller got "My Thought Process: … Okay, the user wants …"
                    # as the ANSWER (observed live 2026-07-22 via /agentrun,
                    # which drives oneshot, on gemini-3.1-pro-preview).
                    # Same rule in both paths: thoughts are not the answer.
                    if getattr(part, "thought", False):
                        reasoning += part.text
                    else:
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
        # Degenerate case: the model emitted ONLY thought parts (no answer).
        # Returning "" would look like an empty completion and hide the cause,
        # so fall back to the reasoning text rather than losing the response.
        if not content and reasoning:
            logger.debug(
                f"Gemini oneshot returned only thought parts "
                f"({len(reasoning)} chars); falling back to reasoning as content."
            )
            content = reasoning

        result = {
            "content": content,
            "finish_reason": finish_reason,
            "model": model,
            "usage": usage_dict,
        }
        # Additive: callers that want the monologue can read it; the ones that
        # only read `content` are unaffected (Item 51).
        if reasoning:
            result["reasoning"] = reasoning
        return result

    def _convert_messages(self, messages: List[Message]) -> tuple:
        """Convert Message objects to Gemini format.

        Gemini uses a different format than OpenAI:
        - 'user' and 'model' roles (not 'assistant')
        - 'parts' array instead of 'content' string
        - System messages become system_instruction in config
        - Native tool round-trips use function_call / function_response
          parts instead of OpenAI's tool_calls / tool-role messages

        The engine's native pairing branch (engine/chat.py) records tool
        round-trips as an assistant message carrying `tool_calls` followed
        by tool-role messages carrying `tool_call_id`. Gemini's wire format
        has no id field on function responses — pairing is by function
        NAME — so the id→name mapping is resolved here from the preceding
        assistant turn. A tool result whose id can't be resolved falls back
        to a plain user text turn rather than an invalid function_response.

        Args:
            messages: List of Message objects

        Returns:
            Tuple of (contents list, system_instruction string or None)
        """
        contents = []
        system_parts = []
        call_id_to_name: Dict[str, str] = {}

        if not messages:
            return contents, None

        for m in messages:
            if m.role == "system":
                # Collect system messages for system_instruction. Gemini's
                # system_instruction is text-only, so flatten any multimodal
                # content to its text representation.
                system_parts.append(m.text_content())
            elif m.role == "assistant" and m.tool_calls:
                parts: List[Dict[str, Any]] = []
                text = m.text_content()
                if text and text.strip():
                    parts.append({"text": text})
                for tc in m.tool_calls:
                    func = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                    name = func.get("name", "")
                    if not name:
                        continue
                    args = self._parse_tool_call_arguments(func.get("arguments"))
                    call_id = tc.get("id")
                    if call_id:
                        call_id_to_name[call_id] = name
                    fc_part: Dict[str, Any] = {
                        "function_call": {"name": name, "args": args}
                    }
                    # Item 45: Gemini 3.x REQUIRES the signature it issued with
                    # this call to come back on the functionCall part, or the
                    # whole request 400s ("missing a thought_signature in
                    # functionCall parts"). 2.5 never sets it → key absent →
                    # unchanged behaviour there.
                    sig = self._decode_thought_signature(
                        tc.get("thought_signature") if isinstance(tc, dict) else None
                    )
                    if sig:
                        fc_part["thought_signature"] = sig
                    parts.append(fc_part)
                if parts:
                    contents.append({"role": "model", "parts": parts})
            elif m.role == "tool":
                name = call_id_to_name.get(m.tool_call_id or "")
                if name:
                    contents.append({
                        "role": "user",
                        "parts": [{
                            "function_response": {
                                "name": name,
                                "response": {"result": m.text_content()},
                            }
                        }],
                    })
                else:
                    # Unpaired tool result (e.g. restored session that lost
                    # the assistant turn) — degrade to a plain user turn.
                    contents.append({
                        "role": "user",
                        "parts": self._content_to_gemini_parts(m.content),
                    })
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
    def _parse_tool_call_arguments(raw: Any) -> Dict[str, Any]:
        """Normalize a recorded tool-call `arguments` value to a dict.

        The engine stores arguments as a JSON string (OpenAI wire shape);
        Gemini's function_call part wants the structured dict. Malformed
        JSON degrades to {} — the call was already executed, the replayed
        part only needs to exist for transcript coherence.
        """
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw:
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

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
        tools: Optional[List] = None,
        response_format: Optional[Dict[str, Any]] = None,
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

        # Structured output is resolved FIRST because it decides whether
        # grounding may be added at all (see below) — the same coexistence
        # rule function declarations already follow.
        structured = response_format_to_gemini(response_format)
        config_kwargs.update(structured)

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

        # Add Google Search Grounding ONLY if no function declarations —
        # THOSE cannot coexist with grounding in the same request (400
        # INVALID_ARGUMENT).
        #
        # Structured output is NOT such a conflict, contrary to an earlier
        # revision of this code which also suppressed grounding whenever a
        # response_format was set. Verified live against
        # gemini-3.1-pro-preview, 2026-08-09 — both of these are ACCEPTED:
        #   google_search + response_mime_type
        #   google_search + response_mime_type + response_schema
        # The restriction was generalized from the function-declaration case
        # without being tested, and the cost was silent: a caller combining
        # `response_format` with `execution.run.grounding` kept its JSON and
        # quietly lost its search.
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
                # Parameters are JSON Schema, but Gemini validates a strict
                # OpenAPI subset — sanitize or one bad tool kills the request.
                if "parameters" in func:
                    declaration["parameters"] = _sanitize_schema_for_gemini(
                        func["parameters"]
                    )
                declarations.append(declaration)
        return declarations

    def _parse_function_call(self, function_call, part=None) -> Optional[Dict[str, Any]]:
        """Parse a Gemini function_call part into tool call dict.

        Args:
            function_call: Gemini FunctionCall object with name and args
            part: the enclosing Part, when available. Gemini 3.x carries
                `thought_signature` on the PART (not on the FunctionCall), and
                requires it to be echoed back on the follow-up turn — see
                `_thought_signature_of` and `_convert_messages`.

        Returns:
            Dict with 'name', 'arguments', 'tool_call_id' and (when present)
            'thought_signature', or None if invalid. Gemini only populates
            FunctionCall.id in some API configurations, so a missing id is
            synthesized — the engine's native pairing branch requires every
            call to carry one, and the id never goes back on the wire (Gemini
            pairs responses by function name; see _convert_messages).
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

        call_id = getattr(function_call, 'id', None) or f"gemini-fc-{uuid.uuid4().hex[:12]}"
        parsed = {"name": name, "arguments": args, "tool_call_id": call_id}
        sig = self._thought_signature_of(part, function_call)
        if sig:
            parsed["thought_signature"] = sig
        return parsed

    @staticmethod
    def _thought_signature_of(part, function_call=None) -> Optional[str]:
        """Extract Gemini 3.x `thought_signature` from a response part.

        v1.19.1 Item 45: Gemini 3.x models return an opaque `thought_signature`
        alongside each `function_call` and **reject the follow-up turn** unless
        the client echoes it back on the corresponding functionCall part:

            400 INVALID_ARGUMENT — Function call is missing a thought_signature
            in functionCall parts … `default_api:<tool>`, position N

        Reproduced live 3x on `gemini-3.1-pro-preview` (read_file, web_search),
        which made EVERY native tool round-trip fail on 3.x. Gemini 2.5 does
        not send the field, so absence is normal there and must stay silent.

        The field is `Optional[bytes]` on the PART (verified against
        google-genai `types.Part.model_fields`). It is stored base64-encoded
        because the engine's session transcript is JSON and raw bytes are not
        serialisable — `_decode_thought_signature` reverses that on the way
        back out, so the SDK receives the EXACT original bytes. Encoding
        without decoding was the first fix attempt's bug: the wire then
        carried a str where the SDK wanted bytes and the 400 persisted.
        The FunctionCall is probed as a defensive fallback in case a future
        SDK relocates the field.
        """
        for holder in (part, function_call):
            if holder is None:
                continue
            for attr in ("thought_signature", "thoughtSignature"):
                sig = getattr(holder, attr, None)
                if not sig:
                    continue
                if isinstance(sig, bytes):
                    try:
                        return base64.b64encode(sig).decode("ascii")
                    except Exception:
                        return None
                return str(sig)
        return None

    @staticmethod
    def _decode_thought_signature(sig):
        """Reverse `_thought_signature_of` for the outbound wire.

        The SDK types `Part.thought_signature` as `Optional[bytes]` and
        pydantic rejects a non-base64 str outright, so the value we stored
        (base64 text, for JSON-safety in the session transcript) must be
        decoded back to the ORIGINAL bytes before it goes out. Returns None
        when the value cannot be decoded, so a malformed signature degrades to
        "omit the field" rather than poisoning the whole request.
        """
        if not sig:
            return None
        if isinstance(sig, bytes):
            return sig
        try:
            return base64.b64decode(sig, validate=True)
        except Exception:
            return None

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
