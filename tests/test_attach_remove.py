"""Tests for /attach remove subcommand and remove_context_attachment.

Phase 2.1b (v1.17.4). The counterpart to `/attach clear`: clear drops
the pre-send staging buffer, remove evicts already-committed attachments
from session history so they stop being re-sent (and re-billed) on
every subsequent turn.

Scope:
    EngineClient.remove_context_attachment
        - Single attachment by name across one user turn
        - Single attachment by name across multiple user turns (all removed)
        - `all` literal evicts every attachment
        - Tool / assistant / system turn multimodal content is NOT touched
          (role filter matches _refresh_context_attachments semantics)
        - Message with nothing-but-attachment content gets a text
          placeholder so alternation stays valid
        - No-match returns 0 without mutating session
        - Empty arg returns 0
        - AppState context_attachments refreshed via on_messages_changed

    /attach remove command surface
        - /attach remove <name> success
        - /attach remove all success
        - /attach remove with no arg → usage error
        - /attach remove unknown → warning listing current attachments
        - Listing shows both staging and in-context sections
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

from ppxai.commands.attach import handle_attach
from ppxai.commands.results import ResultStatus
from ppxai.engine.client import EngineClient
from ppxai.engine.types import Message


# Real 1x1 red PNG — survives magic-byte validation in build_multimodal_content.
_RED_PIXEL_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8DwHwAFAQH/c4"
    b"X0gAAAAABJRU5ErkJggg=="
)
_RED_DATA_URI = f"data:image/png;base64,{base64.b64encode(_RED_PIXEL_PNG).decode('ascii')}"

_BLUE_DATA_URI = f"data:image/png;base64,{base64.b64encode(b'different').decode('ascii')}"


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """Fresh EngineClient with session dir and store redirected into tmp_path."""
    import ppxai.engine.session_store as store_mod
    monkeypatch.setattr(store_mod, "_DEFAULT_STAGING_DIR", tmp_path / "staging")
    (tmp_path / "staging").mkdir()

    client = EngineClient()
    client.session.sessions_dir = tmp_path / "sessions"
    client.session.sessions_dir.mkdir(parents=True, exist_ok=True)
    return client


def _image_block(name: str, url: str = _RED_DATA_URI) -> dict:
    return {
        "type": "image_url",
        "name": name,
        "image_url": {"url": url},
    }


# -----------------------------------------------------------------------------
# EngineClient.remove_context_attachment — engine-level API
# -----------------------------------------------------------------------------


class TestRemoveContextAttachment:
    def test_removes_single_attachment_from_one_turn(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[
                {"type": "text", "text": "describe"},
                _image_block("chart.png"),
            ],
        ))
        engine.session.add_message(Message(role="assistant", content="done"))

        assert len(engine.get_context_attachments()) == 1
        removed = engine.remove_context_attachment("chart.png")
        assert removed == 1

        # AppState refreshed via on_messages_changed — list now empty.
        assert engine.get_context_attachments() == []
        # User message still has the text, just not the image.
        user_msg = engine.session.messages[0]
        assert len(user_msg.content) == 1
        assert user_msg.content[0]["type"] == "text"

    def test_removes_attachment_across_multiple_turns(self, engine):
        # Same named attachment reattached on two separate user turns
        # (common pattern: user refers back to the original image).
        for _ in range(2):
            engine.session.add_message(Message(
                role="user",
                content=[
                    {"type": "text", "text": "still about the chart"},
                    _image_block("chart.png"),
                ],
            ))
            engine.session.add_message(Message(role="assistant", content="ok"))

        removed = engine.remove_context_attachment("chart.png")
        # Both occurrences should be dropped.
        assert removed == 2
        assert engine.get_context_attachments() == []
        # Both user messages retain their text parts.
        for msg in engine.session.messages:
            if msg.role == "user":
                assert any(b.get("type") == "text" for b in msg.content)

    def test_remove_all_evicts_every_attachment(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[
                _image_block("a.png", _RED_DATA_URI),
                _image_block("b.png", _BLUE_DATA_URI),
            ],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        engine.session.add_message(Message(
            role="user",
            content=[_image_block("c.png", _RED_DATA_URI)],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))

        assert len(engine.get_context_attachments()) >= 2

        removed = engine.remove_context_attachment("all")
        assert removed == 3  # a, b, c
        assert engine.get_context_attachments() == []

    def test_no_match_returns_zero(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[_image_block("existing.png")],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))

        removed = engine.remove_context_attachment("nonexistent.png")
        assert removed == 0
        # Session untouched.
        assert len(engine.get_context_attachments()) == 1

    def test_empty_name_returns_zero(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[_image_block("chart.png")],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))

        assert engine.remove_context_attachment("") == 0
        assert len(engine.get_context_attachments()) == 1

    def test_tool_and_assistant_multimodal_not_touched(self, engine):
        # Role filter: only user-turn content parts get evicted. An
        # assistant turn that (hypothetically) carries inline image
        # content must remain untouched — otherwise the model's prior
        # output gets silently rewritten.
        engine.session.add_message(Message(
            role="user",
            content=[_image_block("user_photo.png")],
        ))
        engine.session.add_message(Message(
            role="assistant",
            content=[
                {"type": "text", "text": "here's what I see"},
                _image_block("assistant_render.png"),  # hypothetical tool output
            ],
        ))
        engine.session.add_message(Message(
            role="tool",
            tool_call_id="call_1",
            content=[_image_block("tool_output.png")],
        ))

        # "all" should remove ONLY the user-turn attachment.
        removed = engine.remove_context_attachment("all")
        assert removed == 1
        # Assistant and tool multimodal content still intact.
        assert any(
            isinstance(b, dict) and b.get("name") == "assistant_render.png"
            for b in engine.session.messages[1].content
        )
        assert engine.session.messages[2].content[0]["name"] == "tool_output.png"

    def test_empty_user_message_gets_text_placeholder(self, engine):
        # A user message whose content was ONLY an attachment — after
        # removal, the list would be empty which would violate message
        # alternation. Dispatcher injects a placeholder text part.
        engine.session.add_message(Message(
            role="user",
            content=[_image_block("lonely.png")],  # no text part
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))

        removed = engine.remove_context_attachment("lonely.png")
        assert removed == 1
        msg = engine.session.messages[0]
        assert len(msg.content) == 1
        assert msg.content[0]["type"] == "text"
        assert "lonely.png" in msg.content[0]["text"]
        assert "removed" in msg.content[0]["text"].lower()

    def test_listener_fires_on_removal(self, engine):
        received: list = []
        engine.state.on("context_attachments", lambda v: received.append(v))

        engine.session.add_message(Message(
            role="user",
            content=[_image_block("chart.png")],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))
        received.clear()  # discard the add-message notification

        engine.remove_context_attachment("chart.png")

        # Exactly one state_sync event from the removal.
        assert len(received) == 1
        assert received[0] == []  # empty list after eviction


# -----------------------------------------------------------------------------
# /attach remove command surface
# -----------------------------------------------------------------------------


class TestAttachRemoveCommand:
    def _make_context(self, engine: EngineClient, pending_files=None):
        return SimpleNamespace(
            engine_client=engine,
            session=engine.session,
            working_dir=engine.session.working_dir,
            pending_files=pending_files or [],
            _wrapped=None,
        )

    def test_remove_by_name_success(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[
                {"type": "text", "text": "describe"},
                _image_block("chart.png"),
            ],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))

        ctx = self._make_context(engine)
        result = handle_attach(ctx, "remove chart.png")
        assert result.status == ResultStatus.SUCCESS
        assert "Removed 1" in result.message
        assert "chart.png" in result.message
        assert engine.get_context_attachments() == []

    def test_remove_all_command(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[
                _image_block("a.png", _RED_DATA_URI),
                _image_block("b.png", _BLUE_DATA_URI),
            ],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))

        ctx = self._make_context(engine)
        result = handle_attach(ctx, "remove all")
        assert result.status == ResultStatus.SUCCESS
        assert "Removed 2" in result.message
        assert "across all turns" in result.message
        assert engine.get_context_attachments() == []

    def test_remove_without_argument_errors(self, engine):
        ctx = self._make_context(engine)
        result = handle_attach(ctx, "remove")
        assert result.status == ResultStatus.ERROR
        assert "Missing argument" in result.message
        assert "/attach remove <name>" in result.message

    def test_remove_unknown_name_warns_with_available(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[_image_block("real.png")],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))

        ctx = self._make_context(engine)
        result = handle_attach(ctx, "remove ghost.png")
        assert result.status == ResultStatus.WARNING
        assert "ghost.png" in result.message
        # Lists currently-attached names so the user can retry.
        assert "real.png" in result.message
        # Session untouched.
        assert len(engine.get_context_attachments()) == 1

    def test_remove_when_no_attachments(self, engine):
        ctx = self._make_context(engine)
        result = handle_attach(ctx, "remove something.png")
        assert result.status == ResultStatus.INFO
        assert "No attachments currently in context" in result.message

    def test_listing_shows_in_context_section(self, engine):
        engine.session.add_message(Message(
            role="user",
            content=[_image_block("from_history.png")],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))

        ctx = self._make_context(engine)
        result = handle_attach(ctx, "")
        # New dual-section layout.
        assert "In context" in result.message
        assert "from_history.png" in result.message
        assert "re-sent every turn" in result.message
        # Hint points at the removal subcommand.
        assert "/attach remove" in result.message

    def test_listing_shows_both_sections_when_staging_and_context_present(
        self, engine, tmp_path
    ):
        # In-context attachment from a prior turn...
        engine.session.add_message(Message(
            role="user",
            content=[_image_block("old.png")],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))

        # ...plus a new staged file.
        from ppxai.commands.attach import PendingFile
        staged = PendingFile(
            name="new.png",
            path="/tmp/new.png",
            media_type="image/png",
            size=len(_RED_PIXEL_PNG),
            kind="image",
            data=_RED_PIXEL_PNG,
        )
        ctx = self._make_context(engine, pending_files=[staged])
        result = handle_attach(ctx, "")

        assert "Staged" in result.message
        assert "In context" in result.message
        assert "new.png" in result.message
        assert "old.png" in result.message
