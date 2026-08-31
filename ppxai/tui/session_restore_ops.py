"""
Session restoration operations for the Textual TUI.

Extracted from `tui/app.py::PPXAIDEApp` (Item 1 narrowing, v1.18.2)
to mirror the `engine/session_ops.py` decomposition that worked for
the engine layer. The TUI facade was the only major facade in the
layered architecture that hadn't undergone the ops-decomposition
pattern (engine 1058 + 6 ops modules; server 411 + 17 routes;
config 262 + 6 submodules); this is the same shape applied to TUI.

Functions take the `PPXAIDEApp` reference as the first parameter so
they retain access to the Textual app context — `push_screen_wait`
for modal dialogs, `_log` for app-scoped logging, instance widgets
like `_chat_view` / `_status_bar` / `_input_box`, and the
auto-save / sub-title attributes that belong to the Textual `App`
inheritance.

The functions are deliberately NOT pure — they mutate the app's
state (working dir, badges, sub-title) and depend on the app's
modal-dialog system. Pure-function shape would require routing
those interactions through callbacks, which is more ceremony than
the call sites justify.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from ppxai.config import get_auto_restore_mode, get_tui_config
from ppxai.engine.session import SessionManager
from ppxai.tui.widgets.dialog import ConsentDialog

if TYPE_CHECKING:
    from ppxai.tui.app import PPXAIDEApp


async def check_session_restoration(app: "PPXAIDEApp") -> None:
    """Check for last session and offer to restore (Phase 7).

    Shows interactive modal dialog if `auto_restore` config is "prompt".
    Auto-restores if config says "always". Skips silently if "never"
    or if there's nothing to restore. Crash-recovery (dirty session)
    always prompts regardless of auto_restore mode — recovering from
    an interrupt is higher-priority than the user's normal preference.
    """
    app._log.info("_check_session_restoration() called")
    try:
        if not app._engine_client:
            app._log.debug("No engine client, skipping session restoration")
            return

        # Get last session state — with disk-scan fallback for cases
        # where the pointer is missing but saved sessions still exist.
        last_state = SessionManager.get_last_session_state_or_scan()
        if not last_state:
            app._log.debug("No last session state found (pointer missing and no sessions on disk)")
            return

        session_name = last_state.get("name")
        message_count = last_state.get("message_count", 0)
        recovered_from_disk = last_state.get("recovered_from_disk", False)

        app._log.info(
            f"Found last session: {session_name} with {message_count} messages"
            + (" (recovered from disk — state pointer was missing)" if recovered_from_disk else "")
        )

        if message_count == 0:
            app._log.debug("Skipping session with 0 messages")
            return

        chat_view = app._chat_view
        provider_info = last_state.get("provider", "unknown")
        tools_info = "ON" if last_state.get("tools_enabled") else "OFF"

        # Check if session file actually exists before showing any dialog.
        # v1.18.8: accept BOTH formats (flat `<name>.json` AND multimodal
        # `<name>/session.json`) via the shared helper — the flat-only check
        # here treated every saved multimodal session as missing and cleared
        # the restore pointer.
        if not SessionManager.session_file_exists(session_name):
            app._log.warning(f"Session file missing for '{session_name}', clearing stale state")
            SessionManager.clear_state_file()
            return

        # Phase 2.2: dirty session = crash recovery. Always prompt.
        is_dirty = last_state.get("dirty", False)
        if is_dirty:
            app._log.info(f"Detected dirty session (crash): {session_name}")
            app._log.info("Showing crash recovery dialog...")
            try:
                response = await app.push_screen_wait(
                    ConsentDialog(
                        title="⚠ Session Recovery",
                        message="ppxaide was interrupted during last session",
                        question=f"Recover session '{session_name}'?\n{message_count} messages, Provider: {provider_info}, Tools: {tools_info}",
                        options=["Yes", "No"],
                    )
                )
                app._log.info(f"Dialog response: {response!r}")
            except Exception as e:
                app._log.error(f"Dialog error: {e}")
                response = "yes"  # Default to recovery on error.

            if response == "yes":
                if await restore_session(app, session_name, last_state):
                    chat_view.add_system_message(
                        f"⚠ [yellow]Session recovered:[/yellow] {session_name} ({message_count} messages)\n"
                        f"[dim]Provider: {provider_info}, Tools: {tools_info}[/dim]"
                    )
                    app._log.info(f"User chose to recover crash session: {session_name}")
                else:
                    SessionManager.clear_state_file()
                    app._log.warning(f"Session restore failed for '{session_name}', cleared state file")
                return
            else:
                SessionManager.clear_state_file()
                app._log.info("User declined crash recovery, cleared state file")
                return

        # Normal auto-restore logic (not a crash).
        auto_restore = get_auto_restore_mode()
        app._log.info(f"Auto-restore mode: {auto_restore}")

        if auto_restore == "always":
            if await restore_session(app, session_name, last_state):
                chat_view.add_system_message(
                    f"✓ [green]Session restored:[/green] {session_name} ({message_count} messages)\n"
                    f"[dim]Provider: {provider_info}, Tools: {tools_info}[/dim]"
                )
                app._log.info(f"Auto-restored session: {session_name}")
            else:
                SessionManager.clear_state_file()
                app._log.warning(f"Auto-restore failed for '{session_name}', cleared state file")
            return

        # Show interactive prompt for "prompt" mode.
        if auto_restore != "never":
            app._log.info(f"Showing session restoration prompt for {session_name}")

            # Title differentiates the recovery (state pointer missing,
            # fell back to disk scan) path from the normal resume path.
            if recovered_from_disk:
                dialog_title = "Session Recovery (state pointer missing)"
                dialog_message = f"Most recent session on disk: {session_name}"
            else:
                dialog_title = "Session Restoration"
                dialog_message = f"Last session: {session_name}"

            response = await app.push_screen_wait(
                ConsentDialog(
                    title=dialog_title,
                    message=dialog_message,
                    question=f"{message_count} messages, Provider: {provider_info}, Tools: {tools_info}\n\nRestore this session?",
                    options=["Yes", "No"],
                )
            )

            if response.lower() == "yes":
                if await restore_session(app, session_name, last_state):
                    chat_view.add_system_message(
                        f"✓ [green]Session restored:[/green] {session_name} ({message_count} messages)\n"
                        f"[dim]Provider: {provider_info}, Tools: {tools_info}[/dim]"
                    )
                    app._log.info(f"User chose to restore session: {session_name}")
                else:
                    SessionManager.clear_state_file()
                    app._log.warning(f"Restore failed for '{session_name}', cleared state file")
            else:
                app._log.info("User declined session restoration")

    except Exception as e:
        app._log.error(f"Error checking session restoration: {e}", exc_info=True)


async def restore_session(
    app: "PPXAIDEApp",
    session_name: str,
    session_state: dict,
) -> bool:
    """Restore a session with provider, model, tools, and working dir state.

    Args:
        app: The PPXAIDEApp instance — provides engine_client, widgets,
            log, and `sub_title` setter.
        session_name: Name of the session file to load.
        session_state: Persisted session metadata (used by callers for
            crash-recovery branching; this function reads its own copy
            via `engine_client.restore_session()`).

    Returns:
        True if every restoration step succeeded; False otherwise. The
        caller is expected to clear the state file on False so a failed
        recovery doesn't repeat its dialog on next launch.
    """
    if not app._engine_client:
        app._log.error("Restoration failed: No engine client")
        return False

    app._log.info(f"Loading session: {session_name}")
    result = app._engine_client.restore_session(session_name)
    if not result["success"]:
        app._log.error(f"Restoration failed: {result.get('error')}")
        return False

    app._log.info(f"Session loaded successfully: {result['message_count']} messages")
    # Provider/model/tools/working_dir already synced to AppState by
    # engine_client.restore_session() → observers update badges automatically.
    app._log.info(f"Restored provider: {result.get('provider')}, model: {result.get('model')}")

    # Restore working directory (TUI-specific: os.chdir + completer + cwd badge).
    working_dir = result["working_dir"]
    if working_dir and os.path.isdir(working_dir):
        try:
            os.chdir(working_dir)
            app._working_dir = working_dir
            app._log.info(f"Restored working directory: {working_dir}")

            input_box = app._input_box
            if input_box._completer:
                input_box._completer.update_working_dir(Path(working_dir))

            tui_config = get_tui_config()
            if tui_config.get("show_cwd", True):
                cwd_display = app._format_cwd_display(working_dir)
                if app._status_bar is not None:
                    app._status_bar.update_badge("cwd", cwd_display)
                app._log.info(f"Updated cwd badge to: {cwd_display}")
        except Exception as e:
            app._log.warning(f"Failed to restore working directory: {e}")

    # Render loaded messages into ChatView (matches /load command behaviour).
    chat_view = app._chat_view
    chat_view.clear()

    messages = app._engine_client.session.messages
    app._log.info(f"Rendering {len(messages)} messages to chat view")
    for msg in messages:
        role = msg.role
        # Flatten multimodal content to text for widget display; image
        # and file parts become [Image: name] / [File: name] placeholders.
        content = msg.text_content()

        if role == "user":
            chat_view.add_user_message(content)
        elif role == "assistant":
            chat_view.add_assistant_message(content)
        elif role == "system":
            chat_view.add_system_message(content)
        elif role == "tool":
            chat_view.add_message(content, role="tool")

    # Update subtitle to match restored provider/model.
    if app._provider and app._model:
        app.sub_title = f"{app._provider}/{app._model}"
        app._log.info(f"Updated subtitle: {app.sub_title}")

    # Restore command history to InputBox (matches Rich TUI behavior).
    input_box = app._input_box
    command_history = app._engine_client.session.command_history
    if command_history:
        input_box.set_history(command_history)
        app._log.info(f"Restored {len(command_history)} commands to input history")

    # Refocus input box after session restoration (critical for autocomplete).
    input_box.focus()

    app._log.info(
        f"Session restoration complete: provider={app._provider}, "
        f"model={app._model}, tools={app._tools_enabled}"
    )
    return True
