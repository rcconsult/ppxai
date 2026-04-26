"""
Main entry point for the ppxai application.
"""

import argparse
import os
import sys
import asyncio
import time
from pathlib import Path

from ..version import __version__

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

from ..commands.attach import build_multimodal_content, collect_context_attachments
from ..commands.factory import CommandFactory
from ..commands.handler import CommandHandler
from ..config import (
    PROVIDERS,
    get_default_provider,
    get_api_key,
    get_auto_restore_mode,
    get_auto_save_interval,
    get_base_url,
    get_provider_config,
    get_tui_config,
    get_tui_theme,
    initialize,
)
from ..engine.completion import complete as engine_complete
from .ui import console, display_welcome, select_model, select_provider
from .ui_components import format_usage_string, render_status_panel
from ..engine.session import SessionManager
from .themes import get_theme
from ..common.logger import get_logger
from ..common.autosave_guard import AutosaveFailureGuard
from .event_handler import TUIEventHandler

logger = get_logger("tui")


def get_status_line(handler, use_themed: bool = True):
    """Generate status line showing current settings.

    All state reads go through handler properties / AppState.
    Only checkpoint_status and usage_display require engine_client
    method calls (not part of AppState — derived data).
    """
    state = handler.engine_client.state
    provider_config = get_provider_config(handler.provider)
    provider_name = provider_config["name"]

    # All core fields from AppState via handler properties
    tools_enabled = handler.tools_enabled
    agent_mode = state.get("agent_mode")

    # Get model display name (use ID if not found)
    model_display = handler.current_model
    for model_info in provider_config.get("models", {}).values():
        if model_info.get("id") == handler.current_model:
            model_display = model_info.get("name", handler.current_model)
            break

    # Checkpoint status — derived data, not in AppState
    checkpoint_str = None
    if agent_mode:
        checkpoint_status = handler.engine_client.get_checkpoint_status()
        if checkpoint_status.get("enabled"):
            last_checkpoint = checkpoint_status.get("last_checkpoint")
            is_valid = checkpoint_status.get("is_valid", True)
            if last_checkpoint:
                checkpoint_str = "↶!" if not is_valid else "↶"

    # Usage stats — derived data, not in AppState
    usage_str = None
    usage_display = handler.engine_client.session.get_usage_for_display(
        current_provider=handler.provider,
        current_model=handler.current_model
    )
    if usage_display:
        prompt_tokens = usage_display.get("prompt_tokens", 0)
        completion_tokens = usage_display.get("completion_tokens", 0)
        cost = usage_display.get("estimated_cost", 0.0)
        label = usage_display.get("label")
        if prompt_tokens > 0 or completion_tokens > 0:
            usage_str = format_usage_string(prompt_tokens, completion_tokens, cost)
            if label:
                usage_str = f"[{label}] {usage_str}"

    if use_themed:
        theme_name = getattr(handler, 'current_theme_name', None) or get_tui_theme()
        theme = get_theme(theme_name)

        tui_config = get_tui_config()
        show_version = tui_config.get("show_version", True)
        show_cwd = tui_config.get("show_cwd", True)
        show_datetime = tui_config.get("show_datetime", False)

        # Working dir and context from AppState
        working_dir = handler.working_dir if show_cwd else None
        context_percent = state.get("context_percentage")

        # Attachments badge (v1.17.4 Phase 1) — union of two sources:
        #   • `pending_files` on the handler — Rich-client-specific staging
        #     for `/attach`, not yet sent. Kept on the handler because the
        #     staging UX differs per client (slash command here, drag-drop
        #     in web, file picker in VSCode) and doesn't need cross-client
        #     sync.
        #   • `state.context_attachments` on AppState — canonical list of
        #     attachments already committed to session.messages, maintained
        #     by EngineClient._refresh_context_attachments. This is the
        #     shared source of truth every client reads; Textual / Web /
        #     VSCode will render from the same field in later phases.
        staged = list(getattr(handler, "pending_files", None) or [])
        in_context = state.get("context_attachments") or []
        # Dedupe by name; staged entries take precedence because they still
        # carry size / path / kind metadata useful for display.
        attachments_by_name: dict = {}
        for entry in in_context:
            attachments_by_name[entry.get("name", "")] = entry
        for entry in staged:
            attachments_by_name[getattr(entry, "name", "")] = entry
        attachments = [v for k, v in attachments_by_name.items() if k] or None

        return render_status_panel(
            provider=provider_name,
            model=model_display,
            tools_enabled=tools_enabled,
            agent_mode=agent_mode,
            usage_str=usage_str,
            checkpoint_str=checkpoint_str,
            theme=theme,
            version=f"v{__version__}" if show_version else None,
            working_dir=working_dir,
            show_datetime=show_datetime,
            context_percent=context_percent,
            pending_files=attachments,
        )

    # Fallback: plain text status line
    tools_status = "[green]ON[/green]" if tools_enabled else "[dim]OFF[/dim]"
    parts = [provider_name, model_display, f"Tools: {tools_status}"]
    if agent_mode:
        parts.append("Agent: [green]ON[/green]")
        if checkpoint_str:
            parts.append(f"[cyan]{checkpoint_str}[/cyan]")
    if usage_str:
        parts.append(f"[cyan]{usage_str}[/cyan]")

    status = "[dim][[/dim]" + "[dim] | [/dim]".join(parts) + "[dim]][/dim]"
    return status


