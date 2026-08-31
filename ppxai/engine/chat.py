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
import time
from dataclasses import asdict
from pathlib import Path
from typing import AsyncIterator, Dict, Any, List, Optional, Protocol, Callable

from .types import AgentBeatState, Event, EventType, Message, UsageStats
from .session import SessionManager, sanitize_outbound
from .tools.manager import ToolManager
from .tools.builtin import web_premium
from .tools.parser import parse_tool_call, detect_truncated_tool_call, strip_tool_json_from_text
from .tools.validator import ResponseValidator, ValidationResult, check_session_pollution
from .model_facts import shipped_facts_for_model
from .providers.base import BaseProvider
from ..config import get_system_prompt, get_system_prompt_mode, calculate_cost
from ..common.logger import get_logger
from ..config.defaults import DEFAULT_AGENT_ZOMBIE_THRESHOLD
from ..config import get_agent_config

logger = get_logger("chat")


# Empty-response repair (Item 44, v1.19.1).
#
# When a provider streams back nothing, the chat loops nudge the model with a
# synthetic user turn and retry. Two invariants must hold when that nudge is
# involved, or history is corrupted for the NEXT turn:
#   1. The synthetic nudge is transient — it is repair machinery, not something
#      the user said. It must be rolled back once we stop retrying, exactly as
#      the tool-loop's iteration>1 empty path already does. Leaving it persisted
#      silently rewrites the conversation.
#   2. We never persist an empty-content assistant turn. Current Perplexity Sonar
#      rejects a resent empty assistant with invalid_message 400, and it carries
#      no value regardless. Coalesce to a visible sentinel so history stays
#      strictly alternating and always sendable.
# `finalize_empty_response` centralizes both so every empty-exhaustion path
# behaves identically instead of each open-coding (and drifting from) the rule.
EMPTY_RESPONSE_NUDGE = (
    "Please proceed with the task. If you need more information, ask. "
    "If you can help, please respond."
)

EMPTY_RESPONSE_SENTINEL = "[No response generated]"


def finalize_empty_response(ctx: "ChatContext", full_response: str) -> str:
    """Roll back a transient empty-response nudge and coalesce empty content.

    Called on the terminal (non-retrying) branch of an empty-response path.

    * If ``full_response`` has real content, returns it unchanged and touches
      nothing — the normal case.
    * If it is empty, the immediately-preceding turn is the synthetic
      ``EMPTY_RESPONSE_NUDGE`` this loop appended before its last retry. That
      nudge is repair machinery, not user input, so it is removed via
      ``remove_last_message`` (which keeps message-count, multimodal cache, and
      the AppState callback consistent — never pop ``messages`` directly). The
      returned text is coalesced to ``EMPTY_RESPONSE_SENTINEL`` so the caller
      persists a visible, sendable assistant turn instead of empty content.

    Returns the text the caller should persist as the assistant message.
    """
    if full_response.strip():
        return full_response

    # Roll back the transient nudge if it is the current tail. Guard on the
    # exact nudge text so we never remove a genuine trailing user turn.
    tail = ctx.session.messages[-1] if ctx.session.messages else None
    if (
        tail is not None
        and tail.role == "user"
        and tail.text_content().strip() == EMPTY_RESPONSE_NUDGE
    ):
        ctx.session.remove_last_message()

    return EMPTY_RESPONSE_SENTINEL


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

    @property
    def system_prompt_override(self) -> Optional[str]:
        """Per-engine system-prompt override (v1.19.x). When non-None, it
        REPLACES the config system prompt for this run (the v1 agent tier
        uses it for bounded-agent framing). None = use config."""
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

    def get_working_dir(self) -> Optional[str]:
        """Get current working directory (v1.15.2)."""
        ...


# Tool categories used by the success heuristic. Module-level so
# `_compute_tool_success` is import-cheap and unit-testable.
_READ_ONLY_TOOLS = frozenset({
    'read_file', 'display_file', 'list_directory',
    'search_files', 'get_working_directory',
})
_SHELL_TOOLS = frozenset({'execute_shell_command', 'execute_command'})


def _compute_tool_success(tool_name: str, result: str) -> bool:
    """Classify a tool call as success or failure for validator bookkeeping.

    The classification is feed-stock for `ResponseValidator`'s
    `claim_contradicts_result` warning and for the agent zombie-loop
    circuit-breaker. False positives here cause spurious warnings to
    the user; false negatives mask real errors.

    Heuristics differ per tool category:

    - Read-only tools (read_file, etc.): success unless the result
      begins with `Error:` — read_file results ARE file content, so
      substring-matching on error keywords inside the file would flag
      source code as broken.

    - Shell tools (execute_shell_command, execute_command): the tool
      formats its output as `[cwd: <dir>]\\n...` on success and
      `[cwd: <dir>, exit: <N>]\\n...` on non-zero exit. The bracketed
      exit code is the authoritative signal. v1.18.7 fix: previously
      this branch substring-matched on 'failed' / 'error:' in the
      output, which flagged benign stderr noise (e.g. LibreOffice's
      "Warning: failed to read path from javaldx") as a real error
      and triggered false `claim_contradicts_result` warnings on
      successful conversions.

    - Everything else (write tools, native pdf/pptx/excel/docx tools,
      web tools, …): substring-match a small set of error indicators.
      Imperfect but covers the common failure modes for tools whose
      output format we don't control.
    """
    if tool_name in _READ_ONLY_TOOLS:
        return not result.startswith(('Error:', 'Error '))

    if tool_name in _SHELL_TOOLS:
        if not result.startswith("[cwd:"):
            # Output didn't go through the wrapper — fall back to the
            # generic heuristic so wrapper-bypassing custom shells
            # still get classified.
            return not any(
                ind in result.lower()
                for ind in ('error:', 'not found', 'failed',
                            'does not exist', 'permission denied')
            )
        header = result.split("]", 1)[0]
        # Success: "[cwd: X" with no ", exit: N" inside the header.
        return ", exit:" not in header

    return not any(
        ind in result.lower()
        for ind in ('error:', 'not found', 'failed',
                    'does not exist', 'permission denied')
    )


