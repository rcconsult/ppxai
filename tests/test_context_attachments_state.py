"""Tests for AppState.context_attachments (multimodal tracking, v1.17.4).

Verifies the full pipeline:
    session.messages mutation
        → SessionManager.on_messages_changed callback
        → EngineClient._refresh_context_attachments
        → AppState.context_attachments field
        → EngineClient.get_context_attachments() public API

This is the shared surface every client (Rich/Textual/Web/VSCode) reads from,
so bugs here ripple everywhere. Tests exercise every mutation entry point
(add_message, remove_last_message, clear, load, strip_to_user_messages)
plus the dedup-by-name contract and the JSON-schema stability of entries.
"""

from __future__ import annotations

import json

import pytest

from ppxai.engine.app_state import AppState
from ppxai.engine.client import EngineClient
from ppxai.engine.session import SessionManager
from ppxai.engine.types import Message

# -----------------------------------------------------------------------------
# AppState field exists and has the documented shape
# -----------------------------------------------------------------------------


class TestAppStateFieldDefinition:
    def test_field_defaults_to_empty_list(self):
        state = AppState()
        assert state.get("context_attachments") == []

    def test_field_is_settable(self):
        state = AppState()
        changed = state.set("context_attachments", [{"name": "a.png", "kind": "image"}])
        assert changed is True
        assert state.get("context_attachments") == [{"name": "a.png", "kind": "image"}]

    def test_field_set_short_circuits_on_equal_value(self):
        state = AppState()
        entry = [{"name": "a.png", "kind": "image", "media_type": "image/png", "turn_index": 0}]
        assert state.set("context_attachments", entry) is True
        # Same list value — should be detected as no-op.
        assert state.set("context_attachments", list(entry)) is False

    def test_field_listener_receives_new_value(self):
        state = AppState()
        received: list = []
        state.on("context_attachments", lambda v: received.append(v))
        state.set("context_attachments", [{"name": "x.png"}])
        assert received == [[{"name": "x.png"}]]


# -----------------------------------------------------------------------------
# EngineClient wiring — callback fires on every session mutation
# -----------------------------------------------------------------------------


@pytest.fixture
def engine():
    """Fresh EngineClient — don't rely on provider/model being configured."""
    return EngineClient()