class PPXAICompleter(Completer):
    """Prompt-toolkit adapter for engine.completion.

    Rich TUI delegates ALL autocomplete logic to `engine.completion.complete()`,
    the same function used by Textual TUI (in-process) and by Web + VSCode
    (via `POST /complete`). This class is purely a glue layer that:

    1. Builds the completion context from the active EngineClient
       (working_dir, current_provider, live tool list), and
    2. Maps the engine's stable dict schema to prompt_toolkit Completion
       objects.

    Subcommand tables (/tools, /usage, /checkpoint, /status, /theme),
    `/model` and `/provider` name lookups, path-arg routing, @file refs,
    and @git/@tree/@clipboard/@url context providers are all owned by
    the engine — keeping this class this short is the whole point of the
    v1.17.x autocomplete refactor. Do NOT re-introduce client-side tables.
    """

    def __init__(self, command_handler=None):
        self._command_handler = command_handler

    def _engine_client(self):
        if self._command_handler is None:
            return None
        return getattr(self._command_handler, "engine_client", None)

    def _get_working_dir(self) -> str:
        engine = self._engine_client()
        if engine is not None:
            try:
                wd = engine.get_working_dir()
                if wd:
                    return str(wd)
            except Exception:
                pass
        return os.getcwd()

    def _get_current_provider(self):
        engine = self._engine_client()
        if engine is None:
            return None
        return getattr(engine, "provider_name", None) or None

    def _get_tool_names(self) -> list[tuple[str, str]]:
        engine = self._engine_client()
        if engine is None:
            return []
        tool_manager = getattr(engine, "tool_manager", None)
        if tool_manager is None:
            return []
        try:
            return [
                (t["name"], t.get("description", ""))
                for t in tool_manager.list_tools()
            ]
        except Exception:
            return []

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        items = engine_complete(
            text,
            len(text),
            working_dir=self._get_working_dir(),
            current_provider=self._get_current_provider(),
            tool_names=self._get_tool_names(),
        )
        for item in items:
            yield Completion(
                item["text"],
                start_position=item.get("replace_start", 0),
                display=item.get("display", item["text"]),
                display_meta=item.get("description", ""),
            )


# Note: Environment variables are loaded in config.py


def check_session_recovery() -> tuple[bool, dict | None]:
    """Check if there's a session to recover.

    v1.13.9: Implements session recovery logic based on config.

    Returns:
        Tuple of (should_restore, session_state) where:
        - should_restore: True if we should restore a session
        - session_state: Dict with session info if available
    """
    auto_restore = get_auto_restore_mode()

    # Get last session state — with disk-scan fallback when the pointer
    # file is missing (e.g. it was cleared but saved sessions still exist).
    last_state = SessionManager.get_last_session_state_or_scan()

    # Debug logging for recurring regression tracking (see
    # memory/feedback_session_recovery_ordering.md). If the prompt
    # fails to appear again, these lines in tui-debug.log will show
    # exactly why the early-return triggered.
    logger.debug(
        f"[session-recovery] auto_restore={auto_restore!r}, "
        f"state={'found' if last_state else 'NONE'}"
        + (f", name={last_state.get('name')}, dirty={last_state.get('dirty')}, "
           f"messages={last_state.get('message_count')}, "
           f"recovered_from_disk={last_state.get('recovered_from_disk', False)}"
           if last_state else "")
    )

    if not last_state:
        logger.debug("[session-recovery] → skip: no state file and no sessions on disk")
        return False, None

    session_name = last_state.get("name")
    is_dirty = last_state.get("dirty", False)
    message_count = last_state.get("message_count", 0)
    recovered_from_disk = last_state.get("recovered_from_disk", False)

    # Skip if no messages in last session
    if message_count == 0:
        logger.debug("[session-recovery] → skip: message_count == 0")
        return False, None

    # If session was dirty (crash), always try to recover
    if is_dirty:
        console.print(f"\n[yellow]⚠ Recovering from interrupted session:[/yellow] {session_name}")
        console.print(f"[dim]  {message_count} messages, last provider: {last_state.get('provider', 'unknown')}[/dim]")
        return True, last_state

    # Handle based on auto_restore config
    if auto_restore == "never":
        return False, None

    if auto_restore == "always":
        console.print(f"\n[cyan]↻ Restoring last session:[/cyan] {session_name}")
        console.print(f"[dim]  {message_count} messages[/dim]")
        return True, last_state

    # auto_restore == "prompt" — distinguish a normal pointer find from
    # a disk-scan fallback so the user knows why we're asking.
    if recovered_from_disk:
        console.print(f"\n[yellow]State pointer missing — most recent session on disk:[/yellow] {session_name}")
    else:
        console.print(f"\n[cyan]Last session available:[/cyan] {session_name}")
    console.print(f"[dim]  {message_count} messages, provider: {last_state.get('provider', 'unknown')}[/dim]")

    try:
        response = console.input("[cyan]Restore? (y/n): [/cyan]").strip().lower()
        if response in ('y', 'yes'):
            return True, last_state
    except (KeyboardInterrupt, EOFError):
        console.print()
        pass

    return False, None