def _get_zombie_threshold(ctx: ChatContext) -> int:
    """Read the P0 (v1.18.0) circuit-breaker threshold from agent config.

    Returns the integer zombie_threshold — override via
    `tools.agent.zombie_threshold` in ppxai-config.json. 0 disables
    zombie detection entirely. Failures are swallowed and return the
    default; zombie detection is a safety net, not a hard contract —
    if config resolution breaks at runtime we fall back to the default
    rather than crashing the tool loop.

    The fallback is `DEFAULT_AGENT_ZOMBIE_THRESHOLD`, not a literal: a
    duplicated default silently diverges the day the constant changes.
    """

    try:
        return int(
            get_agent_config().get(
                "zombie_threshold", DEFAULT_AGENT_ZOMBIE_THRESHOLD
            )
        )
    except Exception:
        return DEFAULT_AGENT_ZOMBIE_THRESHOLD


def _get_bootstrap_tool_calling(ctx: ChatContext, model: str) -> dict:
    """Extract tool_calling overrides from bootstrap context for a model.

    Args:
        ctx: Chat context (accesses bootstrap via get_bootstrap_prompt side)
        model: Model ID to match against glob patterns

    Returns:
        Dict of tool_calling overrides, or empty dict
    """
    try:
        # Access the engine client's bootstrap context through the protocol
        # EngineClient stores _bootstrap_context; we access via attribute
        bootstrap = getattr(ctx, "_bootstrap_context", None)
        if bootstrap is None:
            return {}
        return bootstrap.get_tool_calling_overrides(model)
    except (AttributeError, TypeError):
        return {}


def _bump_live_run_tokens(ctx: ChatContext, delta: int) -> None:
    """Add `delta` tokens to the session's live in-flight run total (v1.19.0).

    Kept in lockstep with `accumulated_usage.total_tokens` so the agent-platform
    token budget can read a truthful running total at each tool-loop boundary —
    `ctx.session.usage` is only committed at terminal STREAM_END. Best-effort:
    a session shim without the attribute is silently skipped (never breaks a
    normal chat). See `Session.live_run_tokens`."""
    session = getattr(ctx, "session", None)
    if session is None:
        return
    try:
        session.live_run_tokens = getattr(session, "live_run_tokens", 0) + (delta or 0)
    except AttributeError:
        pass


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
    # Pre-flight: fix alternation violations in history before sending to
    # provider. preserve_trailing_user() detaches the just-typed user turn so
    # the fix doesn't strip it, then restores it; the fix itself fires the
    # AppState change notification.
    with ctx.session.preserve_trailing_user():
        preflight_fixed = ctx.session.validate_and_fix_alternation()
    if preflight_fixed:
        logger.info(f"Pre-flight alternation fix: removed {preflight_fixed} messages")

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

            if event.type in (EventType.ERROR, EventType.PROVIDER_THROTTLED):
                removed = ctx.session.remove_last_message()
                logger.info(
                    f"Error rollback (simple): event={event.type.value}, "
                    f"removed={removed}, messages_left={len(ctx.session.messages)}"
                )
                yield event
                return
            elif event.type == EventType.STREAM_END:
                full_response = event.data or ""
                response_metadata = event.metadata
            elif event.type == EventType.STREAM_START:
                yield event
            elif event.type == EventType.STREAM_CHUNK:
                yield event

        # Check for empty response and retry
        if not full_response.strip() and retry_count < max_retries and max_retries > 0:
            retry_count += 1
            yield Event(EventType.INFO, f"Empty response, retrying... ({retry_count}/{max_retries})")
            ctx.session.add_message(Message("user", EMPTY_RESPONSE_NUDGE))
            continue  # Retry

        # Retries exhausted (or disabled). If still empty, roll back the
        # transient nudge and coalesce to a sentinel so we never persist an
        # unsendable empty assistant turn (Item 44, v1.19.1).
        full_response = finalize_empty_response(ctx, full_response)

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


def _build_prompt_based_messages(ctx: ChatContext) -> List[Message]:
    """Build message list with tool descriptions injected into system prompt.

    Assembles: bootstrap prompt + system prompt + tool prompt into a single
    system message, prepended to the conversation messages. Used for both
    the primary prompt-based path and native-mode fallback retries.

    Args:
        ctx: Chat context with provider, session, tool_manager, etc.

    Returns:
        Message list with system prompt containing tool descriptions
    """
    messages = ctx.session.get_messages()
    tool_prompt = ctx.tool_manager.get_tools_prompt(working_dir=ctx.get_working_dir())
    if not tool_prompt:
        return messages

    # Add provider-specific guidance
    has_native_search = ctx.provider and (
        ctx.provider.capabilities.citations or ctx.provider.capabilities.web_search
    )
    has_search_tool = ctx.tool_manager.get_tool("web_search") is not None

    # v1.19.x: when a bounded-agent override is active (/v1/agent/task), do NOT
    # encourage native search — that block directly contradicts the agent
    # framing ("use ONLY granted tools, no native fallback") and is the exact
    # cause of the Perplexity native-search substitution on tool-capable runs.
    agent_override_active = bool(getattr(ctx, "system_prompt_override", None))

    if has_native_search and not has_search_tool and not agent_override_active:
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

    # Apply custom system prompt. A per-engine override (v1.19.x agent tier)
    # REPLACES the config system prompt + forces "prepend" so the tool block
    # still follows the agent framing.
    override = getattr(ctx, "system_prompt_override", None)
    if override:
        system_prompt = override
        prompt_mode = "prepend"
    else:
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

    return [Message("system", final_prompt)] + messages