class TestEngineRefreshWiring:
    def test_initial_snapshot_is_empty(self, engine):
        assert engine.get_context_attachments() == []
        assert engine.state.get("context_attachments") == []

    def test_add_message_with_image_updates_state(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[
                {"type": "text", "text": "what is this?"},
                {"type": "image_url", "name": "chart.png",
                 "image_url": {"url": "data:image/png;base64,AA"}},
            ],
        ))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 1
        entry = attachments[0]
        # Stable schema — all four keys must be present.
        assert entry["name"] == "chart.png"
        assert entry["kind"] == "image"
        assert entry["media_type"] == "image/png"
        assert entry["turn_index"] == 0

    def test_media_type_extracted_from_data_uri(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "image_url", "name": "photo.jpg",
                      "image_url": {"url": "data:image/jpeg;base64,XX"}}],
        ))
        entry = engine.get_context_attachments()[0]
        assert entry["media_type"] == "image/jpeg"

    def test_text_only_message_adds_nothing(self, engine):
        engine.session.add_message(Message(role="user", content="plain text"))
        engine.session.add_message(Message(role="assistant", content="reply"))
        assert engine.get_context_attachments() == []

    def test_multiple_images_across_turns_all_tracked(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "image_url", "name": "a.png",
                      "image_url": {"url": "data:image/png;base64,AA"}}],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "image_url", "name": "b.png",
                      "image_url": {"url": "data:image/png;base64,BB"}}],
        ))
        attachments = engine.get_context_attachments()
        assert [e["name"] for e in attachments] == ["a.png", "b.png"]
        # turn_index reflects position in session.messages, not user-turn count.
        assert attachments[0]["turn_index"] == 0
        assert attachments[1]["turn_index"] == 2

    def test_same_file_id_deduped(self, engine):
        # Same attachment (same file_id) re-sent on two turns → single entry.
        # Content-addressed dedup: identity is the file_id, not the name.
        for _ in range(2):
            engine.session.add_message(Message(
                role="user",
                content=[{
                    "type": "image_url",
                    "name": "chart.png",
                    "file_id": "sha256:abc123",
                    "image_url": {"url": "data:image/png;base64,AA"},
                }],
            ))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 1

    def test_same_name_different_file_ids_not_deduped(self, engine):
        # Two different files that happen to share a display name (e.g.
        # two `chart.png` from different directories) must surface as
        # TWO badges, not one. Silent collapse was the R7 bug.
        engine.session.add_message(Message(
            role="user",
            content=[{
                "type": "image_url",
                "name": "chart.png",
                "file_id": "sha256:aaa",
                "image_url": {"url": "data:image/png;base64,AA"},
            }],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        engine.session.add_message(Message(
            role="user",
            content=[{
                "type": "image_url",
                "name": "chart.png",
                "file_id": "sha256:bbb",
                "image_url": {"url": "data:image/png;base64,BB"},
            }],
        ))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 2
        assert {a["file_id"] for a in attachments} == {"sha256:aaa", "sha256:bbb"}

    def test_empty_file_id_not_collapsed_by_name(self, engine):
        # Two legacy blocks with empty file_id + same name are distinct
        # from the user's perspective. Don't silently dedup them.
        for _ in range(2):
            engine.session.add_message(Message(
                role="user",
                content=[{"type": "image_url", "name": "chart.png",
                          "image_url": {"url": "data:image/png;base64,AA"}}],
            ))
            engine.session.add_message(Message(role="assistant", content="ok"))
        attachments = engine.get_context_attachments()
        assert len(attachments) == 2

    def test_remove_last_message_refreshes(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "image_url", "name": "tmp.png",
                      "image_url": {"url": "data:image/png;base64,AA"}}],
        ))
        assert len(engine.get_context_attachments()) == 1
        engine.session.remove_last_message()
        assert engine.get_context_attachments() == []

    def test_clear_refreshes_to_empty(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "image_url", "name": "x.png",
                      "image_url": {"url": "data:image/png;base64,AA"}}],
        ))
        assert engine.get_context_attachments()
        engine.session.clear()
        assert engine.get_context_attachments() == []

    def test_reset_for_model_switch_refreshes_state(self, engine):
        # `reset_for_model_switch` strips assistant turns and then runs
        # `validate_and_fix_alternation`, which can further pop trailing user
        # messages. We don't care about the exact surviving set here — we
        # care that AppState ends up *consistent with* session.messages
        # after the operation, so the callback chain fired correctly.
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "image_url", "name": "keep.png",
                      "image_url": {"url": "data:image/png;base64,AA"}}],
        ))
        engine.session.add_message(Message(role="assistant", content="answer"))
        assert len(engine.get_context_attachments()) == 1

        engine.session.reset_for_model_switch()

        # Recompute expected set directly from session.messages and compare
        # with what AppState reports. They must agree — that's the whole
        # point of wiring on_messages_changed.
        expected_names = set()
        for msg in engine.session.messages:
            if isinstance(msg.content, list):
                for block in msg.content:
                    if isinstance(block, dict) and block.get("type") == "image_url":
                        expected_names.add(block.get("name") or "image")
        actual_names = {e["name"] for e in engine.get_context_attachments()}
        assert actual_names == expected_names

    def test_tool_generated_images_are_not_tracked(self, engine):
        """Role filter: tool-returned images don't pollute context_attachments.

        Phase 2.8 (PDF tools) and Phase 4 (Excel chart render) return
        rasterized PNGs via tool calls. Those images show up in assistant
        or tool role messages — they should NEVER appear in the user-facing
        attachment badge, which represents "what the user attached" and
        not "every multimodal artifact in history." This test pins the
        invariant so Phase 2.8 implementation can't accidentally violate it.
        """
        # Simulate a conversation where:
        #   1. user attaches a real image
        #   2. assistant makes a tool call that returns a PDF page image
        #   3. tool role message carries the rasterized PDF page as image_url
        engine.session.add_message(Message(
            role="user",
            content=[
                {"type": "text", "text": "analyze this chart"},
                {"type": "image_url", "name": "chart.png",
                 "image_url": {"url": "data:image/png;base64,AA"}},
            ],
        ))
        engine.session.add_message(Message(
            role="assistant",
            content=[
                {"type": "text", "text": "Let me also check the PDF."},
                # Hypothetical Phase 2.8 shape: assistant message with
                # inline tool-generated image (e.g., from agent-mode loop
                # that rendered a PDF page mid-response).
                {"type": "image_url", "name": "pdf_page_3.png",
                 "image_url": {"url": "data:image/png;base64,BB"}},
            ],
        ))
        engine.session.add_message(Message(
            role="tool",
            tool_call_id="call_1",
            content=[
                {"type": "image_url", "name": "excel_chart.png",
                 "image_url": {"url": "data:image/png;base64,CC"}},
            ],
        ))

        attachments = engine.get_context_attachments()
        # Only the user-attached chart.png should be visible.
        assert len(attachments) == 1
        assert attachments[0]["name"] == "chart.png"
        # Tool / assistant images are deliberately excluded.
        names = {a["name"] for a in attachments}
        assert "pdf_page_3.png" not in names
        assert "excel_chart.png" not in names

    def test_system_messages_with_list_content_are_not_tracked(self, engine):
        # Defensive: a system message with multimodal content (unusual but
        # not impossible — e.g., some provider-specific system prompt
        # injection) must also be excluded by the role filter.
        engine.session.messages.append(Message(
            role="system",
            content=[
                {"type": "image_url", "name": "logo.png",
                 "image_url": {"url": "data:image/png;base64,AA"}},
            ],
        ))
        # Manually trigger refresh since we bypassed add_message's callback
        # to install the message directly.
        engine._refresh_context_attachments()
        assert engine.get_context_attachments() == []

    def test_get_context_attachments_returns_fresh_copy(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "image_url", "name": "a.png",
                      "image_url": {"url": "data:image/png;base64,AA"}}],
        ))
        first = engine.get_context_attachments()
        first.append({"name": "hacked.png"})  # Caller mutation
        # Second call should not reflect the external mutation.
        second = engine.get_context_attachments()
        assert len(second) == 1
        assert second[0]["name"] == "a.png"


