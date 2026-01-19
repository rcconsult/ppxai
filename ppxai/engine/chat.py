"""
Chat implementation for the ppxai engine.

This module contains the core chat logic, separated from EngineClient.
Uses dependency injection via ChatContext protocol for testability.

Architecture:
- ChatContext: Protocol defining what chat functions need
- chat_simple: Chat without tool support
- chat_with_tools: Chat with tool iteration loop
"""

import asyncio
import json
from dataclasses import asdict
from typing import AsyncIterator, Dict, Any, List, Optional, Protocol, Callable

from .types import Event, EventType, Message, UsageStats
from .session import SessionManager
from .tools.manager import ToolManager
from .tools.parser import parse_tool_call
from .providers.base import BaseProvider
from ..config import get_system_prompt, get_system_prompt_mode, calculate_cost
from ..common.logger import get_logger

logger = get_logger("chat")


class ChatContext(Protocol):
    """Protocol defining what chat functions need from the client.

    This allows chat functions to operate without importing EngineClient,
    breaking the import cycle and enabling easier testing.
    """

    @property
    def provider(self) -> Optional[BaseProvider]:
        """Current AI provider."""
        ...

    @property
    def provider_name(self) -> str:
        """Provider identifier string."""
        ...

    @property
    def model(self) -> str:
        """Current model name."""
        ...

    @property
    def session(self) -> SessionManager:
        """Session manager for message history."""
        ...

    @property
    def tool_manager(self) -> ToolManager:
        """Tool manager for tool execution."""
        ...

    @property
    def is_interrupted(self) -> bool:
        """Whether the current operation is interrupted."""
        ...

    def get_consent_events(self) -> List[Event]:
        """Get and clear queued consent events."""
        ...

    def track_tool_usage(self, tool_name: str, usage: Dict[str, Any]) -> None:
        """Track tool usage for cost calculation."""
        ...

    def commit_agent_changes_if_needed(self, message: str) -> Optional[str]:
        """Commit agent changes if in agent mode. Returns commit hash or None."""
        ...

    def get_bootstrap_prompt(self) -> str:
        """Get bootstrap prompt for current provider/model (v1.14.0)."""
        ...


async def chat_simple(
    ctx: ChatContext,
    stream: bool
) -> AsyncIterator[Event]:
    """Simple chat without tools.

    Args:
        ctx: Chat context with provider, session, etc.
        stream: Whether to stream the response

    Yields:
        Event objects for stream chunks and final response
    """
    # Auto-retry loop for empty responses
    max_retries = ctx.tool_manager.auto_retry_empty
    retry_count = 0

    while True:
        messages = ctx.session.get_messages()

        # Add system prompt for inline citation URLs if provider has web search/citations
        if ctx.provider and (ctx.provider.capabilities.citations or ctx.provider.capabilities.web_search):
            citation_prompt = Message(
                "system",
                "When citing sources, always include the full URL in parentheses after "
                "the citation number, like [1](https://example.com). This helps users "
                "click through to the sources directly."
            )
            messages = [citation_prompt] + messages

        full_response = ""
        response_metadata = None

        async for event in ctx.provider.chat(messages, ctx.model, stream):
            # Check for interrupt
            if ctx.is_interrupted:
                ctx.session.remove_last_message()
                yield Event(EventType.ERROR, "Interrupted by user")
                return

            if event.type == EventType.ERROR:
                removed = ctx.session.remove_last_message()
                logger.info(
                    f"Error rollback (simple): removed={removed}, "
                    f"messages_left={len(ctx.session.messages)}"
                )
                yield event
                return
            elif event.type == EventType.STREAM_END:
                full_response = event.data or ""
                response_metadata = event.metadata
            elif event.type == EventType.STREAM_CHUNK:
                yield event

        # Check for empty response and retry
        if not full_response.strip() and retry_count < max_retries and max_retries > 0:
            retry_count += 1
            yield Event(EventType.INFO, f"Empty response, retrying... ({retry_count}/{max_retries})")
            ctx.session.add_message(Message(
                "user",
                "Please proceed with the task. If you need more information, ask. "
                "If you can help, please respond."
            ))
            continue  # Retry

        # Add assistant message BEFORE yielding STREAM_END
        ctx.session.add_message(Message("assistant", full_response))

        if response_metadata and response_metadata.get("usage"):
            usage = response_metadata["usage"]
            usage.estimated_cost = calculate_cost(
                usage.prompt_tokens,
                usage.completion_tokens,
                ctx.model,
                ctx.provider_name
            )
            ctx.session.update_usage(usage, ctx.provider_name, ctx.model)
            response_metadata["usage"] = asdict(usage)

        yield Event(EventType.STREAM_END, full_response, response_metadata)
        return