async def _execute_single_tool(
    ctx: ChatContext,
    tool_name: str,
    tool_args: Dict[str, Any],
    validator: 'ResponseValidator',
    iteration: int
) -> tuple:
    """Execute one tool call and collect events.

    Returns:
        (result_text, success, events_to_yield)
        On exception: (error_msg, False, events_to_yield)
    """
    events = []
    try:
        # v1.19.1 F4: per-call usage capture for premium web search. The
        # holder MUST be installed in THIS (parent) context before the tool
        # task is created — the task inherits a context copy, but the holder
        # list is the same object, so the handler's usage lands here and
        # nowhere else. Fixes the concurrent-run misattribution of the old
        # global get_last_tool_usage() reset-on-read channel.
        usage_holder = (
            web_premium.begin_usage_capture() if tool_name == "web_search" else None
        )
        tool_task = asyncio.create_task(
            ctx.tool_manager.execute_tool(tool_name, **tool_args)
        )

        # Wait for tool completion, checking for interrupt.
        # NOTE: Consent events are NOT drained here — they stay in
        # ctx._event_queue for the SSE generator to poll via drain_events()
        # and deliver to the client. Draining them into a local list caused
        # a deadlock: the events were trapped here while the SSE generator
        # never saw them (v1.16.0 fix).
        while not tool_task.done():
            if ctx.is_interrupted:
                tool_task.cancel()
                try:
                    await tool_task
                except asyncio.CancelledError:
                    pass
                return None, False, [Event(EventType.ERROR, "Interrupted by user")]
            await asyncio.sleep(0.05)

        result = await tool_task

        # Determine if tool succeeded based on result content
        tool_success = _compute_tool_success(tool_name, result)

        # Record tool call for validation
        validator.record_tool_call(
            tool_name=tool_name,
            arguments=tool_args,
            result=result,
            success=tool_success,
            iteration=iteration
        )

        # Track tool usage for premium search — read from THIS call's holder
        # (race-free), not the legacy process-global (v1.19.1 F4).
        if tool_name == "web_search" and usage_holder:
            try:
                for tool_usage in usage_holder:
                    ctx.track_tool_usage(tool_name, tool_usage)
            except Exception as e:
                logger.debug(f"Tool usage tracking failed: {e}")

        # Emit DISPLAY_FILE event for display_file tool
        if tool_name == "display_file" and "filepath" in tool_args:
            filepath = tool_args["filepath"]
            try:
                working_dir_str = ctx.get_working_dir() if hasattr(ctx, 'get_working_dir') else None
                working_dir = Path(working_dir_str) if working_dir_str else Path.cwd()
                path = Path(filepath).expanduser()
                if not path.is_absolute():
                    path = working_dir / filepath
                path = path.resolve()

                if path.exists() and path.is_file():
                    logger.debug(f"[display_file] Emitting DISPLAY_FILE event for: {path}")
                    events.append(Event(EventType.DISPLAY_FILE, {
                        "filepath": str(path)
                    }))
                else:
                    logger.debug(f"[display_file] Path validation failed: exists={path.exists()}, is_file={path.is_file() if path.exists() else 'N/A'}")
            except Exception as e:
                logger.debug(f"[display_file] Exception during event emission: {e}")
                pass

        # Truncated result for display
        display_limit = ctx.tool_manager.get_tool_display_limit(tool_name, tool_args)
        truncated_result = result[:display_limit] + "..." if len(result) > display_limit else result

        events.append(Event(EventType.TOOL_RESULT, {
            "tool": tool_name,
            "result": truncated_result
        }))

        return result, tool_success, events

    except Exception as e:
        error_msg = str(e)

        # Record failed tool call for validation
        validator.record_tool_call(
            tool_name=tool_name,
            arguments=tool_args,
            result=f"Error: {error_msg}",
            success=False,
            iteration=iteration
        )

        events.append(Event(EventType.TOOL_ERROR, {
            "tool": tool_name,
            "error": error_msg
        }))

        return f"Error: {error_msg}", False, events


