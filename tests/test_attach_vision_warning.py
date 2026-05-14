"""v1.18.6 — proactive warning when an image is attached to a non-vision model.

Three concerns covered:

1. **`/attach` proactive warning** (TUI + Rich/Textual + web `/attach` command):
   when the user stages an image AND the active model has
   `supports_vision=False`, `handle_attach` appends a `⚠`-prefixed line
   to its result message. Catches the silent-drop trap before the user
   wastes a turn on a confused model response.

2. **Server `_build_chat_payload` warning collection**: when the user sends
   an image attachment via `POST /chat`, `_build_chat_payload` now returns
   a `(payload, warnings)` tuple. Per-attachment warnings of shape
   `{type, severity, message, suggested_action, details}` are emitted as
   `Event(EventType.WARNING, ...)` BEFORE the chat starts. The web /
   VSCode clients render these via their existing validator-warning
   shape (no new renderer needed — payload mirrors v1.15.2's shape).

3. **Non-image attachments stay silent**: PDF / Excel / code never trigger
   a vision warning regardless of model. The vision branch fires only
   when `media_type.startswith("image/")` AND model lacks vision.

Sentinel coverage so this contract doesn't drift as Phase 1-4 of
ADR 0006 land. The schema refactor reorganizes Message.attachments but
must NOT change the warning surface — tests pin the user-visible
behavior independent of the internal storage.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

import pytest

from ppxai.commands.attach import PendingFile, handle_attach
from ppxai.commands.results import ResultStatus


# Minimal 1x1 red PNG — same fixture used by test_attach_command.py.
_RED_PIXEL_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8DwHwAFAQH/c4"
    b"X0gAAAAABJRU5ErkJggg=="
)


# =============================================================================
# /attach proactive warning (TUI side, also web slash-command path)
# =============================================================================


def _make_engine_client(*, model: str, supports_vision: bool) -> Any:
    """Minimal stub exposing the `model` + `state.get('model_supports_vision')`
    surface that handle_attach reads. Bypasses real EngineClient setup so
    these tests stay fast (no provider config, no SSE, no session manager).
    """
    state = SimpleNamespace(
        get=lambda key, default=None: (
            supports_vision if key == "model_supports_vision" else default
        ),
    )
    return SimpleNamespace(
        model=model,
        state=state,
        file_store=None,
    )


@pytest.fixture
def ctx_with_vision_model(tmp_path) -> Any:
    """Context whose active model DOES support vision (gpt-5.5)."""
    return SimpleNamespace(
        working_dir=str(tmp_path),
        pending_files=[],
        engine_client=_make_engine_client(model="gpt-5.5", supports_vision=True),
        _wrapped=None,
    )


@pytest.fixture
def ctx_without_vision(tmp_path) -> Any:
    """Context whose active model does NOT support vision.

    Uses a deliberately fake model name so we don't depend on registry
    contents — the warning check goes through state.get(), not the
    profile lookup itself.
    """
    return SimpleNamespace(
        working_dir=str(tmp_path),
        pending_files=[],
        engine_client=_make_engine_client(
            model="text-only-model", supports_vision=False,
        ),
        _wrapped=None,
    )


@pytest.fixture
def ctx_no_engine(tmp_path) -> Any:
    """Context without an engine_client (test stub case). Warning logic
    must short-circuit silently — never crash on missing engine."""
    return SimpleNamespace(
        working_dir=str(tmp_path),
        pending_files=[],
        engine_client=None,
        _wrapped=None,
    )


class TestAttachProactiveVisionWarning:
    """Warning fires only when (image attached) AND (model lacks vision)."""

    def test_image_on_non_vision_model_appends_warning(self, ctx_without_vision, tmp_path):
        (tmp_path / "shot.png").write_bytes(_RED_PIXEL_PNG)
        result = handle_attach(ctx_without_vision, "shot.png")
        assert result.status == ResultStatus.SUCCESS
        assert "⚠" in result.message
        # Message names the file + the active model so users can act.
        assert "shot.png" in result.message
        assert "text-only-model" in result.message
        # Suggests at least one known vision-capable replacement.
        assert "vision-capable model" in result.message

    def test_image_on_vision_model_no_warning(self, ctx_with_vision_model, tmp_path):
        (tmp_path / "shot.png").write_bytes(_RED_PIXEL_PNG)
        result = handle_attach(ctx_with_vision_model, "shot.png")
        assert result.status == ResultStatus.SUCCESS
        assert "⚠" not in result.message
        assert "vision-capable model" not in result.message

    def test_text_attachment_silent_even_on_non_vision_model(
        self, ctx_without_vision, tmp_path,
    ):
        """PDFs, code, Excel — vision branch must NOT fire. Their failure
        mode (model can't summarize a PDF without read_pdf) is a different
        problem with a different remedy."""
        (tmp_path / "code.py").write_text("def f(): pass", encoding="utf-8")
        result = handle_attach(ctx_without_vision, "code.py")
        assert result.status == ResultStatus.SUCCESS
        assert "⚠" not in result.message

    def test_mixed_image_and_text_warning_only_about_image(
        self, ctx_without_vision, tmp_path,
    ):
        (tmp_path / "shot.png").write_bytes(_RED_PIXEL_PNG)
        (tmp_path / "code.py").write_text("def f(): pass", encoding="utf-8")
        result = handle_attach(ctx_without_vision, "shot.png code.py")
        assert result.status == ResultStatus.SUCCESS
        assert "⚠" in result.message
        # The warning names only the image, not the .py file.
        assert "shot.png" in result.message
        # The .py file is in the attachment list section but not the warning.
        warning_section_start = result.message.index("⚠")
        warning_section = result.message[warning_section_start:]
        assert "code.py" not in warning_section

    def test_no_engine_client_does_not_crash(self, ctx_no_engine, tmp_path):
        """Test stubs / bare contexts without engine_client must not raise.
        The warning is best-effort guidance, not a load-bearing check."""
        (tmp_path / "shot.png").write_bytes(_RED_PIXEL_PNG)
        result = handle_attach(ctx_no_engine, "shot.png")
        assert result.status == ResultStatus.SUCCESS
        # Warning skipped because we can't query model state — no crash.
        assert "⚠" not in result.message


# =============================================================================
# Server _build_chat_payload — vision warning collection on /chat
# =============================================================================


class TestBuildChatPayloadVisionWarning:
    """Server-side: chat route collects per-attachment vision warnings into
    a list the chat endpoint surfaces as `Event(EventType.WARNING, ...)`
    BEFORE the chat starts. Today's known sender for the WARNING event;
    future warning kinds (deprecation, throttle) reuse the same path.
    """

    def _make_engine(self, *, model: str = "", provider: str = "") -> Any:
        """Minimal engine stub for `_build_chat_payload`. Doesn't need a real
        SessionFileStore — payload-build is pure I/O on the message bytes."""
        return SimpleNamespace(
            model=model,
            provider_name=provider,
            file_store=None,
        )

    def _make_attachment(self, name: str, media_type: str, data_bytes: bytes) -> Any:
        return SimpleNamespace(
            name=name,
            media_type=media_type,
            data=base64.b64encode(data_bytes).decode("ascii"),
        )

    def test_returns_tuple(self):
        """`_build_chat_payload` must return `(payload, warnings, refs)`
        3-tuple after ADR 0006 Steps 2-3 (v1.18.6). Old callers expecting
        2-tuple or bare payload would silently break — sentinel."""
        from ppxai.server.routes.chat import _build_chat_payload
        result = _build_chat_payload("hello", [], self._make_engine())
        assert isinstance(result, tuple)
        assert len(result) == 3
        payload, warnings, refs = result
        assert payload == "hello"
        assert warnings == []
        assert refs == []

    def test_image_on_non_vision_model_emits_warning(self):
        from ppxai.server.routes.chat import _build_chat_payload
        engine = self._make_engine(model="text-only-model", provider="custom")
        attachment = self._make_attachment("shot.png", "image/png", _RED_PIXEL_PNG)

        payload, warnings, refs = _build_chat_payload("look at this", [attachment], engine)

        assert len(warnings) == 1
        w = warnings[0]
        # Schema mirrors web's existing validator-warning shape so the
        # same renderer handles both. See web/app.js::showValidationWarning.
        assert w["type"] == "vision_unsupported"
        assert w["severity"] == "warning"
        assert "shot.png" in w["message"]
        assert "text-only-model" in w["message"]
        assert "vision-capable" in w["suggested_action"]
        assert w["details"]  # non-empty for debugging
        # refs is empty here because text-only-model uses the placeholder
        # path which doesn't produce an attachment_ref.
        assert refs == []

    def test_image_on_vision_model_no_warning(self):
        """gpt-5.5 has supports_vision=True per registry — must not warn.
        ADR 0006 Step 2/3: producer pipeline produces ImageAttachmentRef
        in the refs list when vision-capable model accepts the image."""
        from ppxai.server.routes.chat import _build_chat_payload
        engine = self._make_engine(model="gpt-5.5", provider="openai")
        attachment = self._make_attachment("shot.png", "image/png", _RED_PIXEL_PNG)

        payload, warnings, refs = _build_chat_payload("look at this", [attachment], engine)

        assert warnings == []
        # ImageAttachmentRef populated for the accepted image
        assert len(refs) == 1
        assert refs[0].kind == "image"
        assert refs[0].name == "shot.png"

    def test_text_attachment_no_warning_regardless_of_model(self):
        """PDFs / code — vision branch only fires for image/* media types.
        ADR 0006 Step 2/3: TextAttachmentRef populated for text files."""
        from ppxai.server.routes.chat import _build_chat_payload
        engine = self._make_engine(model="text-only-model", provider="custom")
        attachment = self._make_attachment("notes.txt", "text/plain", b"hello world")

        payload, warnings, refs = _build_chat_payload("read this", [attachment], engine)

        assert warnings == []
        # TextAttachmentRef populated; text artifacts merge into combined-text block.
        assert len(refs) == 1
        assert refs[0].kind == "text"

    def test_multiple_images_one_warning_each(self):
        """Two images on a non-vision model → two warnings, each naming
        its own file. Lets the UI render them separately if it wants."""
        from ppxai.server.routes.chat import _build_chat_payload
        engine = self._make_engine(model="text-only-model", provider="custom")
        a1 = self._make_attachment("first.png", "image/png", _RED_PIXEL_PNG)
        a2 = self._make_attachment("second.png", "image/png", _RED_PIXEL_PNG)

        payload, warnings, refs = _build_chat_payload("compare these", [a1, a2], engine)

        assert len(warnings) == 2
        names = [w["message"] for w in warnings]
        assert any("first.png" in m for m in names)
        assert any("second.png" in m for m in names)

    def test_empty_files_returns_message_unchanged(self):
        from ppxai.server.routes.chat import _build_chat_payload
        engine = self._make_engine(model="any", provider="any")
        payload, warnings, refs = _build_chat_payload("just text", [], engine)
        assert payload == "just text"
        assert warnings == []
        assert refs == []