def restore_session_to_handler(handler: CommandHandler, session_state: dict) -> bool:
    """Restore a session to the command handler.

    restore_session() updates EngineClient and AppState atomically.
    Handler properties (provider, current_model, working_dir) read
    from AppState, so no manual sync is needed.

    Args:
        handler: CommandHandler to restore to
        session_state: Session state dict from state file

    Returns:
        True if restored successfully
    """
    session_name = session_state.get("name")
    if not session_name:
        return False

    result = handler.engine_client.restore_session(session_name)
    if not result["success"]:
        console.print(f"[red]Failed to load session: {session_name}[/red]")
        return False

    # AppState is already updated by restore_session() — handler.provider
    # and handler.current_model read from state automatically.

    # Sync OS working directory to match restored session
    working_dir = handler.working_dir
    if working_dir and os.path.isdir(working_dir):
        try:
            os.chdir(working_dir)
        except Exception:
            pass

    console.print(f"[green]✓ Session restored:[/green] {session_name} ({result['message_count']} messages)")
    return True


def main():
    """Main application loop."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="ppxai - Terminal UI for AI providers")
    parser.add_argument("--version", "-v", action="version", version=f"ppxai {__version__}")
    parser.parse_args()

    # Initialize configuration system (v1.13.10: explicit initialization).
    # initialize() also restores persisted debug-log state — so the logger
    # is writing to tui-debug.log BEFORE the session-recovery prompt runs.
    initialize()

    # Session recovery check — BEFORE provider/model selection so the user
    # always sees the restore prompt even if they Ctrl+C during selection.
    # If restoring, we skip the selection entirely (the session already has
    # a provider + model).
    should_restore, session_state = check_session_recovery()
    restored = False

    if should_restore and session_state:
        # Recover: use the saved session's provider + model
        provider = session_state.get("provider", get_default_provider())
        provider_config = get_provider_config(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        if api_key:
            current_model = session_state.get("model") or provider_config.get("default_model", "")
            handler = CommandHandler(api_key, current_model, base_url, provider)
            if restore_session_to_handler(handler, session_state):
                provider = handler.provider
                current_model = handler.current_model
                restored = True
                console.print(f"[green]Restored:[/green] {provider_config['name']} / {current_model}")
            else:
                console.print("[yellow]Session restore failed — starting fresh.[/yellow]")

    if not restored:
        # Fresh session — normal provider/model selection flow
        provider = get_default_provider()

        # Allow provider selection at startup if multiple providers configured
        if len(PROVIDERS) > 1:
            console.print("\n[bold cyan]Available Providers:[/bold cyan]")
            for key, config in PROVIDERS.items():
                api_key_env = config["api_key_env"]
                has_key = bool(os.getenv(api_key_env))
                status = "[green]configured[/green]" if has_key else "[yellow]not configured[/yellow]"
                console.print(f"  - {key}: {config['name']} ({status})")

            # Check if user wants to change provider
            if os.getenv("MODEL_PROVIDER"):
                console.print(f"\n[dim]Using provider from MODEL_PROVIDER env: {provider}[/dim]")
            else:
                provider = select_provider()

        # Get provider configuration
        provider_config = get_provider_config(provider)
        api_key = get_api_key(provider)
        base_url = get_base_url(provider)

        if not api_key:
            api_key_env = provider_config["api_key_env"]
            console.print(f"[red]Error: {api_key_env} not found in environment variables.[/red]")
            console.print("[yellow]Please create a .env file with your API key (see .env.example)[/yellow]")
            sys.exit(1)

        console.print(f"\n[green]Connected to:[/green] {provider_config['name']} ({base_url})")

        # Display welcome
        display_welcome()

        # Select initial model (from provider's available models)
        current_model = select_model(provider)

        # Create command handler with provider info (no legacy client)
        handler = CommandHandler(api_key, current_model, base_url, provider)

    # Create prompt session with history and completer
    # Pre-populate history from restored session
    history = InMemoryHistory()
    for cmd in handler.engine_client.session.command_history:
        history.append_string(cmd)

    completer = PPXAICompleter(command_handler=handler)
    session = PromptSession(
        history=history,
        completer=completer,
        complete_while_typing=True,
        auto_suggest=AutoSuggestFromHistory(),
    )

    # Main loop
    console.print("\n[bold green]Ready to chat! Type your message or /help for commands.[/bold green]")
    console.print("[dim]Tab: autocomplete • @file: reference files • ↑/↓: history • Ctrl-C twice to exit[/dim]\n")
    console.print(f"[dim]Session: {handler.engine_client.session.session_name}[/dim]\n")

    # Track Ctrl-C presses for double-press to exit
    ctrl_c_count = 0
    ctrl_c_timestamp = 0
    ctrl_c_timeout = 2.0  # seconds

    # v1.18.0 Phase 5f: tell the user when auto-save has been failing
    # silently. Guard returns True exactly once per failure streak so
    # we don't spam; resets on the first success.
    autosave_guard = AutosaveFailureGuard()

    while True:
        try:
            # Reset Ctrl-C counter if timeout elapsed
            if ctrl_c_count > 0 and time.time() - ctrl_c_timestamp > ctrl_c_timeout:
                ctrl_c_count = 0

            # Display status line (v1.12.0: uses handler only)
            status_line = get_status_line(handler)
            console.print(status_line)

            # Get user input with history and completion support
            user_input = session.prompt("You: ").strip()

            # Reset Ctrl-C counter on successful input
            ctrl_c_count = 0

            if not user_input:
                continue

            # Add to command history
            handler.engine_client.session.add_to_history(user_input)

            # Handle commands
            if user_input.startswith("/"):
                should_exit = handler.handle_command(user_input)
                if should_exit:
                    break
                # Update current_model from handler (no legacy client)
                current_model = handler.current_model
                continue

            # Log user input
            if user_input.startswith('/'):
                logger.log_command(user_input)
            else:
                logger.log_user_message(user_input)

            # Send message to API
            # ALWAYS use EngineClient (created at startup)
            # This ensures @git/@tree/@file context injection always works
            if handler.engine_client:
                # v1.17.4 Phase 1: if /attach staged any files, build a
                # multimodal content list (text + image_url parts) and pass
                # that instead of the plain string. EngineClient.chat()
                # accepts either format. Pending files are cleared after
                # the chat send completes, whether or not it succeeds —
                # otherwise a failed send leaves orphaned attachments that
                # would be auto-included in the *next* turn.
                pending_files = list(getattr(handler, "pending_files", []) or [])
                if pending_files:
                    # v1.17.4 Phase 2.2: pass live model + provider +
                    # file_store so `build_multimodal_content` can route
                    # each file through `preprocess_file` with the
                    # correct vision routing and persistence context.
                    # Model / provider may have changed since /attach was
                    # run, which is why the routing decision happens here
                    # rather than at attach time.
                    #
                    # Phase 2.7: when a VL sidecar is configured and the
                    # current model is text-only, `preprocess_file` calls
                    # `engine.caption_image` to generate a text caption
                    # instead of dropping the image to a placeholder.
                    # `has_vision_sidecar()` returns False when the sidecar
                    # is disabled or unconfigured, so we pass None in
                    # that case and the placeholder fallback kicks in.
                    vl_captioner = (
                        handler.engine_client.caption_image
                        if handler.engine_client.has_vision_sidecar()
                        else None
                    )
                    chat_payload = build_multimodal_content(
                        user_input,
                        pending_files,
                        model=handler.current_model,
                        provider=handler.provider,
                        file_store=handler.engine_client.file_store,
                        vl_captioner=vl_captioner,
                    )
                    logger.info(
                        f"Sending multimodal message: {len(pending_files)} attachment(s), "
                        f"{len(chat_payload)} content part(s)"
                    )
                else:
                    chat_payload = user_input

                # Use engine with event-based streaming
                # EngineClient handles all context injection (@file, @git, @tree) internally
                async def stream_engine_response():
                    """Stream response from EngineClient using shared TUIEventHandler."""
                    # Create TUI-specific event handler with verbose setting, theme, and emoji mode
                    verbose = handler.tools_verbose  # reads from AppState
                    theme_name = getattr(handler, 'current_theme_name', None)
                    emoji_mode = getattr(handler, 'emoji_mode', False)
                    event_handler = TUIEventHandler(
                        console, logger,
                        verbose=verbose,
                        theme_name=theme_name,
                        emoji_mode=emoji_mode,
                        engine_client=handler.engine_client
                    )

                    # Process events using shared handler
                    # chat_payload is either the raw user_input (context
                    # injection still runs) or a multimodal content list
                    # when attachments are present.
                    async for event in handler.engine_client.chat(chat_payload, stream=True):
                        should_continue = await event_handler.handle_event(event)
                        if not should_continue:
                            break

                    return event_handler.get_response()

                try:
                    response = asyncio.run(stream_engine_response())
                finally:
                    # Always drop pending attachments after the send attempt,
                    # so the next turn starts clean even on error/interrupt.
                    if pending_files and hasattr(handler, "pending_files"):
                        handler.pending_files.clear()

            # Update session metadata (v1.12.0: use engine session as source of truth)
            if response and handler.engine_client:
                message_count = len(handler.engine_client.session.messages)

                # Auto-save session based on config interval (dirty save for recovery)
                save_interval = get_auto_save_interval()
                if message_count > 0 and (save_interval == 0 or message_count % max(1, save_interval) == 0):
                    try:
                        handler.engine_client.session.save_dirty()
                        autosave_guard.on_success()
                    except Exception as e:
                        logger.warning(f"Auto-save failed: {e}")
                        # v1.18.0 Phase 5f: tell the user after the
                        # threshold so a run with a full disk or
                        # revoked permissions doesn't silently lose
                        # every turn's save for the rest of the run.
                        if autosave_guard.on_failure(e):
                            console.print(
                                f"[yellow]⚠ Auto-save has failed "
                                f"{autosave_guard.consecutive_failures} times in a row "
                                f"({e}). Check disk space and permissions; "
                                f"use /save to force a save to a specific path.[/yellow]"
                            )

        except KeyboardInterrupt:
            # Implement double Ctrl-C to exit
            ctrl_c_count += 1
            ctrl_c_timestamp = time.time()

            if ctrl_c_count == 1:
                # First Ctrl-C: Show warning with options
                console.print("\n[yellow]⚠ Activity interrupted![/yellow]")
                console.print("[yellow]  • Press Ctrl-C again to exit[/yellow]")
                console.print("[yellow]  • Or continue typing to resume[/yellow]\n")

                # Cleanup conversation history if interrupted during streaming.
                # v1.18.0 Phase 3: read last role from AppState instead of
                # scanning session.messages — the engine maintains
                # last_message_role via session.on_messages_changed.
                # v1.18.2: also fire validate_and_fix_alternation() to clean
                # any orphan assistant.tool_calls left behind when
                # KeyboardInterrupt fired between chat.py adding the assistant
                # message and the tool result loop. Without this, the next
                # turn's request to OpenAI rejects with a 400 referencing the
                # missing tool_call_ids.
                cleaned = False
                if handler.engine_client:
                    last_role = handler.engine_client.state.get("last_message_role")
                    if last_role == "user":
                        handler.engine_client.session.remove_last_message()
                        cleaned = True
                    fixed = handler.engine_client.session.validate_and_fix_alternation()
                    if fixed > 0:
                        cleaned = True
                if cleaned:
                    console.print("[dim]Conversation history cleaned up. Message chain is in a sane state.[/dim]\n")
            else:
                # Second Ctrl-C: Exit gracefully
                console.print("\n[yellow]Exiting gracefully...[/yellow]")
                # Mark session clean on graceful exit
                try:
                    handler.engine_client.session.mark_clean()
                except Exception:
                    pass
                break

            continue

        except EOFError:
            console.print("\n[yellow]Goodbye![/yellow]")
            # Mark session clean on graceful exit
            try:
                handler.engine_client.session.mark_clean()
            except Exception:
                pass
            break

        except Exception as e:
            console.print(f"\n[red]Unexpected error: {str(e)}[/red]\n")
            continue


if __name__ == "__main__":
    main()
