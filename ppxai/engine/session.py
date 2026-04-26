"""
Session management for the ppxai engine.

Handles conversation history, session persistence, and usage tracking.

v1.13.9: Added session state file for auto-recovery and command history persistence.
v1.13.11: Migrated to centralized constants (ConsentMode)
"""

import base64
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Dict, Any, Optional

from .types import Message, ToolUsage, UsageStats, SessionInfo
from .session_store import SessionFileStore
from ..common.logger import get_logger
from ..constants import ConsentMode
from ..usage import save_session_usage

logger = get_logger("session")


# Session state file location
SESSION_STATE_FILE = Path.home() / ".ppxai" / "session-state.json"


# Minimal media-type → extension map used when a content block arrives
# without a `name` field — we synthesize a default filename like
# "attachment.png" so the file has a stable name in the store.
_MEDIA_TYPE_TO_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/markdown": "md",
}


def _ext_from_media_type(media_type: str) -> str:
    """Best-effort extension for an unknown-named attachment."""
    return _MEDIA_TYPE_TO_EXT.get(media_type, "bin")


def _message_has_multimodal(msg: Any) -> bool:
    """True if `msg.content` carries any multimodal content parts (R10).

    Shared by add_message / remove_last_message / _has_multimodal_attachments
    so the "is this multimodal?" predicate has exactly one definition.

    R5 (v1.17.6): recognizes both `image_url` (images) and `uploaded_file`
    (PDF/Office/large-CSV) content blocks. The cache correctness
    depends on this — if a session is multimodal under either shape,
    `save()` must route it through the directory-format writer so the
    `uploads/` subtree carries the binary bytes.
    """
    content = getattr(msg, "content", None)
    if not isinstance(content, list):
        return False
    for block in content:
        if isinstance(block, dict) and block.get("type") in (
            "image_url", "uploaded_file",
        ):
            return True
    return False