async def chat_with_tools(
    ctx: ChatContext,
    stream: bool
) -> AsyncIterator[Event]:
    """Chat with tool support.

    Supports two modes:
    1. Native tool calling: Provider returns TOOL_CALL events
    2. Prompt-based: Parse tool calls from model's text response

    Args:
        ctx: Chat context with provider, session, tool_manager, etc.
        stream: Whether to stream the response

    Yields:
        Event objects for tool calls, results, and final response
    """
    iteration = 0
    max_iterations = ctx.tool_manager.max_iterations

    # Reset tool call history for loop detection
    ctx.tool_manager.reset_tool_history()

    # Track accumulated usage
    accumulated_usage = UsageStats()

    # Check if provider supports native tool calling
    use_native_tools = (
        ctx.provider and
        hasattr(ctx.provider, 'capabilities') and
        ctx.provider.capabilities.native_tool_calling
    )

    # Get tools in OpenAI format for native tool calling
    openai_tools = None
    if use_native_tools:
        openai_tools = ctx.tool_manager.get_tools_openai_format()
    else:
        openai_tools = True  # Signal tools enabled for prompt-based mode

    # Debug: log session state at start of chat_with_tools
    logger.debug(
        f"chat_with_tools start: messages={len(ctx.session.messages)}, "
        f"roles={[m.role for m in ctx.session.messages[-5:]]}"  # Last 5 message roles
    )

    yield Event(EventType.STREAM_START, {"model": ctx.model})

    empty_retry_count = 0

    while iteration < max_iterations:
        if ctx.is_interrupted:
            yield Event(EventType.ERROR, "Interrupted by user")
            return

        iteration += 1

        if iteration > 1:
            yield Event(EventType.INFO, f"Processing... (iteration {iteration})")

        messages = ctx.session.get_messages()

        if not use_native_tools:
            # Prompt-based tool calling
            tool_prompt = ctx.tool_manager.get_tools_prompt()
            if tool_prompt:
                # Add provider-specific guidance
                has_native_search = ctx.provider and (
                    ctx.provider.capabilities.citations or ctx.provider.capabilities.web_search
                )
                has_search_tool = ctx.tool_manager.get_tool("web_search") is not None

                if has_native_search and not has_search_tool:
                    tool_prompt += (
                        "\n\n## Native Web Search Capability\n"
                        "You have NATIVE web search capability built-in. For weather, current events, "
                        "web searches, or any real-time information: simply answer the question directly "
                        "using your native search - you do NOT need a tool for this."
                    )

                if has_native_search or has_search_tool:
                    tool_prompt += (
                        "\n\nWhen citing sources or URLs from search results, format them as markdown links "
                        "like [Source Name](https://example.com) so they are clickable."
                    )

                # Apply custom system prompt
                system_prompt = get_system_prompt(ctx.provider_name)
                prompt_mode = get_system_prompt_mode(ctx.provider_name)

                # Get bootstrap prompt (v1.14.0)
                bootstrap_prompt = ctx.get_bootstrap_prompt()

                # Assemble final prompt:
                # 1. Bootstrap (project context) - if present
                # 2. System prompt (user config)
                # 3. Tool prompt
                # Note: prompt_mode affects system_prompt placement relative to tool_prompt
                if prompt_mode == "replace":
                    final_prompt = system_prompt
                elif prompt_mode == "append":
                    final_prompt = f"{tool_prompt}\n\n{system_prompt}"
                else:  # "prepend" (default)
                    final_prompt = f"{system_prompt}\n\n{tool_prompt}"

                # Prepend bootstrap prompt if present (always first)
                if bootstrap_prompt:
                    final_prompt = f"{bootstrap_prompt}\n\n---\n\n{final_prompt}"

                messages = [Message("system", final_prompt)] + messages

        # Get response from provider
        full_response = ""
        native_tool_calls = []

        async for event in ctx.provider.chat(messages, ctx.model, stream=False, tools=openai_tools):
            if event.type == EventType.ERROR:
                # Only remove user message on first iteration (before any tool results added)
                # This prevents session corruption from orphan user messages (v1.14.1)
                if iteration == 1:
                    removed = ctx.session.remove_last_message()
                    logger.info(
                        f"Error rollback: iteration={iteration}, removed={removed}, "
                        f"messages_left={len(ctx.session.messages)}"
                    )
                yield event
                return
            elif event.type == EventType.TOOL_CALL:
                native_tool_calls.append(event.data)
            elif event.type == EventType.STREAM_END:
                full_response = event.data
                if event.metadata and event.metadata.get("usage"):
                    usage = event.metadata["usage"]
                    accumulated_usage.prompt_tokens += usage.prompt_tokens
                    accumulated_usage.completion_tokens += usage.completion_tokens
                    accumulated_usage.total_tokens += usage.total_tokens

        # Determine tool call
        tool_call = None
        if native_tool_calls:
            tc = native_tool_calls[0]
            tool_args = tc.get("arguments", {})
            if isinstance(tool_args, dict) and "tool" in tool_args and "arguments" in tool_args:
                tool_args = tool_args["arguments"]
            tool_call = {"tool": tc["tool"], "arguments": tool_args}
        else:
            tool_call = parse_tool_call(full_response, ctx.tool_manager.get_tool)

        if tool_call:
            tool_name = tool_call["tool"]
            tool_args = tool_call.get("arguments", {})

            # Check for tool loop
            if ctx.tool_manager.is_tool_loop_detected(tool_name, tool_args):
                yield Event(
                    EventType.INFO,
                    f"Loop detected: '{tool_name}' called {ctx.tool_manager.max_same_tool_calls}x with same args"
                )
                loop_msg = ctx.tool_manager.get_loop_message(tool_name)
                ctx.session.add_message(Message("user", loop_msg))
                continue

            ctx.tool_manager.record_tool_call(tool_name, tool_args)

            yield Event(EventType.TOOL_CALL, {
                "tool": tool_name,
                "arguments": tool_args
            })

            # Execute tool
            try:
                tool_task = asyncio.create_task(
                    ctx.tool_manager.execute_tool(tool_name, **tool_args)
                )

                # Yield consent events while tool runs
                while not tool_task.done():
                    for consent_event in ctx.get_consent_events():
                        yield consent_event
                    await asyncio.sleep(0.05)

                # Drain remaining consent events
                for consent_event in ctx.get_consent_events():
                    yield consent_event

                result = await tool_task

                # Track tool usage for premium search
                if tool_name == "web_search":
                    try:
                        from .tools.builtin import web_premium
                        tool_usage = web_premium.get_last_tool_usage()
                        if tool_usage:
                            ctx.track_tool_usage(tool_name, tool_usage)
                    except Exception:
                        pass

                yield Event(EventType.TOOL_RESULT, {
                    "tool": tool_name,
                    "result": result[:2000] + "..." if len(result) > 2000 else result
                })

                ctx.session.add_message(Message(
                    "assistant",
                    f"I'll use the {tool_name} tool.\n```json\n{json.dumps(tool_call, indent=2)}\n```"
                ))
                ctx.session.add_message(Message(
                    "user",
                    f"The {tool_name} tool returned:\n\n{result}\n\nNow respond to the user based on this result."
                ))

            except Exception as e:
                error_msg = str(e)
                yield Event(EventType.TOOL_ERROR, {
                    "tool": tool_name,
                    "error": error_msg
                })

                ctx.session.add_message(Message(
                    "assistant",
                    f"I'll use the {tool_name} tool.\n```json\n{json.dumps(tool_call, indent=2)}\n```"
                ))
                ctx.session.add_message(Message(
                    "user",
                    f"The {tool_name} tool failed with error: {error_msg}\n\n"
                    "Please provide an answer without using that tool, or try a different approach."
                ))

            continue

        else:
            # No tool call - final response
            # Handle empty responses
            if iteration == 1 and not full_response.strip() and ctx.tool_manager.auto_retry_empty > 0:
                empty_retry_count += 1
                if empty_retry_count <= ctx.tool_manager.auto_retry_empty:
                    yield Event(
                        EventType.INFO,
                        f"Empty response, retrying... ({empty_retry_count}/{ctx.tool_manager.auto_retry_empty})"
                    )
                    ctx.session.add_message(Message(
                        "user",
                        "Please proceed with the task. If you need more information, ask. "
                        "If you can help, please respond."
                    ))
                    continue

            # Handle empty response after tool iterations
            if iteration > 1 and not full_response.strip():
                ctx.session.add_message(Message(
                    "user",
                    "Please provide a summary or answer based on the tool results above. "
                    "Do not call any more tools - just synthesize the information."
                ))

                async for event in ctx.provider.chat(
                    ctx.session.get_messages(), ctx.model, stream=False, tools=None
                ):
                    if event.type == EventType.ERROR:
                        yield event
                        return
                    elif event.type == EventType.STREAM_END:
                        full_response = event.data
                        if event.metadata and event.metadata.get("usage"):
                            usage = event.metadata["usage"]
                            accumulated_usage.prompt_tokens += usage.prompt_tokens
                            accumulated_usage.completion_tokens += usage.completion_tokens
                            accumulated_usage.total_tokens += usage.total_tokens

                full_response = full_response.strip() or "[Tool execution completed but no summary generated]"

                # Remove prompt message from history
                if ctx.session.messages and ctx.session.messages[-1].role == "user":
                    ctx.session.messages.pop()

            ctx.session.add_message(Message("assistant", full_response))

            # Commit agent changes if needed
            commit_hash = ctx.commit_agent_changes_if_needed("Task completed")
            if commit_hash:
                yield Event(EventType.STATUS, f"✓ Changes committed: {commit_hash[:8]}")

            # Calculate final cost
            metadata = None
            if accumulated_usage.total_tokens > 0:
                accumulated_usage.estimated_cost = calculate_cost(
                    accumulated_usage.prompt_tokens,
                    accumulated_usage.completion_tokens,
                    ctx.model,
                    ctx.provider_name
                )
                ctx.session.update_usage(accumulated_usage, ctx.provider_name, ctx.model)
                metadata = {"usage": asdict(accumulated_usage)}

            yield Event(EventType.STREAM_END, full_response, metadata)
            return

    # Max iterations reached
    yield Event(EventType.INFO, "Maximum tool iterations reached")
    ctx.session.add_message(Message(
        "assistant",
        "[Tool iterations limit reached. Please try again with a simpler query.]"
    ))
