"""Tests for /attach slash command (Phase 1, v1.17.4).

Covers the pure/leaf helpers (`_split_paths`, `_classify`,
`build_multimodal_content`, `_load_file`) and the full `handle_attach`
dispatcher against real files in a pytest tmp_path. Deliberately avoids
spinning up a CommandHandler — `/attach` only reads `working_dir` and
`pending_files` from its context, so a SimpleNamespace stand-in is enough
and keeps the tests fast.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any

import pytest

from ppxai.commands.attach import (
    MAX_FILE_BYTES,
    ContextAttachment,
    PendingFile,
    _classify,
    _load_file,
    _split_paths,
    build_multimodal_content,
    collect_context_attachments,
    handle_attach,
)
from ppxai.engine.types import Message
from ppxai.commands.factory import CommandFactory
from ppxai.commands.results import ResultStatus


# Minimal 1x1 red PNG as raw bytes (valid header; decoders accept it).
_RED_PIXEL_PNG = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8DwHwAFAQH/c4"
    b"X0gAAAAABJRU5ErkJggg=="
)


@pytest.fixture
def ctx(tmp_path) -> Any:
    """Fake command context exposing only the fields /attach reads."""
    context = SimpleNamespace(
        working_dir=str(tmp_path),
        pending_files=[],
    )
    # _load_file uses _wrapped for attribute-write fallback; point it at self
    # so assignments to pending_files round-trip into the same namespace.
    context._wrapped = context
    return context


# -----------------------------------------------------------------------------
# Pure helpers
# -----------------------------------------------------------------------------


class TestSplitPaths:
    def test_whitespace_separated(self):
        assert _split_paths("a.png b.txt c.py") == ["a.png", "b.txt", "c.py"]

    def test_quoted_path_with_space(self):
        assert _split_paths('"my docs/chart.png" b.py') == ["my docs/chart.png", "b.py"]

    def test_mixed_quoting(self):
        assert _split_paths('"a b.png" "c d.txt" e.py') == ["a b.png", "c d.txt", "e.py"]

    def test_empty(self):
        assert _split_paths("") == []

    def test_single_path(self):
        assert _split_paths("chart.png") == ["chart.png"]


class TestClassify:
    def test_image_types(self):
        assert _classify("image/png", ".png") == "image"
        assert _classify("image/jpeg", ".jpg") == "image"
        assert _classify("image/webp", ".webp") == "image"
        assert _classify("image/gif", ".gif") == "image"

    def test_text_types(self):
        assert _classify("text/plain", ".txt") == "text"
        assert _classify("text/markdown", ".md") == "text"
        assert _classify("text/x-python", ".py") == "text"

    def test_code_by_extension_even_when_mime_unknown(self):
        assert _classify("application/octet-stream", ".rs") == "text"
        assert _classify("application/octet-stream", ".ts") == "text"
        assert _classify("application/json", ".json") == "text"

    def test_pdf_and_office_are_deferred(self):
        assert _classify("application/pdf", ".pdf") == "deferred"
        assert _classify("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx") == "deferred"
        assert _classify("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx") == "deferred"

    def test_unknown_is_deferred(self):
        assert _classify("application/octet-stream", ".bin") == "deferred"


class TestBuildMultimodalContent:
    def test_text_only(self):
        parts = build_multimodal_content("hello world", [])
        assert parts == [{"type": "text", "text": "hello world"}]

    def test_empty_message_empty_pending_still_has_one_part(self):
        # Providers reject empty content — we must always return at least one part.
        parts = build_multimodal_content("", [])
        assert len(parts) == 1
        assert parts[0]["type"] == "text"

    def test_image_becomes_data_uri(self):
        # v1.17.4 Phase 2.2: build_multimodal_content now delegates to
        # preprocess_file which validates via magic-byte sniffing, so
        # tests need REAL image bytes. A fake "AAAA" blob would be
        # rejected by validate_image — that's the correct behavior.
        pf = PendingFile(
            name="chart.png",
            path="/tmp/chart.png",
            media_type="image/png",
            size=len(_RED_PIXEL_PNG),
            kind="image",
            data=_RED_PIXEL_PNG,
        )
        parts = build_multimodal_content("describe this", [pf], model="gpt-5.2")
        assert len(parts) == 2
        assert parts[0] == {"type": "text", "text": "describe this"}
        assert parts[1]["type"] == "image_url"
        assert parts[1]["name"] == "chart.png"
        assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_text_file_inlined_into_text_part(self):
        pf = PendingFile(
            name="hello.py",
            path="/tmp/hello.py",
            media_type="text/x-python",
            size=11,
            kind="text",
            data=b'print("hi")',
        )
        parts = build_multimodal_content("review this", [pf])
        assert len(parts) == 1  # text file merged into the single text part
        assert parts[0]["type"] == "text"
        assert 'review this' in parts[0]["text"]
        assert '<file name="hello.py"' in parts[0]["text"]
        assert 'print("hi")' in parts[0]["text"]
        assert '</file>' in parts[0]["text"]

    def test_mixed_text_and_image(self):
        img = PendingFile(
            name="g.png", path="/tmp/g.png", media_type="image/png",
            size=len(_RED_PIXEL_PNG), kind="image", data=_RED_PIXEL_PNG,
        )
        txt = PendingFile(
            name="config.yaml", path="/tmp/config.yaml", media_type="text/yaml",
            size=10, kind="text", data=b"key: value",
        )
        parts = build_multimodal_content("explain", [img, txt], model="gpt-5.2")
        # One merged text part (user prompt + text file), one image part.
        assert len(parts) == 2
        assert parts[0]["type"] == "text"
        assert "explain" in parts[0]["text"]
        assert "config.yaml" in parts[0]["text"]
        assert parts[1]["type"] == "image_url"


# -----------------------------------------------------------------------------
# _load_file — file IO + classification
# -----------------------------------------------------------------------------


class TestLoadFile:
    def test_loads_png(self, tmp_path):
        path = tmp_path / "pixel.png"
        path.write_bytes(_RED_PIXEL_PNG)
        pf, err = _load_file("pixel.png", str(tmp_path))
        assert err is None
        assert pf is not None
        assert pf.kind == "image"
        assert pf.media_type == "image/png"
        assert pf.name == "pixel.png"
        # Base64 round-trip
        assert base64.b64decode(pf.data_b64) == _RED_PIXEL_PNG

    def test_loads_text_file(self, tmp_path):
        path = tmp_path / "notes.md"
        path.write_text("# Hello\n\nWorld", encoding="utf-8")
        pf, err = _load_file("notes.md", str(tmp_path))
        assert err is None
        assert pf.kind == "text"
        assert pf.text == "# Hello\n\nWorld"

    def test_resolves_relative_against_working_dir(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "file.txt").write_text("x", encoding="utf-8")
        pf, err = _load_file("sub/file.txt", str(tmp_path))
        assert err is None
        assert pf.name == "file.txt"

    def test_strips_surrounding_quotes(self, tmp_path):
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        pf, err = _load_file('"a.txt"', str(tmp_path))
        assert err is None
        assert pf.name == "a.txt"

    def test_missing_file_error(self, tmp_path):
        pf, err = _load_file("nope.png", str(tmp_path))
        assert pf is None
        assert err is not None and "no such file" in err

    def test_missing_file_suggests_close_matches_in_parent(self, tmp_path):
        """R18: siblings in the target dir are surfaced when the name is wrong."""
        (tmp_path / "ppxai-vscode-v1.17.4.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (tmp_path / "ppxai-tui-preview.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (tmp_path / "something-unrelated.txt").write_text("x", encoding="utf-8")

        _, err = _load_file("ppxai-vscode-v1.17.3.png", str(tmp_path))
        assert err is not None
        assert "no such file" in err
        assert "Nearest matches" in err
        # The lexically closest PNG must show up first.
        assert "ppxai-vscode-v1.17.4.png" in err

    def test_missing_file_suggests_sibling_dirs_when_parent_absent(self, tmp_path):
        """R18: when the typed subdir doesn't exist, suggest similar ancestors."""
        (tmp_path / "docs").mkdir()
        (tmp_path / "resources").mkdir()
        (tmp_path / "archive").mkdir()

        _, err = _load_file("resourcs/foo.png", str(tmp_path))
        assert err is not None
        assert "no such file" in err
        assert "'resourcs' not found" in err
        assert "resources" in err  # closest sibling directory

    def test_missing_file_with_no_close_matches_keeps_message_terse(self, tmp_path):
        """No noisy suggestions when nothing in the parent is similar."""
        (tmp_path / "totally_unrelated.zip").write_bytes(b"PK\x03\x04")

        _, err = _load_file("alpha.png", str(tmp_path))
        assert err is not None
        assert "no such file" in err
        # Either the "none similar" note or nothing about matches — but not a
        # misleading suggestion for an unrelated name.
        assert "alpha.png" not in err.split("\n", 1)[-1] or "none similar" in err

    def test_pdf_deferred_with_helpful_message(self, tmp_path):
        (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\n")
        pf, err = _load_file("doc.pdf", str(tmp_path))
        assert pf is None
        assert err is not None
        assert "Phase 2" in err

    def test_oversize_file_rejected(self, tmp_path, monkeypatch):
        # Patch MAX_FILE_BYTES low so we don't allocate 10 MB.
        import ppxai.commands.attach as attach_mod
        monkeypatch.setattr(attach_mod, "MAX_FILE_BYTES", 100)
        big = tmp_path / "big.txt"
        big.write_bytes(b"x" * 200)
        pf, err = _load_file("big.txt", str(tmp_path))
        assert pf is None
        assert err is not None and "exceeds" in err


# -----------------------------------------------------------------------------
# handle_attach — full dispatcher
# -----------------------------------------------------------------------------


class TestHandleAttach:
    def test_list_when_empty_shows_usage(self, ctx):
        result = handle_attach(ctx, "")
        assert result.status == ResultStatus.INFO
        assert "Usage:" in result.message
        # Usage message mentions the four subcommands post-Phase-2.1b.
        assert "/attach clear" in result.message
        assert "/attach remove" in result.message

    def test_attach_single_image(self, ctx, tmp_path):
        (tmp_path / "x.png").write_bytes(_RED_PIXEL_PNG)
        result = handle_attach(ctx, "x.png")
        assert result.status == ResultStatus.SUCCESS
        assert len(ctx.pending_files) == 1
        assert ctx.pending_files[0].kind == "image"
        # Image paths are surfaced in metadata for inline-preview rendering.
        assert "attached_paths" in result.metadata
        assert len(result.metadata["attached_paths"]) == 1

    def test_attach_image_plus_text(self, ctx, tmp_path):
        (tmp_path / "img.png").write_bytes(_RED_PIXEL_PNG)
        (tmp_path / "code.py").write_text("def f(): pass", encoding="utf-8")
        result = handle_attach(ctx, "img.png code.py")
        assert result.status == ResultStatus.SUCCESS
        kinds = [pf.kind for pf in ctx.pending_files]
        assert kinds == ["image", "text"]
        # Only the image appears in attached_paths — text files don't preview.
        assert len(result.metadata["attached_paths"]) == 1

    def test_list_after_attach(self, ctx, tmp_path):
        (tmp_path / "a.png").write_bytes(_RED_PIXEL_PNG)
        handle_attach(ctx, "a.png")
        result = handle_attach(ctx, "")
        # Post-Phase-2.1b: listing shows two sections (staged + in context).
        # After a single /attach with no send, only the staged section exists.
        assert "Staged" in result.message
        assert "1 file" in result.message
        assert "a.png" in result.message

    def test_clear_discards_pending(self, ctx, tmp_path):
        (tmp_path / "a.png").write_bytes(_RED_PIXEL_PNG)
        handle_attach(ctx, "a.png")
        assert len(ctx.pending_files) == 1
        result = handle_attach(ctx, "clear")
        assert result.status == ResultStatus.SUCCESS
        assert len(ctx.pending_files) == 0
        assert "Cleared 1 attachment" in result.message

    def test_clear_when_empty(self, ctx):
        result = handle_attach(ctx, "clear")
        assert result.status == ResultStatus.INFO
        assert "No attachments to clear" in result.message

    def test_all_missing_returns_error(self, ctx):
        result = handle_attach(ctx, "ghost1.png ghost2.png")
        assert result.status == ResultStatus.ERROR
        assert len(ctx.pending_files) == 0  # nothing staged on failure

    def test_partial_success_keeps_valid_files(self, ctx, tmp_path):
        (tmp_path / "real.png").write_bytes(_RED_PIXEL_PNG)
        result = handle_attach(ctx, "real.png missing.png")
        assert result.status == ResultStatus.SUCCESS
        assert len(ctx.pending_files) == 1
        assert "Skipped:" in result.message

    def test_pdf_rejected_with_phase2_hint(self, ctx, tmp_path):
        (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4\n")
        result = handle_attach(ctx, "doc.pdf")
        assert result.status == ResultStatus.ERROR
        assert "Phase 2" in result.message
        assert len(ctx.pending_files) == 0


# -----------------------------------------------------------------------------
# Registration — /attach is discoverable via CommandFactory
# -----------------------------------------------------------------------------


class TestCollectContextAttachments:
    """Scan session.messages for multimodal attachments still in context."""

    def _session(self, messages):
        return SimpleNamespace(messages=messages)

    def test_empty_session(self):
        assert collect_context_attachments(self._session([])) == []

    def test_no_multimodal_messages(self):
        msgs = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi there"),
        ]
        assert collect_context_attachments(self._session(msgs)) == []

    def test_single_image_in_user_message(self):
        msg = Message(role="user", content=[
            {"type": "text", "text": "describe this"},
            {"type": "image_url", "name": "chart.png",
             "image_url": {"url": "data:image/png;base64,AA"}},
        ])
        result = collect_context_attachments(self._session([msg]))
        assert len(result) == 1
        assert result[0].name == "chart.png"
        assert result[0].kind == "image"

    def test_multiple_unique_images_across_turns(self):
        msgs = [
            Message(role="user", content=[
                {"type": "text", "text": "q1"},
                {"type": "image_url", "name": "a.png",
                 "image_url": {"url": "data:image/png;base64,AA"}},
            ]),
            Message(role="assistant", content="answer 1"),
            Message(role="user", content=[
                {"type": "text", "text": "q2"},
                {"type": "image_url", "name": "b.png",
                 "image_url": {"url": "data:image/png;base64,BB"}},
            ]),
        ]
        result = collect_context_attachments(self._session(msgs))
        assert [r.name for r in result] == ["a.png", "b.png"]

    def test_duplicate_name_deduped(self):
        # Same image attached twice across turns — should appear once.
        msgs = [
            Message(role="user", content=[
                {"type": "image_url", "name": "chart.png",
                 "image_url": {"url": "data:image/png;base64,AA"}},
            ]),
            Message(role="user", content=[
                {"type": "image_url", "name": "chart.png",
                 "image_url": {"url": "data:image/png;base64,AA"}},
            ]),
        ]
        result = collect_context_attachments(self._session(msgs))
        assert len(result) == 1
        assert result[0].name == "chart.png"

    # ------------------------------------------------------------------
    # ADR 0006 Phase 2a — readers walk Message.attachments first
    # ------------------------------------------------------------------

    def test_phase2a_walks_attachments_when_populated(self):
        """When Message.attachments is populated (ADR 0006 Phase 1+
           production path), the reader uses it directly without
           scanning content blocks. Pinning the new code path so a
           future regression doesn't silently fall back to the legacy
           block-scan branch."""
        from ppxai.engine.types import AttachmentRef
        msg = Message(
            role="user",
            content=[
                {"type": "text", "text": "look at this"},
                # Note: in-block name DELIBERATELY differs from
                # AttachmentRef.name to prove the reader trusts
                # attachments, not in-block keys.
                {"type": "image_url", "name": "wrong-name.png",
                 "image_url": {"url": "data:image/png;base64,X"}},
            ],
            attachments=[
                AttachmentRef(block_index=1, name="correct-name.png",
                              file_id="sha256:abc", media_type="image/png"),
            ],
        )
        result = collect_context_attachments(self._session([msg]))
        assert len(result) == 1
        assert result[0].name == "correct-name.png"

    def test_phase2a_legacy_fallback_when_attachments_empty(self):
        """Pre-Phase-1 messages (no attachments populated) fall back to
           the legacy block-walk so the migration is non-breaking."""
        msg = Message(
            role="user",
            content=[
                {"type": "image_url", "name": "legacy.png",
                 "image_url": {"url": "data:image/png;base64,X"}},
            ],
            # attachments deliberately empty — simulates pre-Phase-1 shape
        )
        result = collect_context_attachments(self._session([msg]))
        assert len(result) == 1
        assert result[0].name == "legacy.png"

    def test_ignores_text_parts(self):
        # Text-only list content never produces an attachment entry.
        msg = Message(role="user", content=[{"type": "text", "text": "just text"}])
        assert collect_context_attachments(self._session([msg])) == []

    def test_missing_name_falls_back_to_image(self):
        msg = Message(role="user", content=[
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64,AA"}},
        ])
        result = collect_context_attachments(self._session([msg]))
        assert len(result) == 1
        assert result[0].name == "image"

    def test_missing_session_attribute_returns_empty(self):
        assert collect_context_attachments(SimpleNamespace()) == []

    def test_non_list_content_is_skipped(self):
        # Plain-string content (legacy single-modal) never contains image parts.
        msg = Message(role="user", content="plain string")
        assert collect_context_attachments(self._session([msg])) == []


class TestRegistration:
    def test_attach_registered(self):
        # Importing handler wires up registrations via side-effect imports.
        import ppxai.commands.handler  # noqa: F401
        spec = CommandFactory.get("attach")
        assert spec is not None
        assert spec.name == "attach"
        assert "att" in spec.aliases

    def test_attach_alias_resolves(self):
        import ppxai.commands.handler  # noqa: F401
        spec = CommandFactory.get("att")
        assert spec is not None
        assert spec.name == "attach"