# -----------------------------------------------------------------------------
# Observability — listeners on the field fire on every relevant mutation
# -----------------------------------------------------------------------------


class TestListenerDispatch:
    def test_listener_fires_on_add_message(self, engine):
        received: list = []
        engine.state.on("context_attachments", lambda v: received.append(v))
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "image_url", "name": "a.png",
                      "image_url": {"url": "data:image/png;base64,AA"}}],
        ))
        assert len(received) == 1
        assert received[0][0]["name"] == "a.png"

    def test_listener_does_not_fire_for_text_only_turns(self, engine):
        # Text-only messages don't change the attachment list, so AppState's
        # equality-dedup must prevent a redundant listener call. This
        # matters for SSE: we don't want to spam state_sync events for
        # every token.
        engine.session.add_message(Message(
            role="user",
            content=[{"type": "image_url", "name": "a.png",
                      "image_url": {"url": "data:image/png;base64,AA"}}],
        ))
        received: list = []
        engine.state.on("context_attachments", lambda v: received.append(v))
        # Add a text-only turn — attachments unchanged.
        engine.session.add_message(Message(role="assistant", content="hi"))
        engine.session.add_message(Message(role="user", content="more?"))
        assert received == []


# -----------------------------------------------------------------------------
# JSON-serializability — every entry must survive round-trip through SSE
# -----------------------------------------------------------------------------


class TestJsonSerializability:
    def test_entries_are_json_roundtrippable(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[
                {"type": "text", "text": "q"},
                {"type": "image_url", "name": "chart.png",
                 "image_url": {"url": "data:image/png;base64,AA"}},
            ],
        ))
        entries = engine.get_context_attachments()
        # Must survive a JSON round-trip unchanged — this is the contract
        # for state_sync / SSE / web-client / vscode-client consumption.
        dumped = json.dumps(entries)
        assert json.loads(dumped) == entries