async def chat_with_tools(
    ctx: ChatContext,
    stream: bool
) -> AsyncIterator[Event]:
    """Chat with tool support.

    Supports three profile-driven modes:
    1. Native tool calling: Provider returns TOOL_CALL events
    2. Prompt-based: Parse tool calls from model's text response
    3. Auto: Start native, fall back to prompt-based on empty/failure

    Args:
        ctx: Chat context with provider, session, tool_manager, etc.
        stream: Whether to stream the response

    Yields:
        Event objects for tool calls, results, and final response
    """
    iteration = 0
    max_iterations = ctx.tool_manager.max_iterations

    # Per-model facts: shipped row, then operator config (ADR 0012 §2 Q0e).
    # One resolver, one record — replaces `get_effective_profile`, which
    # merged a third vocabulary (AGENTS.md `tool_calling`, retired in Q0f as
    # a parser with zero users) on top of the profile table.
    facts = (
        ctx.provider.get_facts_for_model(ctx.model)
        if ctx.provider
        else shipped_facts_for_model(ctx.model)
    )
    if facts.max_tool_iterations > 0:
        max_iterations = max(max_iterations, facts.max_tool_iterations)

    # Reset tool call history for loop detection
    ctx.tool_manager.reset_tool_history()

    # v1.15.2: Initialize response validator for hallucination detection
    validator = ResponseValidator()

    # Track accumulated usage
    accumulated_usage = UsageStats()

    # v1.19.0: reset the live in-flight token mirror for this run. We bump it in
    # lockstep with accumulated_usage.total_tokens below so the agent-platform
    # token budget can read a truthful running total at each tool-loop boundary
    # (ctx.session.usage is only committed at terminal STREAM_END). Live-only;
    # never persisted. Guarded so a session shim without the attr won't crash.
    if hasattr(ctx, "session") and ctx.session is not None:
        try:
            ctx.session.live_run_tokens = 0
        except AttributeError:
            pass

    # Tool calling mode: ONE lookup (ADR 0012 §2 Q0e).
    #
    # This site was debt Item 43's Layer-2 bug. It asked TWO systems in a
    # fixed order — `profile.tool_calling.mode` first, then
    # `ProviderCapabilities.native_tool_calling` as a gate — so a capability
    # resolving native=True never reached the wire if the profile glob said
    # prompt_based, and a provider-wide capability could speak for a model
    # the profile had measured. `tool_mode` now answers the whole question
    # from the model's own record, and no provider-level statement can
    # reach it, because tool mode is not a field of the provider record.
    use_native_tools = facts.tool_mode != "prompt_based"

    openai_tools = ctx.tool_manager.get_tools_openai_format() if use_native_tools else None

    logger.debug(
        f"Tool mode: tool_mode={facts.tool_mode}, use_native={use_native_tools}, "
        f"fallback_empty={facts.fallback_on_empty}, fallback_fail={facts.fallback_on_failure}"
    )

    # Debug: log session state at start of chat_with_tools
    logger.debug(
        f"chat_with_tools start: messages={len(ctx.session.messages)}, "
        f"roles={[m.role for m in ctx.session.messages[-5:]]}"  # Last 5 message roles
    )

    # Pre-flight: fix alternation violations in history before sending to
    # provider. preserve_trailing_user() detaches the just-typed user turn so
    # the fix doesn't strip it, then restores it; the fix itself fires the
    # AppState change notification.
    with ctx.session.preserve_trailing_user():
        preflight_fixed = ctx.session.validate_and_fix_alternation()
    if preflight_fixed:
        logger.info(f"Pre-flight alternation fix: removed {preflight_fixed} messages")

    yield Event(EventType.STREAM_START, {"model": ctx.model})

    # P0 (v1.18.0) — agent heartbeat primitives. `beat` tracks per-
    # iteration state; AGENT_RUN_START fires once so clients can reset
    # their progress widgets, AGENT_BEAT fires at the end of every
    # iteration with structured state, AGENT_RUN_ERROR fires alongside
    # each ERROR yield so consumers see a terminal lifecycle event.
    beat = AgentBeatState(start_time=time.monotonic())
    yield Event(EventType.AGENT_RUN_START, {
        "model": ctx.model,
        "provider": ctx.provider_name,
        "max_iterations": max_iterations,
        "agent_mode": bool(getattr(ctx, "agent_mode", False)),
    })

    empty_retry_count = 0
    consecutive_truncation_retries = 0
    MAX_TRUNCATION_RETRIES = 3

    # Track the last tool name for progress display
    last_tool_name = ""

    # Fix: ensure session.tools_enabled reflects actual tool usage (v1.17.4).
    # This was None in session metadata when tools were enabled via native
    # provider path rather than explicit /tools enable.
    ctx.session.tools_enabled = True

    while iteration < max_iterations:
        if ctx.is_interrupted:
            yield Event(EventType.ERROR, "Interrupted by user")
            yield Event(EventType.AGENT_RUN_ERROR, {
                "reason": "interrupted",
                "iteration": iteration,
                "elapsed_s": round(beat.elapsed_s, 1),
            })
            return

        iteration += 1

        if iteration > 1:
            # Show which tool just completed so the user has breadcrumbs
            # during long tool chains instead of 20+ seconds of silence.
            if last_tool_name:
                yield Event(EventType.INFO, f"Step {iteration}: processing {last_tool_name} result...")
            else:
                yield Event(EventType.INFO, f"Processing... (step {iteration})")

        messages = ctx.session.get_messages()

        if not use_native_tools:
            # Prompt-based tool calling — build messages with tool descriptions in system prompt
            messages = _build_prompt_based_messages(ctx)
        else:
            # Native tool calling — inject bootstrap prompt (AGENTS.md hints)
            # and belt-and-suspenders tool descriptions for fallback-capable models (B3)
            bootstrap_prompt = ctx.get_bootstrap_prompt()
            # v1.19.x: a per-engine override (agent tier) replaces config.
            _override = getattr(ctx, "system_prompt_override", None)
            system_prompt = _override or get_system_prompt(ctx.provider_name)

            # Belt-and-suspenders: inject tool descriptions into system prompt
            # for models with fallback flags, so prompt-based parsing can work
            # if native tool calling returns empty or fails
            tool_hint = ""
            if facts.fallback_on_empty or facts.fallback_on_failure:
                tool_hint = ctx.tool_manager.get_tools_prompt(working_dir=ctx.get_working_dir())

            parts = [p for p in [bootstrap_prompt, system_prompt, tool_hint] if p]
            if parts:
                final_prompt = "\n\n---\n\n".join(parts)
                messages = [Message("system", final_prompt)] + messages

        # Bug B (v1.19.1): the pre-flight alternation fix runs once BEFORE this
        # loop (line ~643), never per iteration. An orphan assistant.tool_calls
        # created mid-turn — a tool cancelled/interrupted, or the loop-detect
        # user injection below — would otherwise reach a strict provider on
        # iterations 2+ and 400 with "tool_call_ids did not have response".
        # Sanitize the OUTBOUND copy only (orphan tool_calls + empty-content
        # assistant); session state is untouched so an in-flight tool
        # round-trip is never destroyed mid-turn.
        messages, _outbound_stripped = sanitize_outbound(messages)
        if _outbound_stripped:
            logger.info(
                f"Outbound sanitize stripped malformed messages before provider "
                f"call (iteration {iteration}): removed {_outbound_stripped} message(s)"
            )

        # Get response from provider
        full_response = ""
        native_tool_calls = []

        async for event in ctx.provider.chat(messages, ctx.model, stream=False, tools=openai_tools):
            if event.type in (EventType.ERROR, EventType.PROVIDER_THROTTLED):
                # Only remove user message on first iteration (before any tool results added)
                # This prevents session corruption from orphan user messages (v1.14.1)
                if iteration == 1:
                    removed = ctx.session.remove_last_message()
                    logger.info(
                        f"Error rollback: event={event.type.value}, "
                        f"iteration={iteration}, removed={removed}, "
                        f"messages_left={len(ctx.session.messages)}"
                    )
                yield event
                # v1.18.3: PROVIDER_THROTTLED records reason='provider_throttled'
                # so post-mortems / benchmark harnesses can distinguish quota
                # blocks from genuine model failures.
                reason = (
                    "provider_throttled"
                    if event.type == EventType.PROVIDER_THROTTLED
                    else "provider_error"
                )
                yield Event(EventType.AGENT_RUN_ERROR, {
                    "reason": reason,
                    "iteration": iteration,
                    "elapsed_s": round(beat.elapsed_s, 1),
                    "detail": str(event.data) if event.data else "",
                })
                return
            elif event.type == EventType.TOOL_CALL:
                native_tool_calls.append(event.data)
            elif event.type == EventType.STREAM_END:
                full_response = event.data or ""
                if event.metadata and event.metadata.get("usage"):
                    usage = event.metadata["usage"]
                    accumulated_usage.prompt_tokens += usage.prompt_tokens
                    accumulated_usage.completion_tokens += usage.completion_tokens
                    accumulated_usage.total_tokens += usage.total_tokens
                    _bump_live_run_tokens(ctx, usage.total_tokens)

        # Check interrupt after provider returns (stream=False blocks until complete)
        if ctx.is_interrupted:
            yield Event(EventType.ERROR, "Interrupted by user")
            yield Event(EventType.AGENT_RUN_ERROR, {
                "reason": "interrupted",
                "iteration": iteration,
                "elapsed_s": round(beat.elapsed_s, 1),
            })
            return

        # Fallback on empty: native mode returned nothing — retry with prompt-based
        if use_native_tools and facts.fallback_on_empty:
            if not native_tool_calls and not full_response.strip():
                logger.info(f"Native empty response, falling back to prompt-based (model={ctx.model})")
                yield Event(EventType.INFO, "Native tool calling returned empty, retrying with prompt-based...")
                fallback_messages = _build_prompt_based_messages(ctx)
                async for event in ctx.provider.chat(fallback_messages, ctx.model, stream=False, tools=None):
                    if event.type in (EventType.ERROR, EventType.PROVIDER_THROTTLED):
                        yield event
                        return
                    elif event.type == EventType.STREAM_END:
                        full_response = event.data or ""
                        if event.metadata and event.metadata.get("usage"):
                            usage = event.metadata["usage"]
                            accumulated_usage.prompt_tokens += usage.prompt_tokens
                            accumulated_usage.completion_tokens += usage.completion_tokens
                            accumulated_usage.total_tokens += usage.total_tokens
                            _bump_live_run_tokens(ctx, usage.total_tokens)

        # Build list of parsed tool calls
        tool_calls_list = []
        if native_tool_calls:
            parsed_calls = []
            for tc in native_tool_calls:
                tool_args = tc.get("arguments", {})
                if isinstance(tool_args, dict) and "tool" in tool_args and "arguments" in tool_args:
                    tool_args = tool_args["arguments"]
                entry = {
                    "tool": tc["tool"],
                    "arguments": tool_args,
                    "tool_call_id": tc.get("tool_call_id"),
                }
                # Item 45: carry provider-opaque per-call metadata across this
                # rebuild. Gemini 3.x's `thought_signature` must reach the
                # session transcript (and from there the next outbound turn) or
                # the follow-up request 400s. Dropping unknown keys here was
                # why the first fix looked correct at both ends yet still
                # failed live — the value never survived the middle hop.
                if tc.get("thought_signature"):
                    entry["thought_signature"] = tc["thought_signature"]
                parsed_calls.append(entry)

            # Limit to first call unless parallel_tool_calls enabled
            if not facts.parallel_tool_calls:
                parsed_calls = parsed_calls[:1]

            # Fallback on failure: first tool call has unknown tool — try prompt-based parser
            # Must run BEFORE strip_tool_json so the parser can find JSON in response text
            if parsed_calls and not ctx.tool_manager.get_tool(parsed_calls[0]["tool"]):
                if facts.fallback_on_failure:
                    logger.info(f"Native tool call unknown tool '{parsed_calls[0]['tool']}', falling back to prompt-based parser")
                    fallback_call = parse_tool_call(full_response, ctx.tool_manager.get_tool)
                    if fallback_call:
                        parsed_calls = [fallback_call]

            # v1.15.6 Gap 4: Strip duplicated tool call JSON from response text.
            if full_response:
                full_response = strip_tool_json_from_text(full_response)

            tool_calls_list = parsed_calls
        else:
            single = parse_tool_call(full_response, ctx.tool_manager.get_tool)
            if single:
                tool_calls_list = [single]

        # Profile-driven strip_json: strip tool JSON from text even without native calls
        if not native_tool_calls and facts.strip_json_from_text and full_response:
            full_response = strip_tool_json_from_text(full_response)

        if tool_calls_list:
            # R12 Opt 1 (v1.17.5): surface the model's intermediate prose
            # between tool iterations. With stream=False the provider
            # returns the full response as one blob; the engine stripped
            # tool JSON out of `full_response` above, leaving whatever
            # narrative the model emitted ("I'll check the config next…").
            # Without this event the UI goes silent for 5–15 s between
            # tool bubbles even though the model IS talking.
            prose = full_response.strip() if full_response else ""
            if prose:
                yield Event(EventType.AGENT_INTERMEDIATE_PROSE, {
                    "text": prose,
                    "iteration": iteration,
                })

            # v1.16.0: Emit group start for UI noise reduction
            yield Event(EventType.TOOL_GROUP_START, {
                "iteration": iteration,
                "count": len(tool_calls_list)
            })

            # Execute each tool call sequentially, collecting results
            results = []  # list of (tool_call_dict, result_text, success)
            interrupted = False

            for tc in tool_calls_list:
                tool_name = tc["tool"]
                tool_args = tc.get("arguments", {})

                # Check for tool loop (per tool)
                if ctx.tool_manager.is_tool_loop_detected(tool_name, tool_args):
                    yield Event(
                        EventType.INFO,
                        f"Loop detected: '{tool_name}' called {ctx.tool_manager.max_same_tool_calls}x with same args"
                    )
                    loop_msg = ctx.tool_manager.get_loop_message(tool_name)
                    ctx.session.add_message(Message("user", loop_msg))
                    interrupted = True  # Stop processing remaining tools
                    break

                ctx.tool_manager.record_tool_call(tool_name, tool_args)

                yield Event(EventType.TOOL_CALL, {
                    "tool": tool_name,
                    "arguments": tool_args
                })

                result, success, extra_events = await _execute_single_tool(
                    ctx, tool_name, tool_args, validator, iteration
                )
                for ev in extra_events:
                    yield ev

                # Check for interrupt (signaled by None result)
                if result is None:
                    return

                results.append((tc, result, success))
                last_tool_name = tool_name

            if interrupted:
                # v1.16.0: Close group even on interruption
                yield Event(EventType.TOOL_GROUP_END, {
                    "iteration": iteration,
                    "count": len(results),
                    "all_succeeded": False
                })
                continue  # Loop detection fired — go to next iteration

            # Add session messages for all executed tool calls
            if use_native_tools and all(tc.get("tool_call_id") for tc in tool_calls_list if tc in [r[0] for r in results]):
                # One assistant message with ALL tool_calls
                executed_calls = [r[0] for r in results]

                def _native_tool_call(tc: dict) -> dict:
                    """OpenAI-shaped tool_call entry, plus provider extras.

                    v1.19.1 Item 45: Gemini 3.x returns an opaque
                    `thought_signature` per function call and REJECTS the
                    follow-up turn unless it is echoed back. It has to survive
                    this hop — the session transcript is what the next
                    outbound request is rebuilt from — so it rides alongside
                    the standard fields. Providers that never set it are
                    unaffected (the key is simply absent).
                    """
                    entry = {
                        "id": tc["tool_call_id"],
                        "type": "function",
                        "function": {
                            "name": tc["tool"],
                            "arguments": json.dumps(tc.get("arguments", {}))
                        }
                    }
                    if tc.get("thought_signature"):
                        entry["thought_signature"] = tc["thought_signature"]
                    return entry

                ctx.session.add_message(Message(
                    "assistant", "",
                    tool_calls=[_native_tool_call(tc) for tc in executed_calls]
                ))
                # N tool result messages
                for tc, result, success in results:
                    error_suffix = ""
                    if not success and result.startswith("Error:"):
                        error_suffix = (
                            "\n\nPlease provide an answer without using that tool, "
                            "or try a different approach."
                        )
                    ctx.session.add_message(Message(
                        "tool", result + error_suffix,
                        tool_call_id=tc["tool_call_id"]
                    ))
            else:
                # Prompt-based / no tool_call_id — synthetic pairs for each tool
                for tc, result, success in results:
                    tool_name = tc["tool"]
                    if success:
                        ctx.session.add_message(Message(
                            "assistant",
                            f"I'll use the {tool_name} tool.\n```json\n{json.dumps(tc, indent=2)}\n```"
                        ))
                        ctx.session.add_message(Message(
                            "user",
                            f"The {tool_name} tool returned:\n\n{result}\n\nNow respond to the user based on this result."
                        ))
                    else:
                        ctx.session.add_message(Message(
                            "assistant",
                            f"I'll use the {tool_name} tool.\n```json\n{json.dumps(tc, indent=2)}\n```"
                        ))
                        ctx.session.add_message(Message(
                            "user",
                            f"The {tool_name} tool failed with error: {result}\n\n"
                            "Please provide an answer without using that tool, or try a different approach."
                        ))

            # v1.16.0: Emit group end after all tool calls processed
            all_succeeded = all(success for _, _, success in results)
            tool_names = [tc["tool"] for tc, _, _ in results]
            yield Event(EventType.TOOL_GROUP_END, {
                "iteration": iteration,
                "count": len(results),
                "all_succeeded": all_succeeded,
                "tools": tool_names
            })

            # P0 (v1.18.0) — heartbeat tick. Per-iteration structured
            # state for clients to render progress / zombie indicators.
            # Emitted AFTER TOOL_GROUP_END so the beat reflects the
            # iteration that just completed (including its success).
            beat.iteration = iteration
            beat.beat_sequence += 1
            beat.last_beat_time = time.monotonic()
            beat.last_tool = last_tool_name
            if all_succeeded:
                beat.last_run_ok = True
                beat.consecutive_failures = 0
            else:
                beat.last_run_ok = False
                beat.consecutive_failures += 1
            yield Event(EventType.AGENT_BEAT, beat.as_event_data())

            # P0 (v1.18.0) — zombie detection / circuit breaker.
            # Read the threshold from tools.agent config (0 disables).
            # Consecutive failed iterations past the threshold → emit
            # AGENT_ZOMBIE and break the loop. Without this, a model
            # whose apply_patch fails 10× with hallucinated variations
            # burns max_iterations worth of tokens before giving up.
            zombie_threshold = _get_zombie_threshold(ctx)
            if zombie_threshold > 0 and beat.consecutive_failures >= zombie_threshold:
                yield Event(EventType.AGENT_ZOMBIE, {
                    "reason": f"{beat.consecutive_failures} consecutive tool failures",
                    "threshold": zombie_threshold,
                    "last_tool": beat.last_tool,
                    "iteration": iteration,
                    "elapsed_s": round(beat.elapsed_s, 1),
                })
                # Treat as an error-exit — clears AppState.agent_beat
                # via EngineClient interception and gives SRE consumers
                # a terminal lifecycle event.
                yield Event(EventType.AGENT_RUN_ERROR, {
                    "reason": "zombie",
                    "iteration": iteration,
                    "elapsed_s": round(beat.elapsed_s, 1),
                    "detail": (
                        f"Circuit breaker tripped at {zombie_threshold} "
                        f"consecutive failures on tool {beat.last_tool!r}."
                    ),
                })
                # Contract: EVERY chat_with_tools exit yields a final
                # STREAM_END carrying the best available text. Consumers
                # that only collect STREAM_END (the /v1/agent task runner)
                # otherwise see a clean generator end and record an EMPTY
                # result for a run that looked completed (live 2026-07-12:
                # deny-path /task runs finished with chars=0).
                zombie_text = (
                    f"[Agent stopped: circuit breaker tripped at "
                    f"{zombie_threshold} consecutive failures on tool "
                    f"{beat.last_tool!r}.]"
                )
                ctx.session.add_message(Message("assistant", zombie_text))
                yield Event(EventType.STREAM_END, zombie_text)
                return

            continue

        else:
            # No tool call - final response
            # v1.15.2: Check for truncated tool call attempts (GPT-OSS intermittent issue)
            # v1.16.0: Extended with raw JSON detection, stuck-loop escalation, retry cap
            truncated = detect_truncated_tool_call(full_response)
            if truncated and iteration < max_iterations:
                consecutive_truncation_retries += 1
                logger.info(
                    f"Truncated tool call detected (attempt {consecutive_truncation_retries}): "
                    f"{truncated['message']}"
                )

                # Cap: after MAX_TRUNCATION_RETRIES, stop retrying and warn user
                if consecutive_truncation_retries > MAX_TRUNCATION_RETRIES:
                    logger.warning(
                        f"Truncation retry limit reached ({MAX_TRUNCATION_RETRIES}) "
                        f"for tool '{truncated['tool']}'"
                    )
                    yield Event(EventType.WARNING, {
                        "type": "stuck_tool_loop",
                        "severity": "error",
                        "message": (
                            f"Model keeps attempting truncated {truncated['tool']} calls. "
                            f"Try: switch to a model with higher token limits, or manually "
                            f"break the task into smaller steps."
                        ),
                    })
                    consecutive_truncation_retries = 0
                    # Fall through to final response handling below
                else:
                    yield Event(
                        EventType.INFO,
                        f"Truncated tool call: {truncated['reason']} - requesting retry "
                        f"({consecutive_truncation_retries}/{MAX_TRUNCATION_RETRIES})"
                    )

                    # Escalating recovery messages
                    if consecutive_truncation_retries >= 2:
                        # Model is stuck — force a different approach
                        recovery_msg = (
                            f"[SYSTEM: CRITICAL — your tool call for '{truncated['tool']}' has been "
                            f"truncated {consecutive_truncation_retries} times. You MUST use a different approach. "
                            f"Do NOT use {truncated['tool']} for large changes. Instead:\n"
                            f"1. Break the work into multiple smaller tool calls\n"
                            f"2. Edit specific sections rather than rewriting entire files\n"
                            f"3. If you cannot complete the task with tools, respond with your answer in text.]"
                        )
                    else:
                        recovery_msg = (
                            f"[SYSTEM: Your previous response contained a truncated {truncated['tool']} "
                            f"tool call ({truncated['reason']}). The tool was NOT executed. "
                            f"To fix this: break the operation into smaller steps. "
                            f"For apply_patch: use smaller, focused patches instead of rewriting entire files. "
                            f"Do NOT repeat the same large tool call — it will be truncated again.]"
                        )

                    ctx.session.add_message(Message("assistant", full_response[:500] + "..." if len(full_response) > 500 else full_response))
                    ctx.session.add_message(Message("user", recovery_msg))
                    continue

            # Reset truncation counter on successful non-truncated response
            consecutive_truncation_retries = 0

            # Handle empty responses
            if iteration == 1 and not full_response.strip() and ctx.tool_manager.auto_retry_empty > 0:
                empty_retry_count += 1
                if empty_retry_count <= ctx.tool_manager.auto_retry_empty:
                    yield Event(
                        EventType.INFO,
                        f"Empty response, retrying... ({empty_retry_count}/{ctx.tool_manager.auto_retry_empty})"
                    )
                    ctx.session.add_message(Message("user", EMPTY_RESPONSE_NUDGE))
                    continue

            # Handle empty response after tool iterations
            if iteration > 1 and not full_response.strip():
                ctx.session.add_message(Message(
                    "user",
                    "Please provide a summary or answer based on the tool results above. "
                    "Do not call any more tools - just synthesize the information."
                ))

                # Bug B (v1.19.1): outbound sanitize guard (see primary send).
                _retry_messages, _ = sanitize_outbound(ctx.session.get_messages())
                async for event in ctx.provider.chat(
                    _retry_messages, ctx.model, stream=False, tools=None
                ):
                    if event.type in (EventType.ERROR, EventType.PROVIDER_THROTTLED):
                        yield event
                        return
                    elif event.type == EventType.STREAM_END:
                        full_response = event.data or ""
                        if event.metadata and event.metadata.get("usage"):
                            usage = event.metadata["usage"]
                            accumulated_usage.prompt_tokens += usage.prompt_tokens
                            accumulated_usage.completion_tokens += usage.completion_tokens
                            accumulated_usage.total_tokens += usage.total_tokens
                            _bump_live_run_tokens(ctx, usage.total_tokens)

                full_response = full_response.strip() or "[Tool execution completed but no summary generated]"

                # Remove prompt message from history (routes through
                # remove_last_message so the message-count, multimodal cache,
                # and AppState callback stay consistent).
                if ctx.session.messages and ctx.session.messages[-1].role == "user":
                    ctx.session.remove_last_message()

            # iteration==1 exhausted-nudge path (Item 44, v1.19.1): if we fell
            # through still empty, roll back the transient nudge and coalesce to
            # a sentinel so we never persist an unsendable empty assistant. A
            # no-op when full_response already has content (normal turns and the
            # iteration>1 path above, which coalesced + rolled back its own
            # prompt already).
            full_response = finalize_empty_response(ctx, full_response)

            ctx.session.add_message(Message("assistant", full_response))

            # v1.15.2: Validate response against tool results to detect hallucinations
            warnings = validator.validate_response(full_response)
            for warning in warnings:
                logger.warning(
                    f"Response validation warning: {warning.result.value} - {warning.message}"
                )
                yield Event(EventType.WARNING, {
                    "type": warning.result.value,
                    "severity": warning.severity,
                    "message": warning.message,
                    "details": warning.details,
                    "suggested_action": warning.suggested_action
                })

            # B7: Check for session pollution (response too similar to previous model's output)
            if iteration == 1 and full_response:
                recent_assistant = [
                    m.text_content() for m in ctx.session.messages[-10:]
                    if m.role == "assistant" and m.text_content() and m != ctx.session.messages[-1]
                ]
                pollution_warning = check_session_pollution(full_response, recent_assistant)
                if pollution_warning:
                    logger.warning(
                        f"Session pollution detected: {pollution_warning.message}"
                    )
                    yield Event(EventType.WARNING, {
                        "type": pollution_warning.result.value,
                        "severity": pollution_warning.severity,
                        "message": pollution_warning.message,
                        "details": pollution_warning.details,
                        "suggested_action": pollution_warning.suggested_action,
                    })

            # Commit agent changes if needed
            commit_hash = ctx.commit_agent_changes_if_needed("Task completed")
            if commit_hash:
                yield Event(EventType.STATUS, f"✓ Changes committed: {commit_hash[:8]}")

            # Signal agent task completion (v1.16.0)
            # Enables clients to show undo badge, update status, etc.
            if ctx.agent_mode:
                yield Event(EventType.AGENT_COMPLETE, {
                    "iterations": iteration,
                    "commit": commit_hash[:8] if commit_hash else None,
                })

            # P0 (v1.18.0): mode-agnostic run-completion event. Unlike
            # AGENT_COMPLETE above (agent_mode-only), AGENT_RUN_COMPLETE
            # always fires — consumers clearing AppState.agent_beat
            # depend on this.
            yield Event(EventType.AGENT_RUN_COMPLETE, {
                "iterations": iteration,
                "elapsed_s": round(beat.elapsed_s, 1),
            })

            # Transfer tool usage from context to accumulated_usage (v1.16.0)
            if hasattr(ctx, '_current_tool_usage') and ctx._current_tool_usage:
                for t_name, t_usage in ctx._current_tool_usage.items():
                    if t_name not in accumulated_usage.tool_calls:
                        accumulated_usage.tool_calls[t_name] = t_usage
                    else:
                        existing = accumulated_usage.tool_calls[t_name]
                        existing.call_count += t_usage.call_count
                        existing.tokens_in += t_usage.tokens_in
                        existing.tokens_out += t_usage.tokens_out
                        existing.estimated_cost += t_usage.estimated_cost

            # Calculate final cost
            metadata = None
            if accumulated_usage.total_tokens > 0 or accumulated_usage.tool_calls:
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

    # Max iterations reached — still persist usage collected so far (v1.16.0)
    if hasattr(ctx, '_current_tool_usage') and ctx._current_tool_usage:
        for t_name, t_usage in ctx._current_tool_usage.items():
            if t_name not in accumulated_usage.tool_calls:
                accumulated_usage.tool_calls[t_name] = t_usage
            else:
                existing = accumulated_usage.tool_calls[t_name]
                existing.call_count += t_usage.call_count
                existing.tokens_in += t_usage.tokens_in
                existing.tokens_out += t_usage.tokens_out
                existing.estimated_cost += t_usage.estimated_cost

    if accumulated_usage.total_tokens > 0 or accumulated_usage.tool_calls:
        accumulated_usage.estimated_cost = calculate_cost(
            accumulated_usage.prompt_tokens,
            accumulated_usage.completion_tokens,
            ctx.model,
            ctx.provider_name
        )
        ctx.session.update_usage(accumulated_usage, ctx.provider_name, ctx.model)

    yield Event(EventType.INFO, "Maximum tool iterations reached")

    # Commit any pending agent changes before signaling completion
    commit_hash = ctx.commit_agent_changes_if_needed("Max iterations reached")
    if commit_hash:
        yield Event(EventType.STATUS, f"✓ Changes committed: {commit_hash[:8]}")

    # Signal agent task completion even on max iterations (v1.16.0)
    if ctx.agent_mode:
        yield Event(EventType.AGENT_COMPLETE, {
            "iterations": max_iterations,
            "commit": commit_hash[:8] if commit_hash else None,
            "max_iterations_reached": True,
        })

    # P0 (v1.18.0): mode-agnostic run-completion event. Fires here so
    # AppState.agent_beat gets cleared even when the run hit the
    # iteration ceiling (not a success, not an error — a controlled
    # stop).
    yield Event(EventType.AGENT_RUN_COMPLETE, {
        "iterations": max_iterations,
        "elapsed_s": round(beat.elapsed_s, 1),
        "max_iterations_reached": True,
    })

    ctx.session.add_message(Message(
        "assistant",
        "[Tool iterations limit reached. Please try again with a simpler query.]"
    ))
    # Contract: EVERY chat_with_tools exit yields a final STREAM_END (see the
    # zombie exit above). Without this, a run that burned its iteration budget
    # ended with an EMPTY result instead of saying why.
    yield Event(
        EventType.STREAM_END,
        "[Tool iterations limit reached. Please try again with a simpler query.]",
    )