class SessionManager:
    """Manages conversation sessions, history, and persistence."""

    def __init__(self, sessions_dir: Optional[Path] = None, exports_dir: Optional[Path] = None):
        """Initialize the session manager.

        Args:
            sessions_dir: Directory for session files
            exports_dir: Directory for exported conversations
        """
        # Default directories
        if sessions_dir is None:
            sessions_dir = Path.home() / ".ppxai" / "sessions"
        if exports_dir is None:
            exports_dir = Path.home() / ".ppxai" / "exports"

        self.sessions_dir = Path(sessions_dir)
        self.exports_dir = Path(exports_dir)

        # Ensure directories exist
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

        # Current session state
        self.session_name = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.messages: List[Message] = []
        self.metadata: Dict[str, Any] = {
            "created_at": datetime.now().isoformat(),
            "provider": None,
            "model": None,
            "message_count": 0
        }
        self.usage = UsageStats()

        # Per-model usage tracking
        # Keys are "provider/model" strings, e.g., "perplexity/sonar-pro"
        self.usage_by_model: Dict[str, UsageStats] = {}

        # Usage display mode for status line
        # "session" = total session usage (default)
        # "provider" = current provider usage only
        # "model" = current model usage only
        # "off" = hide usage from status line
        self.usage_display_mode: str = "session"

        # File editing consent state (Phase 1: v1.11.0)
        self.allowed_files: set[Path] = set()  # Files user consented to edit
        self.edit_consent_mode: str = ConsentMode.PROMPT  # ConsentMode: PROMPT, ALWAYS, NEVER

        # Shell command consent state (v1.11.2)
        self.allowed_commands: set[str] = set()  # Commands user consented to run
        self.shell_consent_mode: str = ConsentMode.PROMPT  # ConsentMode: PROMPT, ALWAYS, NEVER

        # Session persistence and recovery
        self.command_history: List[str] = []  # User input history for this session
        self.working_dir: str = os.getcwd()  # Working directory for this session
        self.tools_enabled: bool = False  # Whether tools were enabled
        self._dirty: bool = False  # True if session has unsaved changes
        self._was_dirty: bool = False  # True if save_dirty() was ever called this session

        # Optional callbacks wired by EngineClient to sync to AppState.
        self.on_usage_updated: Optional[Callable[[UsageStats], None]] = None
        self.on_name_changed: Optional[Callable[[str], None]] = None
        # Fires whenever `self.messages` mutates (add/remove/replace/load/clear).
        # EngineClient wires this to recompute the `context_attachments`
        # AppState field so every client's multimodal badge stays fresh.
        self.on_messages_changed: Optional[Callable[[], None]] = None

        # Binary file store for multimodal attachments (v1.17.4 Phase 2.1a).
        # EngineClient wires an instance here so serialize/deserialize can
        # swap inline data: URIs for compact file_id references in session
        # JSON. When None, serialization falls back to the legacy
        # inline-base64 format — so tests that don't care about multimodal
        # content can use SessionManager standalone without wiring a store.
        self.file_store: Optional[SessionFileStore] = None

        # R10: cache the answer to _has_multimodal_attachments() so save()
        # doesn't walk every message on every auto-save. None means "needs
        # scan" (cold start / after a removal that could have flipped the
        # answer); True/False is authoritative. Invalidated on any
        # mutation that could remove multimodal content; eagerly upgraded
        # to True in add_message when the new message is multimodal, so
        # the common "adding another user turn" path stays scan-free.
        self._multimodal_cache: Optional[bool] = None

    def _notify_messages_changed(self) -> None:
        """Invoke the on_messages_changed callback if wired.

        Exceptions in the callback are swallowed — the session is the source
        of truth and must never fail because a listener misbehaved.
        """
        if self.on_messages_changed is not None:
            try:
                self.on_messages_changed()
            except Exception as exc:
                logger.warning(f"on_messages_changed listener raised: {exc}")

    def add_message(self, message: Message):
        """Add a message to the conversation history.

        Args:
            message: Message to add
        """
        self.messages.append(message)
        self.metadata["message_count"] = len(self.messages)
        # R10: upgrade the multimodal cache inline. Adding a multimodal
        # message always flips the answer to True; adding a text-only
        # message never flips True → False, so False and None stay as-is.
        if self._multimodal_cache is not True and _message_has_multimodal(message):
            self._multimodal_cache = True
        self._notify_messages_changed()

    def get_messages(self) -> List[Message]:
        """Get conversation history.

        Returns:
            List of Message objects
        """
        return self.messages.copy()

    def get_messages_as_dicts(self) -> List[Dict[str, Any]]:
        """Get conversation history as dictionaries.

        Returns:
            List of dicts with 'role', 'content', and optional tool fields
        """
        return [self._serialize_message(m) for m in self.messages]

    def _serialize_message(self, m: Message) -> Dict[str, Any]:
        """Serialize a Message to a dict for JSON storage/API use.

        Content handling (v1.17.4 Phase 2.1a):
        - String content → passed through unchanged (legacy single-modal)
        - List content → scanned for `image_url` parts with `data:` URIs.
          When `self.file_store` is wired, each data URI is materialized
          into the store (hashing yields a stable `file_id`) and the
          content part is rewritten to carry a compact
          `file://uploads/<file_id>/<name>` reference plus an explicit
          `file_id` field. Session JSON stays small; bytes live on disk
          in the session's `uploads/` directory.
        - When `self.file_store` is None (tests, legacy callers), list
          content passes through unchanged and session JSON contains
          inline base64 — matching Phase 1 behavior for backward compat.

        The rewritten shape is stable across save → load round trips:
        `_deserialize_message` reads the `file_id` field and expands the
        reference back into a `data:` URI so in-memory `Message.content`
        matches what providers expect. All provider adapters (Gemini,
        OpenAI, Perplexity) continue to see identical data URIs whether
        the session was just loaded or built mid-conversation.
        """
        content = m.content
        if self.file_store is not None and isinstance(content, list):
            content = self._rewrite_content_for_serialize(content)

        msg: Dict[str, Any] = {"role": m.role, "content": content}
        if m.tool_calls:
            msg["tool_calls"] = m.tool_calls
        if m.tool_call_id:
            msg["tool_call_id"] = m.tool_call_id
        return msg

    def _deserialize_message(self, m: Dict[str, Any]) -> Message:
        """Deserialize a dict to a Message.

        Accepts every shape `_serialize_message` produces:
        - Legacy string content
        - Legacy inline-base64 list content (Phase 1 sessions, no file_store)
        - New file_id-referenced list content (Phase 2.1a sessions) —
          expanded back into data URIs via `self.file_store` so in-memory
          messages look identical to what provider adapters expect.
        """
        content = m["content"]
        if self.file_store is not None and isinstance(content, list):
            content = self._rewrite_content_for_deserialize(content)

        return Message(
            role=m["role"],
            content=content,
            tool_calls=m.get("tool_calls"),
            tool_call_id=m.get("tool_call_id"),
        )

    # ------------------------------------------------------------------
    # Content-part rewriting for SessionFileStore integration
    # ------------------------------------------------------------------

    def _rewrite_content_for_serialize(
        self, content: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Rewrite `data:` URIs in image_url content parts to file_id references.

        For every block that carries a `data:image/...;base64,...` URI:
        1. Decode the base64 payload once
        2. Save the bytes via SessionFileStore (idempotent — identical
           content across turns yields a single on-disk copy thanks to
           content-addressed file_ids)
        3. Replace the URL with `file://uploads/<file_id>/<name>` and set
           an explicit `file_id` field on the block

        Blocks that already carry a `file_id` field (i.e. were produced
        by `/attach` which now pre-registers with the store) are passed
        through unchanged — we don't re-hash bytes that are already on disk.

        Non-image parts, string content, and malformed data URIs are
        passed through unchanged. Failures during base64 decode or store
        write are logged and the original block is kept, so a corrupt
        attachment never blocks the whole session save.
        """
        if self.file_store is None:
            return content

        rewritten: List[Dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "image_url":
                rewritten.append(block)
                continue

            # Already-registered block — rewrite URL only.
            existing_file_id = block.get("file_id")
            url = (block.get("image_url") or {}).get("url", "")

            if existing_file_id:
                meta = self.file_store.get_metadata(existing_file_id)
                if meta is not None:
                    new_block = dict(block)
                    new_block["image_url"] = {
                        "url": f"file://uploads/{existing_file_id}/{meta.name}"
                    }
                    new_block["file_id"] = existing_file_id
                    rewritten.append(new_block)
                    continue
                # file_id is stale — fall through to re-register from URL.

            if not url.startswith("data:"):
                # Non-data URL (http, file://, etc.) — pass through.
                rewritten.append(block)
                continue

            # data:image/png;base64,HELLO...  →  decode, save, rewrite
            try:
                header, b64data = url.split(",", 1)
                media_type = header[5:].split(";", 1)[0] or "application/octet-stream"
                raw = base64.b64decode(b64data)
            except (ValueError, base64.binascii.Error) as exc:
                logger.warning(
                    f"Session serialize: malformed data URI in image_url block: {exc}"
                )
                rewritten.append(block)
                continue

            name = block.get("name") or f"attachment.{_ext_from_media_type(media_type)}"
            try:
                meta = self.file_store.save(name, raw, media_type=media_type)
            except OSError as exc:
                logger.warning(
                    f"Session serialize: file_store.save failed for {name}: {exc}"
                )
                rewritten.append(block)
                continue

            new_block = dict(block)
            new_block["image_url"] = {
                "url": f"file://uploads/{meta.file_id}/{meta.name}"
            }
            new_block["file_id"] = meta.file_id
            new_block["name"] = meta.name  # Normalize in case caller omitted it
            rewritten.append(new_block)

        return rewritten

    def _rewrite_content_for_deserialize(
        self, content: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Expand file_id references back into data URIs.

        Inverse of `_rewrite_content_for_serialize`. For every block
        carrying a `file_id` field, look up the bytes in the store,
        base64-encode them, and rebuild a `data:` URI on
        `image_url.url` so provider adapters see the format they expect.

        Legacy Phase-1 blocks (no file_id, inline data URI already)
        pass through unchanged. Missing files (user deleted
        `~/.ppxai/sessions/foo/uploads/` manually, etc.) are replaced
        with a text placeholder block so deserialization never crashes
        a session load — the user sees `[Attachment missing: chart.png]`
        instead of a confusing exception.
        """
        if self.file_store is None:
            return content

        rewritten: List[Dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "image_url":
                rewritten.append(block)
                continue

            file_id = block.get("file_id")
            if not file_id:
                # Legacy shape — no file_id, already has inline data URI.
                rewritten.append(block)
                continue

            meta = self.file_store.get_metadata(file_id)
            if meta is None or not meta.path.exists():
                # File vanished — replace with a text placeholder so the
                # conversation remains loadable.
                name = block.get("name") or file_id
                logger.warning(
                    f"Session deserialize: attachment missing for file_id={file_id}, "
                    f"replacing with placeholder"
                )
                rewritten.append({
                    "type": "text",
                    "text": f"[Attachment missing: {name}]",
                })
                continue

            try:
                raw = meta.path.read_bytes()
            except OSError as exc:
                logger.warning(
                    f"Session deserialize: cannot read {meta.path} for "
                    f"file_id={file_id}: {exc}"
                )
                rewritten.append({
                    "type": "text",
                    "text": f"[Attachment unreadable: {meta.name}]",
                })
                continue

            b64 = base64.b64encode(raw).decode("ascii")
            new_block = dict(block)
            new_block["image_url"] = {
                "url": f"data:{meta.media_type};base64,{b64}",
            }
            new_block["file_id"] = file_id
            new_block["name"] = meta.name
            rewritten.append(new_block)

        return rewritten

    def remove_last_message(self) -> bool:
        """Remove the last message from conversation history.

        Used to cleanup interrupted messages (e.g., Ctrl-C during streaming)
        to maintain proper user/assistant message alternation.

        Returns:
            True if a message was removed, False if history was empty
        """
        if self.messages:
            removed = self.messages.pop()
            self.metadata["message_count"] = len(self.messages)
            # R10: if the popped message carried multimodal content, the
            # cached answer might now be wrong (was the only multimodal
            # message, or one of several). Invalidate rather than scan —
            # the next save() recomputes lazily.
            if self._multimodal_cache is True and _message_has_multimodal(removed):
                self._multimodal_cache = None
            self._notify_messages_changed()
            return True
        return False

    def validate_and_fix_alternation(self) -> int:
        """Validate and fix message alternation issues.

        Ensures messages follow valid sequences:
        - Basic: user → assistant → user → assistant → ...
        - With tools: user → assistant(tool_calls) → tool → ... → assistant → user → ...

        Tool role messages are allowed after assistant messages that have tool_calls.
        Multiple consecutive tool messages are valid (for multi-tool support).

        Also ensures session starts with user message (not assistant), because
        when tools are enabled a system prompt is prepended, and APIs require
        user/tool messages after system messages.

        User messages are considered less valuable than assistant responses since
        user input is available in command history and logs.

        Returns:
            Number of messages removed to fix alternation issues
        """
        if not self.messages:
            return 0

        removed_count = 0

        # Remove leading assistant/tool messages (they break alternation when system prompt is prepended)
        while self.messages and self.messages[0].role in ("assistant", "tool"):
            removed = self.messages.pop(0)
            removed_count += 1
            logger.warning(
                f"Session alternation fix: removed leading {removed.role} message "
                f"(len={len(removed.text_content())})"
            )

        if not self.messages:
            # All messages were assistant/tool messages
            self.metadata["message_count"] = 0
            if removed_count > 0:
                logger.info(
                    f"Session alternation fixed: removed {removed_count} messages, "
                    f"0 remaining"
                )
            return removed_count

        fixed_messages = []

        for i, msg in enumerate(self.messages):
            if not fixed_messages:
                # First message - always keep (already ensured it's user)
                fixed_messages.append(msg)
                continue

            prev = fixed_messages[-1]

            # Tool messages are valid after assistant(tool_calls) or after another tool message
            if msg.role == "tool":
                if prev.role == "assistant" and prev.tool_calls:
                    fixed_messages.append(msg)
                elif prev.role == "tool":
                    fixed_messages.append(msg)
                else:
                    # Orphan tool message — drop it
                    removed_count += 1
                    logger.warning(
                        f"Session alternation fix: removed orphan tool message "
                        f"(len={len(msg.text_content())}) at position {i}"
                    )
                continue

            if prev.role != msg.role:
                # Proper alternation - keep
                fixed_messages.append(msg)
            elif prev.role == "tool":
                # Non-tool message after tool — valid (assistant responding to tool results)
                fixed_messages.append(msg)
            else:
                # Same role as previous - this breaks alternation
                # Strategy: prefer the message with load-bearing payload, then
                # fall back to "more content". For assistants, a message with
                # non-empty tool_calls must never lose to a plain-text sibling
                # because native tool-calling messages often have empty
                # content (R9).
                if msg.role == "assistant":
                    prev_has_calls = bool(prev.tool_calls)
                    msg_has_calls = bool(msg.tool_calls)
                    if msg_has_calls and not prev_has_calls:
                        # tool_calls beats plain text regardless of length
                        fixed_messages[-1] = msg
                    elif prev_has_calls and not msg_has_calls:
                        # keep prev (tool_calls), drop msg
                        pass
                    else:
                        # both have tool_calls, or neither does — longer wins
                        if len(msg.text_content()) > len(prev.text_content()):
                            fixed_messages[-1] = msg
                else:
                    # Two user messages in a row - keep first one (already in fixed_messages)
                    pass
                removed_count += 1
                dropped = msg if fixed_messages[-1] is prev else prev
                logger.warning(
                    f"Session alternation fix: removed duplicate {msg.role} message "
                    f"(len={len(dropped.text_content())}, tool_calls="
                    f"{bool(dropped.tool_calls) if dropped.role == 'assistant' else 'n/a'}) "
                    f"at position {i}"
                )

        # Also ensure session ends with assistant message (not orphan user)
        # A trailing user message without assistant response will cause alternation
        # errors when the next message is sent
        # Tool messages at the end are also problematic — they need a following assistant
        while fixed_messages and fixed_messages[-1].role in ("user", "tool"):
            removed = fixed_messages.pop()
            removed_count += 1
            # Trailing user = unsent prompt. Make the loss unambiguous in logs
            # so regressions like "session saved mid-turn lost my question" are
            # visible instead of silently buried in an info-level roll-up (R9).
            if removed.role == "user":
                logger.warning(
                    f"Session alternation fix: DROPPED UNSENT USER PROMPT "
                    f"(len={len(removed.text_content())}) — "
                    f"session was saved before the assistant responded. "
                    f"Preview: {removed.text_content()[:120]!r}"
                )
            else:
                logger.warning(
                    f"Session alternation fix: removed trailing {removed.role} message "
                    f"(len={len(removed.text_content())})"
                )

        if removed_count > 0:
            self.messages = fixed_messages
            self.metadata["message_count"] = len(self.messages)
            # R10: alternation fix may have dropped multimodal messages
            # (it reassigns self.messages wholesale). Invalidate cache.
            self._multimodal_cache = None
            logger.info(
                f"Session alternation fixed: removed {removed_count} messages, "
                f"{len(self.messages)} remaining"
            )
            self._notify_messages_changed()

        return removed_count

    def reset_for_model_switch(self) -> int:
        """Strip assistant and tool messages, keeping user messages only.

        Used when switching models to prevent context pollution from
        the previous model's responses.

        After stripping, validates message alternation to ensure the
        resulting sequence is valid for APIs that require strict
        user/assistant alternation (e.g., Perplexity).

        Returns:
            Count of removed messages.
        """
        original_count = len(self.messages)
        self.messages = [m for m in self.messages if m.role == "user"]
        self.metadata["message_count"] = len(self.messages)
        removed = original_count - len(self.messages)
        if removed:
            # R10: reset filtered out assistant/tool messages, which could
            # have carried multimodal tool results. Invalidate — next
            # save() recomputes lazily.
            self._multimodal_cache = None
            logger.info(
                f"Model switch: removed {removed} assistant/tool messages, "
                f"kept {len(self.messages)} user messages"
            )
            self._notify_messages_changed()

        # Fix alternation: stripping assistant messages leaves consecutive
        # user messages which violates API requirements (e.g., Perplexity)
        # validate_and_fix_alternation() will fire its own notification if
        # it ends up mutating anything further.
        alternation_fixed = self.validate_and_fix_alternation()
        if alternation_fixed:
            removed += alternation_fixed

        return removed

    def clear(self):
        """Clear conversation history and reset consent state."""
        self.messages = []
        self.metadata["message_count"] = 0
        # Reset file editing consent state
        self.allowed_files.clear()
        self.edit_consent_mode = ConsentMode.PROMPT
        # R10: empty session has no multimodal content — cache directly.
        self._multimodal_cache = False
        self._notify_messages_changed()

    def set_provider(self, provider: str):
        """Set the current provider.

        Args:
            provider: Provider name
        """
        self.metadata["provider"] = provider

    def set_model(self, model: str):
        """Set the current model.

        Args:
            model: Model ID
        """
        self.metadata["model"] = model

    def update_usage(self, usage: UsageStats, provider: str = None, model: str = None):
        """Update usage statistics.

        Args:
            usage: UsageStats to add
            provider: Provider name (for per-model tracking)
            model: Model ID (for per-model tracking)
        """
        # Update session totals
        self.usage.prompt_tokens += usage.prompt_tokens
        self.usage.completion_tokens += usage.completion_tokens
        self.usage.total_tokens += usage.total_tokens
        self.usage.estimated_cost += usage.estimated_cost

        # Update per-model tracking
        if provider and model:
            key = f"{provider}/{model}"
            if key not in self.usage_by_model:
                self.usage_by_model[key] = UsageStats()

            model_usage = self.usage_by_model[key]
            model_usage.prompt_tokens += usage.prompt_tokens
            model_usage.completion_tokens += usage.completion_tokens
            model_usage.total_tokens += usage.total_tokens
            model_usage.estimated_cost += usage.estimated_cost

        # Merge tool usage and add tool costs to session total (v1.16.0)
        for tool_name, tool_usage in usage.tool_calls.items():
            if tool_name not in self.usage.tool_calls:
                self.usage.tool_calls[tool_name] = ToolUsage(provider=tool_usage.provider)
            self.usage.tool_calls[tool_name].call_count += tool_usage.call_count
            self.usage.tool_calls[tool_name].tokens_in += tool_usage.tokens_in
            self.usage.tool_calls[tool_name].tokens_out += tool_usage.tokens_out
            self.usage.tool_calls[tool_name].estimated_cost += tool_usage.estimated_cost
            # Tool costs contribute to session total
            self.usage.estimated_cost += tool_usage.estimated_cost

        # Notify listener (AppState sync)
        if self.on_usage_updated:
            self.on_usage_updated(self.usage)

    def get_usage(self) -> Dict[str, Any]:
        """Get usage statistics.

        Returns:
            Dictionary with usage stats including per-model breakdown and tool usage
        """
        return {
            "total_tokens": self.usage.total_tokens,
            "prompt_tokens": self.usage.prompt_tokens,
            "completion_tokens": self.usage.completion_tokens,
            "estimated_cost": self.usage.estimated_cost,
            # Add per-model breakdown
            "by_model": {
                key: {
                    "total_tokens": stats.total_tokens,
                    "prompt_tokens": stats.prompt_tokens,
                    "completion_tokens": stats.completion_tokens,
                    "estimated_cost": stats.estimated_cost
                }
                for key, stats in self.usage_by_model.items()
            },
            # Add tool usage breakdown
            "tool_calls": {
                tool_name: {
                    "call_count": tool_usage.call_count,
                    "tokens_in": tool_usage.tokens_in,
                    "tokens_out": tool_usage.tokens_out,
                    "estimated_cost": tool_usage.estimated_cost,
                    "provider": tool_usage.provider
                }
                for tool_name, tool_usage in self.usage.tool_calls.items()
            },
            "display_mode": self.usage_display_mode
        }

    def get_usage_for_display(self, current_provider: str = None, current_model: str = None) -> Optional[Dict[str, Any]]:
        """Get usage statistics for status line display based on display mode.

        Args:
            current_provider: Current provider name
            current_model: Current model ID

        Returns:
            Dictionary with usage stats for display, or None if display_mode is "off"
        """
        if self.usage_display_mode == "off":
            return None

        if self.usage_display_mode == "session":
            return {
                "label": None,  # No label for session totals
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "estimated_cost": self.usage.estimated_cost
            }

        if self.usage_display_mode == "provider" and current_provider:
            # Aggregate all models for current provider
            prompt_tokens = 0
            completion_tokens = 0
            estimated_cost = 0.0
            for key, stats in self.usage_by_model.items():
                if key.startswith(f"{current_provider}/"):
                    prompt_tokens += stats.prompt_tokens
                    completion_tokens += stats.completion_tokens
                    estimated_cost += stats.estimated_cost
            return {
                "label": current_provider[:4],  # Short provider label
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "estimated_cost": estimated_cost
            }

        if self.usage_display_mode == "model" and current_provider and current_model:
            key = f"{current_provider}/{current_model}"
            if key in self.usage_by_model:
                stats = self.usage_by_model[key]
                # Use short model name (last part after any /)
                short_model = current_model.split("/")[-1][:12]
                return {
                    "label": short_model,
                    "prompt_tokens": stats.prompt_tokens,
                    "completion_tokens": stats.completion_tokens,
                    "estimated_cost": stats.estimated_cost
                }
            return {
                "label": current_model.split("/")[-1][:12],
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "estimated_cost": 0.0
            }

        # Fallback to session totals
        return {
            "label": None,
            "prompt_tokens": self.usage.prompt_tokens,
            "completion_tokens": self.usage.completion_tokens,
            "estimated_cost": self.usage.estimated_cost
        }

    def set_usage_display_mode(self, mode: str) -> bool:
        """Set the usage display mode for status line.

        Args:
            mode: One of "session", "provider", "model", "off"

        Returns:
            True if mode was set successfully
        """
        valid_modes = {"session", "provider", "model", "off"}
        if mode in valid_modes:
            self.usage_display_mode = mode
            return True
        return False

    def reset_usage(self):
        """Reset all usage statistics to zero."""
        self.usage = UsageStats()
        self.usage_by_model.clear()

    def get_usage_by_provider(self) -> Dict[str, Dict[str, Any]]:
        """Get usage aggregated by provider.

        Returns:
            Dictionary with provider as key and aggregated stats as value
        """
        by_provider: Dict[str, UsageStats] = {}
        for key, stats in self.usage_by_model.items():
            provider = key.split("/")[0]
            if provider not in by_provider:
                by_provider[provider] = UsageStats()
            by_provider[provider].prompt_tokens += stats.prompt_tokens
            by_provider[provider].completion_tokens += stats.completion_tokens
            by_provider[provider].total_tokens += stats.total_tokens
            by_provider[provider].estimated_cost += stats.estimated_cost

        return {
            provider: {
                "total_tokens": stats.total_tokens,
                "prompt_tokens": stats.prompt_tokens,
                "completion_tokens": stats.completion_tokens,
                "estimated_cost": stats.estimated_cost
            }
            for provider, stats in by_provider.items()
        }

    # ------------------------------------------------------------------
    # Session save path — dual-format (flat .json vs directory)
    # ------------------------------------------------------------------

    def _has_multimodal_attachments(self) -> bool:
        """True if any message in the session has image_url content parts.

        Used by save()/load() to decide between the flat `<name>.json`
        format (text-only sessions, backward compat) and the directory
        format `<name>/session.json` + `<name>/uploads/` (multimodal
        sessions).

        R10: result is cached on the session and invalidated by the
        mutation sites that could flip the answer (add_message /
        remove_last_message / clear / reset_for_model_switch / load /
        validate_and_fix_alternation). Cold-start cost is still
        O(messages × parts), but every subsequent save() during a long
        conversation is O(1) — which matters for text-only sessions on
        TUIs that auto-save after every turn.
        """
        if self._multimodal_cache is not None:
            return self._multimodal_cache

        result = any(_message_has_multimodal(m) for m in self.messages)
        self._multimodal_cache = result
        return result

    def _resolve_session_storage(self, name: str) -> tuple[Path, bool]:
        """Determine the JSON path and format for a given session name.

        Priority:
        1. If `<name>/` already exists on disk → directory format (once
           upgraded, always directory — never downgrade back to flat)
        2. Else if this session currently has multimodal attachments →
           directory format (migration case: a previously-flat session
           gained its first attachment, must switch to directory to hold
           the uploads/ subdirectory)
        3. Else if `<name>.json` exists → flat format (stable text-only
           session keeps its existing flat file untouched)
        4. Otherwise → new flat file

        Note the ordering: rule 2 runs before rule 3 so the flat→directory
        transition fires as soon as an attachment appears, rather than
        getting pinned to flat forever by a stale `.json` file. The
        caller (`_write_session_json`) cleans up the stale flat file after
        writing the directory-format session.

        Returns:
            Tuple of (json_path, is_directory_format).
        """
        dir_path = self.sessions_dir / name
        flat_path = self.sessions_dir / f"{name}.json"

        # Rule 1: existing directory format wins — no downgrades.
        if dir_path.is_dir():
            return dir_path / "session.json", True

        # Rule 2: multimodal content forces directory format even if a
        # stale flat file exists (format migration mid-conversation).
        if self._has_multimodal_attachments():
            return dir_path / "session.json", True

        # Rule 3: text-only session with an existing flat file — keep it.
        if flat_path.is_file():
            return flat_path, False

        # Rule 4: brand new session with no attachments — new flat file.
        return flat_path, False

    def _write_session_json(
        self, session_name: str, session_data: Dict[str, Any]
    ) -> Path:
        """Write session JSON to the correct flat/directory location.

        Handles the flat → directory transition when a session that
        started text-only gains its first attachment mid-conversation.
        This is the only place session JSON is written to disk.

        R11 crash-safety (v1.17.4): when transitioning flat → directory,
        the new directory is staged under a `<name>.tmp/` sibling and
        atomically renamed to `<name>/` before the old flat file is
        removed. `os.rename` is atomic on POSIX same-filesystem moves,
        so a crash mid-transition leaves either the flat file alone
        (directory never appeared) or the directory alone (flat file
        already gone) — never both visible to the session list.

        Sequence for a flat → directory transition:
          1. Create `<name>.tmp/` (no conflict with the live `<name>.json`)
          2. Write `<name>.tmp/session.json` + migrate uploads
          3. `os.rename(<name>.tmp, <name>)` — atomic, single step
          4. `unlink(<name>.json)` — if this step crashes, the
             duplicate-detector in `_resolve_session_load_path` picks
             the directory (newer mtime) and warns

        Updates and pure text-only saves bypass the staging dance.
        """
        json_path, is_dir_format = self._resolve_session_storage(session_name)
        dir_path = self.sessions_dir / session_name
        flat_path = self.sessions_dir / f"{session_name}.json"
        # Has a flat file from a prior text-only save? This is the
        # signal we're doing a transition, not a normal write.
        is_transition = is_dir_format and flat_path.exists() and not dir_path.exists()

        if is_dir_format and is_transition:
            # Stage into a sibling tmp directory, then atomic rename.
            tmp_dir = self.sessions_dir / f"{session_name}.tmp"
            # Clean up any leftover from an earlier failed attempt so
            # rmtree + mkdir start fresh. Using shutil.rmtree so stale
            # partial writes don't block us.
            if tmp_dir.exists():
                import shutil
                try:
                    shutil.rmtree(tmp_dir)
                except OSError as exc:
                    logger.warning(
                        f"Session '{session_name}': stale tmp dir "
                        f"{tmp_dir} couldn't be cleaned: {exc}. "
                        f"Falling back to in-place write."
                    )
                    return self._write_session_json_in_place(
                        session_name, session_data, is_dir_format
                    )
            tmp_dir.mkdir(parents=True, exist_ok=False)

            # Write session.json into the tmp dir.
            tmp_json = tmp_dir / "session.json"
            with open(tmp_json, "w", encoding="utf-8") as f:
                json.dump(session_data, f, indent=2)

            # Move staged files from the store into the tmp uploads/.
            # If the store's move_to_session signs off, we commit.
            if self.file_store is not None:
                self.file_store.move_to_session(tmp_dir)

            # Atomic rename — the filesystem flips from "tmp dir
            # present, live dir absent" to "live dir present" in a
            # single inode update.
            try:
                os.rename(tmp_dir, dir_path)
            except OSError as exc:
                logger.error(
                    f"Session '{session_name}': atomic rename "
                    f"{tmp_dir} → {dir_path} failed: {exc}. The tmp "
                    f"directory is left in place for manual recovery."
                )
                raise

            # Finally remove the old flat file. A crash here is safe:
            # the duplicate-detector on load picks the directory (newer
            # mtime) and warns about the orphan.
            try:
                flat_path.unlink()
                logger.debug(
                    f"Session format transition: atomically renamed "
                    f"{tmp_dir.name} → {dir_path.name} and removed "
                    f"stale flat {flat_path.name}"
                )
            except OSError as exc:
                logger.warning(
                    f"Session '{session_name}': directory transition "
                    f"succeeded but unlink of stale flat "
                    f"{flat_path.name} failed: {exc}. Duplicate-detector "
                    f"will handle on next load."
                )

            return dir_path / "session.json"

        # Non-transition path: directory already exists, or we're
        # writing a pure flat session. Both are single-file writes so
        # atomicity is already handled by the filesystem for overwrite.
        return self._write_session_json_in_place(
            session_name, session_data, is_dir_format
        )

    def _write_session_json_in_place(
        self,
        session_name: str,
        session_data: Dict[str, Any],
        is_dir_format: bool,
    ) -> Path:
        """Write session JSON without the flat→dir transition dance.

        Used when either (a) the session is already in directory format
        and we're just updating session.json, or (b) the session is
        purely flat. No rename, no cross-format footwork — just the
        single JSON write.
        """
        dir_path = self.sessions_dir / session_name
        if is_dir_format:
            dir_path.mkdir(parents=True, exist_ok=True)
            if self.file_store is not None:
                self.file_store.move_to_session(dir_path)
            json_path = dir_path / "session.json"
        else:
            json_path = self.sessions_dir / f"{session_name}.json"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=2)
        return json_path

    def save(self, name: Optional[str] = None) -> str:
        """Save current session to file.

        Args:
            name: Optional session name (uses auto-generated if not provided)

        Returns:
            Session name

        v1.13.9: Now includes working_dir and tools_enabled for session persistence.
        v1.14.1: Validates and fixes message alternation before saving.
        v1.17.4: Dual-format storage (flat JSON for text-only, directory
                 with uploads/ for multimodal). Handled by _write_session_json.
        """
        if name:
            self.session_name = name
            if self.on_name_changed:
                self.on_name_changed(name)

        # Validate and fix alternation issues before saving (v1.14.1)
        self.validate_and_fix_alternation()

        session_data = {
            "session_name": self.session_name,
            "metadata": self.metadata,
            "messages": [self._serialize_message(m) for m in self.messages],
            "usage": self.get_usage(),
            "saved_at": datetime.now().isoformat(),
            # Include persistence fields
            "command_history": self.command_history,
            "working_dir": self.working_dir,
            "tools_enabled": self.tools_enabled
        }

        self._write_session_json(self.session_name, session_data)

        # Only update the state pointer when this session has actual messages.
        # An empty-session save (e.g. /save right after startup) must not clobber
        # the pointer to the previous meaningful session so it can still be restored.
        if self.messages:
            self._update_state_file(dirty=False)
            self._dirty = False

        return self.session_name

    def _resolve_session_load_path(self, name: str) -> Optional[tuple[Path, Optional[Path]]]:
        """Find the JSON file for a saved session name.

        Returns a tuple of (json_path, session_dir) where `session_dir`
        is the enclosing directory for directory-format sessions (used
        to restore the file store) or None for flat-format sessions.
        Returns None if no session with that name exists in either format.

        R11 duplicate-detector (v1.17.4): if BOTH a flat `<name>.json`
        and a directory `<name>/session.json` exist sharing the same
        name, the session-format transition was interrupted mid-flight
        (crash/SIGKILL/filesystem error between the directory write and
        the flat-file unlink). We log a WARNING and pick the newer
        file by mtime so the user at least sees a deterministic result
        instead of two entries for the same conversation in the session
        list. Full atomic-rename fix is still R11 in TODO-file-upload.
        """
        # Reject names that would escape sessions_dir via path traversal.
        # Path("/a/b") / "../c" resolves to /a/c on open() even without
        # .resolve(), so we must validate before any filesystem operation.
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            return None

        dir_path = self.sessions_dir / name
        flat_path = self.sessions_dir / f"{name}.json"

        dir_json = dir_path / "session.json"
        has_dir = dir_path.is_dir() and dir_json.is_file()
        has_flat = flat_path.is_file()

        # Duplicate-format detector — both layouts coexist. Pick newer;
        # log explicitly so the condition surfaces in debug logs.
        if has_dir and has_flat:
            try:
                dir_mtime = dir_json.stat().st_mtime
                flat_mtime = flat_path.stat().st_mtime
            except OSError as exc:
                logger.warning(
                    f"Session '{name}': both flat and directory formats "
                    f"exist, stat() failed during tiebreak: {exc}. "
                    f"Defaulting to directory format."
                )
                return dir_json, dir_path

            if dir_mtime >= flat_mtime:
                logger.warning(
                    f"Session '{name}': found duplicate formats on disk "
                    f"(flat + directory). Picking directory (mtime "
                    f"{dir_mtime:.0f} >= flat {flat_mtime:.0f}). The "
                    f"stale flat file {flat_path.name} should be removed "
                    f"— it's a leftover from an interrupted format "
                    f"transition. See R11 in TODO-file-upload.md."
                )
                return dir_json, dir_path
            else:
                logger.warning(
                    f"Session '{name}': found duplicate formats on disk "
                    f"(flat + directory), but flat is NEWER "
                    f"(flat {flat_mtime:.0f} > dir {dir_mtime:.0f}). "
                    f"This is unusual — the directory format was written "
                    f"then the flat file was touched again somehow. "
                    f"Picking flat; investigate manually."
                )
                return flat_path, None

        if has_dir:
            return dir_json, dir_path
        if has_flat:
            return flat_path, None
        return None

    def load(self, name: str) -> bool:
        """Load a saved session.

        Args:
            name: Session name to load

        Returns:
            True if loaded successfully

        v1.14.1: Validates and fixes message alternation after loading.
        v1.17.4: Dual-format support — finds both flat `<name>.json` and
                 directory `<name>/session.json` layouts. Restores the
                 file store from `<name>/uploads/` for directory sessions.
        """
        resolved = self._resolve_session_load_path(name)
        if resolved is None:
            return False
        filepath, session_dir = resolved

        try:
            # Restore the file store from the session's uploads/ directory
            # BEFORE deserializing messages. Deserialization needs the store
            # populated so it can expand `file_id` references back into
            # data URIs; without it, any attachments load as missing-file
            # placeholders.
            if session_dir is not None and self.file_store is not None:
                restored = self.file_store.restore_from_session(session_dir)
                if restored > 0:
                    logger.debug(
                        f"Restored {restored} attachment(s) from {session_dir}/uploads/"
                    )

            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.session_name = data.get("session_name", name)
            self.metadata = data.get("metadata", {})
            self.messages = [
                self._deserialize_message(m)
                for m in data.get("messages", [])
            ]
            # R10: reset the multimodal cache — one scan on the first save()
            # after load, then O(1) for every subsequent auto-save.
            self._multimodal_cache = None

            usage_data = data.get("usage", {})
            self.usage = UsageStats(
                total_tokens=usage_data.get("total_tokens", 0),
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                estimated_cost=usage_data.get("estimated_cost", 0.0)
            )

            # Load persistence fields
            self.command_history = data.get("command_history", [])
            self.working_dir = data.get("working_dir", os.getcwd())
            self.tools_enabled = data.get("tools_enabled", False)

            # Validate and fix alternation issues after loading (v1.14.1)
            # validate_and_fix_alternation() fires its own on_messages_changed
            # when it mutates anything; we always fire after a successful load
            # below so listeners (AppState sync) pick up the newly loaded
            # messages even when alternation was already clean.
            fixed_count = self.validate_and_fix_alternation()
            if fixed_count > 0:
                logger.warning(
                    f"Loaded session '{name}' had {fixed_count} message alternation issues - auto-fixed"
                )

            self._notify_messages_changed()
            return True

        except Exception as e:
            logger.warning(f"Session load failed for '{name}': {e}")
            return False

    def list_sessions(self) -> List[SessionInfo]:
        """List all saved sessions.

        Returns:
            List of SessionInfo objects, sorted by filename in reverse
            (newest first by naming convention).

        v1.17.4: Scans both flat `<name>.json` files and directory-format
        `<name>/session.json` layouts so multimodal sessions appear
        alongside text-only ones. Deduplicates by session name in case
        a transition left stale artifacts on disk.
        """
        # Collect (json_path, synthetic_name) pairs from both layouts.
        candidates: List[tuple[Path, str]] = []

        # Flat format: ~/.ppxai/sessions/<name>.json
        for filepath in self.sessions_dir.glob("*.json"):
            candidates.append((filepath, filepath.stem))

        # Directory format: ~/.ppxai/sessions/<name>/session.json
        for entry in self.sessions_dir.iterdir():
            if not entry.is_dir():
                continue
            session_json = entry / "session.json"
            if session_json.is_file():
                candidates.append((session_json, entry.name))

        # Sort by synthetic name descending (newest timestamped sessions
        # come first under the default naming convention).
        candidates.sort(key=lambda pair: pair[1], reverse=True)

        sessions: List[SessionInfo] = []
        seen_names: set = set()
        for filepath, fallback_name in candidates:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                session_name = data.get("session_name", fallback_name)
                if session_name in seen_names:
                    # Stale flat file from a format transition — directory
                    # format takes precedence because it's written later.
                    continue
                seen_names.add(session_name)

                metadata = data.get("metadata", {})
                sessions.append(SessionInfo(
                    name=session_name,
                    created_at=metadata.get("created_at", ""),
                    provider=metadata.get("provider", "unknown"),
                    model=metadata.get("model", "unknown"),
                    message_count=len(data.get("messages", [])),
                    saved_at=data.get("saved_at", ""),
                ))
            except Exception as e:
                logger.warning(
                    f"Skipping corrupted session file '{filepath}': {e}"
                )
                continue

        return sessions

    def export(self, filename: Optional[str] = None) -> Path:
        """Export conversation to a markdown file.

        Args:
            filename: Optional filename (auto-generated if not provided)

        Returns:
            Path to exported file
        """
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"conversation_{timestamp}.md"

        filepath = self.exports_dir / filename

        # Build markdown content
        content = f"# Conversation Export\n\n"
        content += f"**Exported:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        content += f"**Session:** {self.session_name}\n"
        if self.metadata.get("model"):
            content += f"**Model:** {self.metadata['model']}\n"
        content += f"**Messages:** {len(self.messages)}\n\n"

        # Add usage stats
        usage = self.get_usage()
        content += f"## Usage Statistics\n\n"
        content += f"- Total Tokens: {usage['total_tokens']:,}\n"
        content += f"- Prompt Tokens: {usage['prompt_tokens']:,}\n"
        content += f"- Completion Tokens: {usage['completion_tokens']:,}\n"
        content += f"- Estimated Cost: ${usage['estimated_cost']:.4f}\n\n"

        content += "---\n\n"

        # Add conversation
        content += "## Conversation\n\n"
        for msg in self.messages:
            role = msg.role.capitalize()
            content += f"### {role}\n\n{msg.text_content()}\n\n"

        # Write to file
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        return filepath

    def delete_session(self, name: str) -> bool:
        """Delete a saved session.

        Args:
            name: Session name to delete

        Returns:
            True if deleted successfully

        v1.17.4: Handles both flat-file and directory-format sessions.
        Removes the entire directory (including uploads/) for multimodal
        sessions — shutil.rmtree rather than unlink so no orphaned
        attachment files are left behind.
        """
        dir_path = self.sessions_dir / name
        flat_path = self.sessions_dir / f"{name}.json"
        deleted = False

        if dir_path.is_dir():
            try:
                shutil.rmtree(dir_path)
                deleted = True
            except OSError as exc:
                logger.warning(f"Failed to remove session directory {dir_path}: {exc}")

        if flat_path.is_file():
            try:
                flat_path.unlink()
                deleted = True
            except OSError as exc:
                logger.warning(f"Failed to remove session file {flat_path}: {exc}")

        return deleted

    def save_usage_to_persistent_storage(self):
        """Save session usage to persistent storage (v1.12.3).

        Called when session ends (exit, /clear, etc.) to persist usage data
        across sessions for time-based analytics.
        """
        # Skip if no usage
        if self.usage.total_tokens == 0 and self.usage.estimated_cost == 0.0:
            return

        # Convert UsageStats to dict format for persistence
        usage_by_model = {
            key: {
                "prompt_tokens": stats.prompt_tokens,
                "completion_tokens": stats.completion_tokens,
                "estimated_cost": stats.estimated_cost
            }
            for key, stats in self.usage_by_model.items()
        }

        # Parse created_at from metadata or use current time
        try:
            started_at = datetime.fromisoformat(self.metadata.get("created_at", datetime.now().isoformat()))
        except ValueError:
            started_at = datetime.now()

        # Convert tool usage to dict format for persistence (v1.16.0)
        tool_calls = {}
        for tool_name, tool_usage in self.usage.tool_calls.items():
            tool_calls[tool_name] = {
                "call_count": tool_usage.call_count,
                "tokens_in": tool_usage.tokens_in,
                "tokens_out": tool_usage.tokens_out,
                "estimated_cost": tool_usage.estimated_cost,
                "provider": tool_usage.provider,
            }

        save_session_usage(
            session_id=self.session_name,
            started_at=started_at,
            ended_at=datetime.now(),
            usage_by_model=usage_by_model,
            total_cost=self.usage.estimated_cost,
            total_tokens=self.usage.total_tokens,
            message_count=len(self.messages),
            tool_calls=tool_calls,
        )

    # =========================================================================
    # Session State File Management
    # =========================================================================

    def add_to_history(self, command: str):
        """Add a command to the session's command history.

        Args:
            command: User input to add to history
        """
        if command and command.strip():
            self.command_history.append(command.strip())

    def set_working_dir(self, path: str):
        """Set the working directory for this session.

        Args:
            path: Working directory path
        """
        self.working_dir = path

    def save_dirty(self) -> str:
        """Save session and mark it as dirty (unsaved changes).

        This is called after each roundtrip to keep the session file synced.

        Returns:
            Session name
        """
        # Save the session file
        self._save_with_extras()

        # Update state file to mark session as dirty
        self._update_state_file(dirty=True)

        self._dirty = True
        self._was_dirty = True
        return self.session_name

    def mark_clean(self):
        """Mark session as clean (graceful exit).

        Called when the application exits gracefully to indicate
        the session was properly saved.
        Updates the state file only when this session has messages OR was
        previously marked dirty — otherwise the previous meaningful session's
        pointer is preserved.
        """
        self._dirty = False
        if self.messages or self._was_dirty:
            self._update_state_file(dirty=False)

    def _save_with_extras(self) -> str:
        """Save session with command history and working directory.

        Internal method that saves the full session data including
        command_history, working_dir, and tools_enabled fields.

        v1.17.4: Routes through `_write_session_json` so auto-saves
        (save_dirty) honor the dual flat/directory format rules — a
        session that gains its first attachment mid-conversation will
        auto-migrate to directory layout on the very next dirty save.

        Returns:
            Session name
        """
        session_data = {
            "session_name": self.session_name,
            "metadata": self.metadata,
            "messages": [self._serialize_message(m) for m in self.messages],
            "usage": self.get_usage(),
            "saved_at": datetime.now().isoformat(),
            # New fields
            "command_history": self.command_history,
            "working_dir": self.working_dir,
            "tools_enabled": self.tools_enabled
        }

        self._write_session_json(self.session_name, session_data)
        return self.session_name

    def _update_state_file(self, dirty: bool):
        """Update the session state file.

        Args:
            dirty: Whether the session has unsaved changes
        """
        # Ensure parent directory exists
        SESSION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

        state_data = {
            "version": 1,
            "last_session": {
                "name": self.session_name,
                "dirty": dirty,
                "provider": self.metadata.get("provider"),
                "model": self.metadata.get("model"),
                "working_dir": self.working_dir,
                "tools_enabled": self.tools_enabled,
                "message_count": len(self.messages)
            },
            "updated_at": datetime.now().isoformat()
        }

        with open(SESSION_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state_data, f, indent=2)

    @staticmethod
    def get_last_session_state() -> Optional[Dict[str, Any]]:
        """Get the last session state from the state file.

        Returns:
            Dictionary with last session info, or None if no state file exists
        """
        if not SESSION_STATE_FILE.exists():
            return None

        try:
            with open(SESSION_STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data.get("last_session")
        except Exception as e:
            logger.debug(f"State file read failed: {e}")
            return None

    @staticmethod
    def clear_state_file():
        """Clear the session state file.

        Called when starting a fresh session to prevent auto-restore.
        """
        if SESSION_STATE_FILE.exists():
            SESSION_STATE_FILE.unlink()

    @staticmethod
    def find_most_recent_session_on_disk() -> Optional[Dict[str, Any]]:
        """Scan ~/.ppxai/sessions/ for the newest session and return its info.

        Fallback path when `session-state.json` is missing or corrupt but
        saved sessions still exist on disk (either because the state file
        was cleared externally, lost to a crash before save, or the
        pointer was never written — see v1.17.4 investigation notes
        around session_20260412_192249 for a real occurrence).

        Considers both formats:
          * flat: `sessions/<name>.json`
          * directory: `sessions/<name>/session.json`

        Returns a dict with the same shape as `get_last_session_state()`
        so callers can use it interchangeably, plus:
          * `"recovered_from_disk": True` — lets clients distinguish
            fallback recovery from normal auto-restore and surface a
            slightly different prompt ("State pointer missing — restore
            most recent session?").

        Returns:
            Dict with session info, or None if no sessions on disk.
        """
        sessions_dir = Path.home() / ".ppxai" / "sessions"
        if not sessions_dir.is_dir():
            return None

        best_path: Optional[Path] = None
        best_mtime: float = -1.0
        best_name: str = ""
        try:
            for entry in sessions_dir.iterdir():
                # Flat format: sessions/<name>.json
                if entry.is_file() and entry.suffix == ".json":
                    name = entry.stem
                    mtime = entry.stat().st_mtime
                    if mtime > best_mtime:
                        best_mtime = mtime
                        best_path = entry
                        best_name = name
                # Directory format: sessions/<name>/session.json
                elif entry.is_dir():
                    candidate = entry / "session.json"
                    if candidate.is_file():
                        name = entry.name
                        mtime = candidate.stat().st_mtime
                        if mtime > best_mtime:
                            best_mtime = mtime
                            best_path = candidate
                            best_name = name
        except Exception as e:
            logger.debug(f"Sessions dir scan failed: {e}")
            return None

        if best_path is None or not best_name:
            return None

        # Read minimal metadata from the session file so callers can
        # render the same prompt content ("<N> messages, provider: X").
        # Any field that's missing or unreadable falls back to a sane
        # default so the caller never has to defend against KeyError.
        try:
            with open(best_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.debug(f"Session file read failed for scan fallback: {e}")
            return None

        metadata = data.get("metadata", {}) or {}
        messages = data.get("messages", []) or []

        return {
            "name": best_name,
            "dirty": False,  # by definition — if dirty, state file would exist
            "provider": metadata.get("provider"),
            "model": metadata.get("model"),
            "working_dir": data.get("working_dir") or metadata.get("working_dir"),
            "tools_enabled": data.get("tools_enabled", False),
            "message_count": len(messages),
            "recovered_from_disk": True,
        }

    @staticmethod
    def get_last_session_state_or_scan() -> Optional[Dict[str, Any]]:
        """Return the last-session pointer, falling back to disk scan.

        Primary path: `get_last_session_state()` — reads the pointer file.
        Fallback path: when the pointer is missing, scan the sessions
        directory for the newest saved session. This recovers gracefully
        from state-file loss that would otherwise silently orphan a
        session from its restore prompt.

        The returned dict is shape-compatible with `get_last_session_state()`.
        If the dict was produced by the fallback, it carries an extra
        `"recovered_from_disk": True` flag so clients can adjust the
        prompt wording.

        Returns:
            Session state dict, or None if neither path finds anything.
        """
        state = SessionManager.get_last_session_state()
        if state:
            return state
        return SessionManager.find_most_recent_session_on_disk()