# -----------------------------------------------------------------------------
# SessionManager callback is resilient to listener errors
# -----------------------------------------------------------------------------


class TestCallbackResilience:
    def test_exception_in_listener_does_not_crash_session(self):
        session = SessionManager()

        def angry_listener() -> None:
            raise RuntimeError("boom")

        session.on_messages_changed = angry_listener
        # Should log a warning and continue; session itself stays consistent.
        session.add_message(Message(role="user", content="hi"))
        assert len(session.messages) == 1

    def test_missing_callback_is_noop(self):
        # Default is None — every mutation must still work.
        session = SessionManager()
        session.add_message(Message(role="user", content="hi"))
        session.clear()
        assert session.messages == []


# -----------------------------------------------------------------------------
# ADR 0006 Phase 2b — scan_attachments reads via Message.resolve_attachment
# -----------------------------------------------------------------------------
# These sentinels pin the new code path so a future regression doesn't
# silently fall back to the legacy in-block-key read. The scanner is the
# producer of the AppState `context_attachments` field that 3 client
# surfaces (web, vscode, both TUIs) consume — drift here = wrong file
# in user-visible badges.


class TestScanAttachmentsUsesImageAttachmentRef:
    def test_uses_attachment_ref_name_when_populated(self, engine):
        """When Message.attachments carries a name, the scanner uses it
        even if the in-block `name` differs. Phase 3 will drop the
        in-block name entirely; until then it must be IGNORED when
        ImageAttachmentRef is present."""
        from ppxai.engine.types import ImageAttachmentRef
        engine.session.add_message(Message(
            role="user",
            content=[
                {"type": "text", "text": "look:"},
                {"type": "image_url", "name": "stale-in-block.png",
                 "file_id": "sha:stalefromblock",
                 "image_url": {"url": "data:image/png;base64,X"}},
            ],
            attachments=[
                ImageAttachmentRef(block_index=1, name="authoritative.png",
                              file_id="sha:authoritative", media_type="image/png"),
            ],
        ))
        entries = engine.get_context_attachments()
        assert len(entries) == 1
        assert entries[0]["name"] == "authoritative.png"
        assert entries[0]["file_id"] == "sha:authoritative"

    def test_block_index_correctness_on_mixed_content(self, engine):
        """Mixed-content message (text + image + text + image) — both
        ImageAttachmentRefs must point at the correct image blocks. If
        block_index is computed wrong (e.g. counting only image_url
        blocks instead of all blocks), the wrong ImageAttachmentRef would
        match and the scanner would return swapped names.
        """
        from ppxai.engine.types import ImageAttachmentRef
        engine.session.add_message(Message(
            role="user",
            content=[
                {"type": "text", "text": "before"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,A"}},
                {"type": "text", "text": "between"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,B"}},
                {"type": "text", "text": "after"},
            ],
            attachments=[
                ImageAttachmentRef(block_index=1, name="first.png",
                              file_id="sha:1", media_type="image/png"),
                ImageAttachmentRef(block_index=3, name="second.png",
                              file_id="sha:2", media_type="image/png"),
            ],
        ))
        entries = engine.get_context_attachments()
        assert len(entries) == 2
        # Order matches block iteration order, not attachment-list order.
        assert entries[0]["name"] == "first.png"
        assert entries[0]["file_id"] == "sha:1"
        assert entries[1]["name"] == "second.png"
        assert entries[1]["file_id"] == "sha:2"

    def test_legacy_messages_without_attachments_still_work(self, engine):
        """Pre-Phase-1 messages have empty attachments. The scanner
        falls back via resolve_attachment's in-block-key synthesis
        branch so legacy fixtures + sessions loaded by old builds
        keep working."""
        engine.session.add_message(Message(
            role="user",
            content=[
                {"type": "image_url", "name": "legacy.png",
                 "file_id": "sha:legacy",
                 "image_url": {"url": "data:image/png;base64,X"}},
            ],
            # attachments deliberately empty
        ))
        entries = engine.get_context_attachments()
        assert len(entries) == 1
        assert entries[0]["name"] == "legacy.png"
        assert entries[0]["file_id"] == "sha:legacy"
