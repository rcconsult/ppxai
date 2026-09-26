"""OpenAI Responses API (`/v1/responses`) as a wire-protocol handler.

Lifted from `OpenAINativeProvider` (ADR 0012 migration step 1) so the wire
lives in one place instead of as four private methods on one provider. The
six lifted members were copied mechanically out of that file, so "no
behaviour change" is a property of the extraction, not a promise;
`tests/test_wire_responses_extraction.py` pins the outgoing request kwargs
with a spy either side of the move.

Codex and Pro models 404 on Chat Completions with "not a chat model"
(measured — commit `5e1ace2f` added the routing and a 404 auto-fallback after
hitting it live). That is why the wire is a per-model fact rather than a
provider-wide one: the same OpenAI account, the same key, two protocols.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from .... import usage as _usage
from ....common.logger import get_logger
from ...types import Event, EventType, Message, UsageStats
from ...uploaded_file import assert_wire_blocks_clean, flatten_uploaded_file_blocks

logger = get_logger("wire.responses")


class ResponsesHandler:
    """The `responses` wire. Stateless; the host supplies client and config.

    `ctx` is the hosting provider. What this handler reads from it:
    `client` (OpenAI SDK), `enable_web_search`, `get_facts_for_model`,
    `_get_max_tokens`, `_get_extra_body`, plus the shared error helpers
    (`_classify_throttle`, `_format_error`, `_log_error_traceback`,
    `provider_id`). Those last four stay host concerns deliberately:
    throttle telemetry and error formatting belong to the account, not to
    the wire format.
    """

    name = "responses"

    # ------------------------------------------------------------------
    # Conversion (lifted verbatim)
    # ------------------------------------------------------------------

    @staticmethod
    def convert_messages(messages: list[Message]) -> tuple:
        """Convert Messages to Responses API format.

        R5 (v1.17.6): any `uploaded_file` blocks on user/assistant/tool
        messages are flattened to legacy text markers before they enter
        the Responses API request. System messages are already flattened
        to text via `text_content()`, so they're covered implicitly.

        Returns:
            Tuple of (instructions string or None, input items list)
        """
        instructions_parts = []
        input_items = []

        for m in messages:
            if m.role == "system":
                # system_instruction is text-only — multimodal content never
                # appears on system messages, but extract text defensively.
                instructions_parts.append(m.text_content())
            elif m.role == "tool":
                # Tool result. The Responses API does NOT take a `tool` role
                # with `tool_call_id` — that is the chat-completions shape. It
                # takes a standalone `function_call_output` item keyed by
                # `call_id`. Sending the chat shape here returned
                # `400 Unknown parameter: 'input[N].tool_calls'` and made the
                # whole responses-wire fleet (gpt-5.6-terra, gpt-5.3-codex,
                # gpt-5-pro) unable to complete a single tool round trip.
                content = flatten_uploaded_file_blocks(m.content)
                # ADR 0006 Step 6 sentinel, ADR 0012 Item 62 fix (a): the
                # validator had exactly ONE call site (the chat-completions
                # emitter), so two of three wires reached the network
                # unchecked. It belongs to the conversion, so it moves with
                # the conversion — same position as base.py's call, right
                # after the flatten. `__debug__`-gated: no cost under -O.
                assert_wire_blocks_clean(content, role=m.role)
                item: dict[str, Any] = {
                    "type": "function_call_output",
                    "call_id": m.tool_call_id or "",
                    # `output` is a STRING on this wire, never a block list.
                    # Join the ALREADY-FLATTENED blocks rather than calling
                    # `text_content()`: the flatten emits the wire marker
                    # (`<uploaded_file .../>`, ADR 0006) while text_content
                    # emits the human-readable `[File: name]` used for logs.
                    # Using the latter here would silently ship the log form
                    # to the API and drop the flatten contract.
                    "output": content if isinstance(content, str) else "".join(
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ),
                }
                input_items.append(item)
            else:
                role = "assistant" if m.role == "assistant" else "user"
                content = flatten_uploaded_file_blocks(m.content)
                assert_wire_blocks_clean(content, role=m.role)
                # Only emit the message item when it actually carries content.
                # An assistant turn that was pure tool calls has empty content,
                # and an empty item is noise the API does not need.
                if content:
                    input_items.append({
                        "role": role,
                        "content": ResponsesHandler.to_responses_parts(content, role),
                    })
                # Assistant tool calls become SEPARATE `function_call` items.
                # The engine stores them in the normalised chat-completions
                # shape (`{"id", "function": {"name", "arguments"}}`) because
                # that is what `_stream`/`_non_stream` emit for every wire, so
                # the translation back out belongs here.
                if m.tool_calls:
                    for tc in m.tool_calls:
                        fn = tc.get("function") or {}
                        input_items.append({
                            "type": "function_call",
                            "call_id": tc.get("id") or "",
                            "name": fn.get("name") or "",
                            # `arguments` is a JSON STRING, not an object.
                            "arguments": fn.get("arguments") or "{}",
                        })

        instructions = "\n\n".join(instructions_parts) if instructions_parts else None
        return instructions, input_items

    @staticmethod
    def to_responses_parts(content: Any, role: str) -> Any:
        """Translate chat-completions content parts to Responses input parts.

        A string passes through (the API takes a bare string). A list is
        rewritten part by part, because `/v1/responses` rejects the
        chat-completions part types outright: Perplexity answered an
        attachment with `input[N]: content part 0: invalid type "text"`
        (smoke run 2026-09-26). User parts become `input_text` /
        `input_image` / `input_file`; assistant parts become `output_text`.
        An unknown part type is passed through unchanged, so the API names
        it instead of it vanishing here.
        """
        if not isinstance(content, list):
            return content
        text_type = "output_text" if role == "assistant" else "input_text"
        parts: list[Any] = []
        for block in content:
            if not isinstance(block, dict):
                parts.append(block)
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append({"type": text_type, "text": block.get("text", "")})
            elif btype == "image_url":
                image = block.get("image_url")
                url = image.get("url", "") if isinstance(image, dict) else image
                part: dict[str, Any] = {"type": "input_image", "image_url": url}
                if isinstance(image, dict) and image.get("detail"):
                    part["detail"] = image["detail"]
                parts.append(part)
            elif btype == "file":
                file_obj = block.get("file") or {}
                parts.append({"type": "input_file", **file_obj})
            else:
                parts.append(block)
        return parts

    # ------------------------------------------------------------------
    # Reserved function names (debt: smoke run 2026-09-26, defect 4)
    # ------------------------------------------------------------------

    #: Prefix a reserved tool name gets on the wire. The model sees and calls
    #: `ppxai_search_files`; ppxai's tool registry, grants, consent and
    #: hints keep the real name, because the alias never leaves this module.
    RESERVED_ALIAS_PREFIX = "ppxai_"

    @staticmethod
    def _reserved(ctx: Any) -> frozenset[str]:
        # Optional host attribute, same contract as `enable_web_search`:
        # a host with no reserved names simply does not declare any.
        return frozenset(getattr(ctx, "reserved_function_names", ()) or ())

    @classmethod
    def alias_name(cls, name: str, reserved: frozenset[str]) -> str:
        return f"{cls.RESERVED_ALIAS_PREFIX}{name}" if name in reserved else name

    @classmethod
    def unalias_name(cls, name: str, reserved: frozenset[str]) -> str:
        prefix = cls.RESERVED_ALIAS_PREFIX
        if name.startswith(prefix) and name[len(prefix):] in reserved:
            return name[len(prefix):]
        return name

    @classmethod
    def _alias_chat_tools(
        cls, tools: list[dict[str, Any]], reserved: frozenset[str]
    ) -> list[dict[str, Any]]:
        """Copy chat-format tools with every reserved name aliased."""
        aliased = []
        for tool in tools:
            func = tool.get("function") if isinstance(tool, dict) else None
            if isinstance(func, dict) and func.get("name") in reserved:
                tool = {**tool, "function": {**func, "name": cls.alias_name(func["name"], reserved)}}
            aliased.append(tool)
        return aliased

    @staticmethod
    def convert_tools(openai_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI chat tools format to Responses API format.

        Chat Completions: {"type": "function", "function": {"name": ..., "parameters": ...}}
        Responses API:    {"type": "function", "name": ..., "parameters": ...}
        """
        response_tools = []
        for tool in openai_tools:
            if tool.get("type") == "function" and "function" in tool:
                func = tool["function"]
                response_tool = {
                    "type": "function",
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                }
                if "parameters" in func:
                    response_tool["parameters"] = func["parameters"]
                response_tools.append(response_tool)
        return response_tools

    @staticmethod
    def build_tool_hint(openai_tools: list[dict[str, Any]]) -> str:
        """Build a concise tool hint for injection into instructions.

        This provides belt-and-suspenders context: if the model outputs
        tool calls as JSON text instead of native function_call items,
        the text-based parser in chat.py can still identify them.
        """
        if not openai_tools:
            return ""
        lines = ["You have the following tools available. Use them by calling the function directly:"]
        for tool in openai_tools:
            if tool.get("type") == "function" and "function" in tool:
                func = tool["function"]
                name = func.get("name", "")
                desc = func.get("description", "")
                params = func.get("parameters", {})
                param_names = list(params.get("properties", {}).keys()) if params else []
                if name:
                    param_str = f"({', '.join(param_names)})" if param_names else "()"
                    lines.append(f"- {name}{param_str}: {desc}")
        return "\n".join(lines) if len(lines) > 1 else ""

    # ------------------------------------------------------------------
    # Usage parsing
    # ------------------------------------------------------------------

    @staticmethod
    def parse_usage(usage) -> UsageStats | None:
        """Parse usage from Responses API response.

        Responses API uses input_tokens/output_tokens instead of
        prompt_tokens/completion_tokens.
        """
        if not usage:
            return None
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        return UsageStats(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    @staticmethod
    def _budget_for(ctx: Any, model: str) -> int | None:
        """Output budget: operator config first, then the shipped fact.

        `ctx._get_max_tokens()` reads CONFIG only. `ModelFacts.max_tokens` is
        the shipped table's answer, and for some models it is not a
        preference but a requirement — Perplexity's Agent API rejects
        `anthropic/*` outright with *"max_output_tokens is required when
        using Anthropic models"* (measured live 2026-08-31, W3 trial). A
        table row saying 4096 that the wire never sees is the same
        declared-but-inert shape this ADR exists to remove, so both sources
        are read here, in one place, config first.
        """
        configured = ctx._get_max_tokens(model)
        if configured:
            return configured
        facts = ctx.get_facts_for_model(model)
        return getattr(facts, "max_tokens", 0) or None

    def build_request(
        self,
        ctx: Any,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        for_oneshot: bool = False,
    ) -> dict[str, Any]:
        """Assemble the `client.responses.create(**kwargs)` arguments.

        Split out of `chat()`/`oneshot()` so the extraction fence can compare
        request kwargs without issuing a request. `for_oneshot` selects the
        stateless variant, which sends no tools and no web-search preview —
        matching what `_oneshot_responses` did before the move.
        """
        instructions, input_items = self.convert_messages(messages)

        # A provider may reserve function names for its own built-in tools.
        # Perplexity rejects `search_files`, `web_search` and `fetch_url`
        # ("custom function name ... is reserved"), and ppxai ships tools
        # with all three names. Alias them here, in the definitions, the
        # tool hint and the history's `function_call` items, and map them
        # back in `_stream` / `_non_stream`.
        reserved = self._reserved(ctx)
        if reserved:
            if tools:
                tools = self._alias_chat_tools(tools, reserved)
            for item in input_items:
                if item.get("type") == "function_call":
                    item["name"] = self.alias_name(item.get("name", ""), reserved)

        request_kwargs: dict[str, Any] = {"model": model, "input": input_items}
        if instructions:
            request_kwargs["instructions"] = instructions

        if for_oneshot:
            token_budget = (
                max_tokens if max_tokens is not None else self._budget_for(ctx, model)
            )
            if token_budget:
                request_kwargs["max_output_tokens"] = token_budget
        else:
            budget = self._budget_for(ctx, model)
            if budget:
                request_kwargs["max_output_tokens"] = budget

            response_tools = []
            # OPTIONAL host attribute, not a required one. `web_search_preview`
            # is OpenAI's server-side search tool; a host that does not offer
            # it simply has no such flag — Perplexity, for one, has search
            # built into the model and would be sent a tool its endpoint does
            # not define. W3 found this the honest way: the first live request
            # from a second host raised AttributeError here, because the host
            # contract was implicit-by-docstring. Defaulting is right, and a
            # named WireHost Protocol (W4) makes it explicit.
            if getattr(ctx, "enable_web_search", False):
                response_tools.append({"type": "web_search_preview"})

            # Per-model, not per-provider: get_facts_for_model() is the hook
            # that lets a provider mark individual models prompt-based.
            # Reading ctx.capabilities here ignored it -- o4-mini resolved
            # False but was sent native tools anyway.
            if tools and ctx.get_facts_for_model(model).tool_mode != "prompt_based":
                response_tools.extend(self.convert_tools(tools))

                # Belt-and-suspenders: also inject tool descriptions into
                # instructions so text-based fallback parsing works if the
                # model outputs tool calls as JSON in content instead of
                # native function_call items.
                tool_hint = self.build_tool_hint(tools)
                if tool_hint:
                    existing = request_kwargs.get("instructions", "")
                    if existing:
                        request_kwargs["instructions"] = f"{existing}\n\n{tool_hint}"
                    else:
                        request_kwargs["instructions"] = tool_hint

            if response_tools:
                request_kwargs["tools"] = response_tools

        # v1.18.3 follow-up: extra_body also works on the Responses API
        # (`client.responses.create(extra_body=...)`). Same lookup path as
        # Chat Completions; only sent when configured.
        extra_body = ctx._get_extra_body(model)
        if extra_body:
            request_kwargs["extra_body"] = extra_body

        return request_kwargs

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def chat(
        self,
        ctx: Any,
        messages: list[Message],
        model: str,
        stream: bool = True,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Event]:
        """Responses API path for Codex / Pro models.

        Uses client.responses.create() with a different message format.
        Native function calling: tools sent as function definitions in the
        API request. Model emits function_call items for tool use.
        Belt-and-suspenders: tool descriptions also injected into instructions
        so fallback text-based parsing works if model outputs JSON in content.
        """
        try:
            request_kwargs = self.build_request(ctx, messages, model, tools)

            yield Event(EventType.STREAM_START, {"model": model})

            if stream:
                async for event in self._stream(ctx, request_kwargs):
                    yield event
            else:
                async for event in self._non_stream(ctx, request_kwargs):
                    yield event

        except Exception as e:
            # v1.18.3 follow-up: typed throttle event + persistent telemetry.
            throttle = ctx._classify_throttle(e)
            if throttle is not None:
                throttle["model"] = model
                try:
                    _usage.record_provider_error(
                        provider=throttle["provider"] or ctx.provider_id or "",
                        status_code=throttle["status_code"],
                        model=model,
                    )
                except Exception:
                    pass
                yield Event(EventType.PROVIDER_THROTTLED, throttle)
            else:
                error_msg = ctx._format_error(e)
                yield Event(EventType.ERROR, error_msg)
            ctx._log_error_traceback(e)

    def oneshot(
        self,
        ctx: Any,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Stateless single-turn completion via the Responses API.

        Codex / Pro models return 404 on Chat Completions, so oneshot for
        those routes here. Non-streaming, sync (the caller offloads to a
        thread). Returns the same {content, finish_reason, model, usage}
        shape as the Chat Completions oneshot path.
        """
        request_kwargs = self.build_request(
            ctx, messages, model, max_tokens=max_tokens, for_oneshot=True
        )

        response = ctx.client.responses.create(**request_kwargs, stream=False)

        # Extract content from output items (same walk as _non_stream).
        content = ""
        if hasattr(response, "output"):
            for item in response.output:
                if getattr(item, "type", None) != "message":
                    continue
                item_content = getattr(item, "content", None)
                if isinstance(item_content, list):
                    for part in item_content:
                        if getattr(part, "type", None) == "output_text":
                            content += getattr(part, "text", "")
                elif isinstance(item_content, str):
                    content += item_content
        if not content and hasattr(response, "output_text"):
            content = response.output_text or ""

        usage_stats = self.parse_usage(getattr(response, "usage", None))
        usage_dict = None
        if usage_stats is not None:
            usage_dict = {
                "prompt_tokens": usage_stats.prompt_tokens,
                "completion_tokens": usage_stats.completion_tokens,
                "total_tokens": usage_stats.total_tokens,
            }
        return {
            "content": content,
            "finish_reason": "stop",
            "model": getattr(response, "model", None) or model,
            "usage": usage_dict,
        }

    # ------------------------------------------------------------------
    # Response handling (lifted verbatim)
    # ------------------------------------------------------------------

    async def _stream(
        self,
        ctx: Any,
        request_kwargs: dict[str, Any],
    ) -> AsyncIterator[Event]:
        """Handle streaming Responses API response."""
        response_stream = ctx.client.responses.create(
            **request_kwargs,
            stream=True,
        )

        full_response = []
        usage = None
        # Track in-progress function calls: call_id -> {"name": str, "arguments": str}
        function_calls: dict[str, dict[str, str]] = {}

        for event in response_stream:
            event_type = getattr(event, "type", None)

            # Text delta events
            if event_type == "response.output_text.delta":
                delta_text = getattr(event, "delta", "")
                if delta_text:
                    full_response.append(delta_text)
                    yield Event(EventType.STREAM_CHUNK, delta_text)

            # Function call item started
            elif event_type == "response.output_item.added":
                item = getattr(event, "item", None)
                if item and getattr(item, "type", None) == "function_call":
                    call_id = getattr(item, "call_id", "") or getattr(item, "id", "")
                    name = getattr(item, "name", "")
                    if call_id:
                        function_calls[call_id] = {"name": name, "arguments": ""}

            # Function call arguments streaming
            elif event_type == "response.function_call_arguments.delta":
                call_id = getattr(event, "call_id", "")
                delta = getattr(event, "delta", "")
                if call_id in function_calls and delta:
                    function_calls[call_id]["arguments"] += delta

            # Function call arguments complete
            elif event_type == "response.function_call_arguments.done":
                call_id = getattr(event, "call_id", "")
                arguments = getattr(event, "arguments", "")
                name = getattr(event, "name", "")
                if call_id in function_calls:
                    function_calls[call_id]["arguments"] = arguments
                    if name:
                        function_calls[call_id]["name"] = name

            # Response completed — extract usage
            elif event_type == "response.completed":
                resp = getattr(event, "response", None)
                if resp:
                    usage = self.parse_usage(getattr(resp, "usage", None))

        # Emit TOOL_CALL events for all completed function calls, under the
        # REAL tool name (a reserved name was aliased in build_request).
        reserved = self._reserved(ctx)
        tool_calls_metadata = []
        for call_id, fc in function_calls.items():
            if fc.get("name"):
                fc["name"] = self.unalias_name(fc["name"], reserved)
                try:
                    args = json.loads(fc["arguments"]) if fc["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                yield Event(EventType.TOOL_CALL, {
                    "tool": fc["name"],
                    "arguments": args,
                    "native": True,
                    "tool_call_id": call_id,
                })
                tool_calls_metadata.append({
                    "id": call_id,
                    "function": {"name": fc["name"], "arguments": fc["arguments"]},
                })

        final_content = "".join(full_response)
        metadata: dict[str, Any] = {}
        if usage:
            metadata["usage"] = usage
        if tool_calls_metadata:
            metadata["tool_calls"] = tool_calls_metadata
        yield Event(EventType.STREAM_END, final_content, metadata or None)

    async def _non_stream(
        self,
        ctx: Any,
        request_kwargs: dict[str, Any],
    ) -> AsyncIterator[Event]:
        """Handle non-streaming Responses API response."""
        response = await asyncio.to_thread(
            lambda: ctx.client.responses.create(
                **request_kwargs,
                stream=False,
            )
        )

        content = ""
        tool_calls_metadata = []

        if hasattr(response, "output"):
            for item in response.output:
                item_type = getattr(item, "type", None)

                if item_type == "message":
                    item_content = getattr(item, "content", None)
                    if isinstance(item_content, list):
                        for part in item_content:
                            if getattr(part, "type", None) == "output_text":
                                content += getattr(part, "text", "")
                    elif isinstance(item_content, str):
                        content += item_content
                    elif item_content is not None:
                        logger.warning(
                            f"Unexpected item.content type in Responses API output: "
                            f"{type(item_content).__name__!r} (value={item_content!r}), "
                            f"item_type={item_type!r} — skipping"
                        )

                elif item_type == "function_call":
                    call_id = getattr(item, "call_id", "") or getattr(item, "id", "")
                    name = self.unalias_name(getattr(item, "name", ""), self._reserved(ctx))
                    arguments = getattr(item, "arguments", "")
                    if name:
                        try:
                            args = json.loads(arguments) if arguments else {}
                        except json.JSONDecodeError:
                            args = {}
                        yield Event(EventType.TOOL_CALL, {
                            "tool": name,
                            "arguments": args,
                            "native": True,
                            "tool_call_id": call_id,
                        })
                        tool_calls_metadata.append({
                            "id": call_id,
                            "function": {"name": name, "arguments": arguments},
                        })

        # Fallback: output_text convenience attribute
        if not content and not tool_calls_metadata and hasattr(response, "output_text"):
            content = response.output_text or ""

        usage = self.parse_usage(getattr(response, "usage", None))

        metadata: dict[str, Any] = {"usage": usage}
        if tool_calls_metadata:
            metadata["tool_calls"] = tool_calls_metadata
        yield Event(EventType.STREAM_END, content, metadata)

    # ------------------------------------------------------------------
    # Message conversion helpers
    # ------------------------------------------------------------------
