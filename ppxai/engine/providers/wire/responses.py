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
from typing import Any, AsyncIterator, Dict, List, Optional

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
    def convert_messages(messages: List[Message]) -> tuple:
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
                # Tool result — include tool_call_id for proper linking
                content = flatten_uploaded_file_blocks(m.content)
                # ADR 0006 Step 6 sentinel, ADR 0012 Item 62 fix (a): the
                # validator had exactly ONE call site (the chat-completions
                # emitter), so two of three wires reached the network
                # unchecked. It belongs to the conversion, so it moves with
                # the conversion — same position as base.py's call, right
                # after the flatten. `__debug__`-gated: no cost under -O.
                assert_wire_blocks_clean(content, role=m.role)
                item: Dict[str, Any] = {
                    "role": "tool",
                    "content": content,
                }
                if m.tool_call_id:
                    item["tool_call_id"] = m.tool_call_id
                input_items.append(item)
            else:
                role = "assistant" if m.role == "assistant" else "user"
                content = flatten_uploaded_file_blocks(m.content)
                assert_wire_blocks_clean(content, role=m.role)
                item = {
                    "role": role,
                    "content": content,
                }
                if m.tool_calls:
                    item["tool_calls"] = m.tool_calls
                input_items.append(item)

        instructions = "\n\n".join(instructions_parts) if instructions_parts else None
        return instructions, input_items

    @staticmethod
    def convert_tools(openai_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
    def build_tool_hint(openai_tools: List[Dict[str, Any]]) -> str:
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
    def parse_usage(usage) -> Optional[UsageStats]:
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
    def _budget_for(ctx: Any, model: str) -> Optional[int]:
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
        messages: List[Message],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: Optional[int] = None,
        for_oneshot: bool = False,
    ) -> Dict[str, Any]:
        """Assemble the `client.responses.create(**kwargs)` arguments.

        Split out of `chat()`/`oneshot()` so the extraction fence can compare
        request kwargs without issuing a request. `for_oneshot` selects the
        stateless variant, which sends no tools and no web-search preview —
        matching what `_oneshot_responses` did before the move.
        """
        instructions, input_items = self.convert_messages(messages)

        request_kwargs: Dict[str, Any] = {"model": model, "input": input_items}
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
        messages: List[Message],
        model: str,
        stream: bool = True,
        tools: Optional[List[Dict[str, Any]]] = None,
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
                    from ....usage import record_provider_error
                    record_provider_error(
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
        messages: List[Message],
        model: str,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
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
        request_kwargs: Dict[str, Any],
    ) -> AsyncIterator[Event]:
        """Handle streaming Responses API response."""
        response_stream = ctx.client.responses.create(
            **request_kwargs,
            stream=True,
        )

        full_response = []
        usage = None
        # Track in-progress function calls: call_id -> {"name": str, "arguments": str}
        function_calls: Dict[str, Dict[str, str]] = {}

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

        # Emit TOOL_CALL events for all completed function calls
        tool_calls_metadata = []
        for call_id, fc in function_calls.items():
            if fc.get("name"):
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
        metadata: Dict[str, Any] = {}
        if usage:
            metadata["usage"] = usage
        if tool_calls_metadata:
            metadata["tool_calls"] = tool_calls_metadata
        yield Event(EventType.STREAM_END, final_content, metadata or None)

    async def _non_stream(
        self,
        ctx: Any,
        request_kwargs: Dict[str, Any],
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
                    name = getattr(item, "name", "")
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

        metadata: Dict[str, Any] = {"usage": usage}
        if tool_calls_metadata:
            metadata["tool_calls"] = tool_calls_metadata
        yield Event(EventType.STREAM_END, content, metadata)

    # ------------------------------------------------------------------
    # Message conversion helpers
    # ------------------------------------------------------------------
