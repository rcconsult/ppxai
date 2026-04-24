"""Tests for /save slash command (handle_save).

Regression coverage for two bugs discovered during interactive Phase 2.1a
testing:

1. `/save <name>` was ignoring the `args` argument entirely — the session
   was always saved under its auto-generated timestamp name, regardless
   of what the user typed after `/save`.

2. `/save` reported the filesystem path as `<name>.json` even for
   multimodal sessions that were actually saved in directory format
   (`<name>/session.json`), producing a misleading success message.

A third test pins the new behavior added after those were fixed:
when the user has attachments staged via `/attach` but hasn't sent them
yet, `/save` should emit a warning alongside the success result — silently
omitting them is the same kind of silent failure as bug #2.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, List

import pytest

from ppxai.commands.attach import PendingFile
from ppxai.commands.results import ResultStatus
from ppxai.commands.session import handle_save
from ppxai.engine.client import EngineClient
from ppxai.engine.types import Message


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """EngineClient with sessions dir redirected into tmp_path."""
    import ppxai.engine.session_store as store_mod

    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(store_mod, "_DEFAULT_STAGING_DIR", staging)

    client = EngineClient()
    client.session.sessions_dir = tmp_path / "sessions"
    client.session.sessions_dir.mkdir(parents=True, exist_ok=True)
    return client


def _make_context(engine: EngineClient, pending_files: List[PendingFile] = None) -> Any:
    """Build a minimal CommandContext-compatible stub wrapping an engine."""
    return SimpleNamespace(
        engine_client=engine,
        session=engine.session,
        working_dir=engine.session.working_dir,
        pending_files=pending_files or [],
    )


# -----------------------------------------------------------------------------
# Bug #1 — /save <name> must honor the args argument
# -----------------------------------------------------------------------------


class TestSaveWithName:
    def test_save_without_args_uses_auto_generated_name(self, engine):
        # Give the session a realistic 2-turn exchange so alternation-fix
        # doesn't drop the only message.
        engine.session.add_message(Message(role="user", content="hello"))
        engine.session.add_message(Message(role="assistant", content="hi"))
        original_name = engine.session.session_name

        result = handle_save(_make_context(engine), "")
        assert result.status == ResultStatus.SUCCESS
        # No rename happened.
        assert engine.session.session_name == original_name
        # Path points at the auto-generated name.
        assert result.details["session_name"] == original_name

    def test_save_with_name_renames_session(self, engine, tmp_path):
        engine.session.add_message(Message(role="user", content="hello"))
        engine.session.add_message(Message(role="assistant", content="hi"))

        result = handle_save(_make_context(engine), "my_experiment")

        assert result.status == ResultStatus.SUCCESS
        assert engine.session.session_name == "my_experiment"
        assert result.details["session_name"] == "my_experiment"
        # Flat format on disk (no attachments).
        expected = engine.session.sessions_dir / "my_experiment.json"
        assert expected.exists()

    def test_save_name_with_whitespace_is_stripped(self, engine):
        engine.session.add_message(Message(role="user", content="hello"))
        engine.session.add_message(Message(role="assistant", content="hi"))

        result = handle_save(_make_context(engine), "  trimmed  ")
        assert result.details["session_name"] == "trimmed"

    def test_save_empty_args_falls_back_to_auto_name(self, engine):
        engine.session.add_message(Message(role="user", content="hello"))
        engine.session.add_message(Message(role="assistant", content="hi"))
        original_name = engine.session.session_name

        # Only whitespace should be treated as "no name given".
        result = handle_save(_make_context(engine), "   ")
        assert result.details["session_name"] == original_name


# -----------------------------------------------------------------------------
# Bug #2 — /save reports correct path for directory-format multimodal sessions
# -----------------------------------------------------------------------------


class TestSavePathReporting:
    def test_flat_session_reports_json_file_path(self, engine):
        engine.session.add_message(Message(role="user", content="text"))
        engine.session.add_message(Message(role="assistant", content="ok"))

        result = handle_save(_make_context(engine), "flat_test")

        assert result.details["format"] == "flat"
        # Normalise separators so Windows (\) and POSIX (/) both pass.
        filepath = result.details["filepath"].replace("\\", "/")
        assert filepath.endswith("/flat_test.json")
        # And the file actually exists at that path.
        assert (engine.session.sessions_dir / "flat_test.json").exists()

    def test_multimodal_session_reports_directory_path(self, engine):
        import base64
        png = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 100
        data_uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")

        engine.session.add_message(Message(
            role="user",
            content=[{
                "type": "image_url",
                "name": "chart.png",
                "image_url": {"url": data_uri},
            }],
        ))
        engine.session.add_message(Message(role="assistant", content="ok"))

        result = handle_save(_make_context(engine), "multimodal_test")

        assert result.details["format"] == "directory"
        # Path points at <name>/session.json, not <name>.json.
        # Normalise separators so Windows (\) and POSIX (/) both pass.
        filepath = result.details["filepath"].replace("\\", "/")
        assert filepath.endswith("/multimodal_test/session.json")
        # And the directory actually contains the expected files.
        session_dir = engine.session.sessions_dir / "multimodal_test"
        assert (session_dir / "session.json").exists()
        assert (session_dir / "uploads").is_dir()


# -----------------------------------------------------------------------------
# Pending-attachment warning — staged files are not in the saved JSON
# -----------------------------------------------------------------------------


class TestPendingAttachmentWarning:
    def test_no_warning_when_pending_is_empty(self, engine):
        engine.session.add_message(Message(role="user", content="hi"))
        engine.session.add_message(Message(role="assistant", content="yo"))
        result = handle_save(_make_context(engine, pending_files=[]), "clean")
        assert result.details["pending_attachments_warning"] is False
        assert "staged" not in result.message.lower()

    def test_warning_when_pending_files_present(self, engine):
        engine.session.add_message(Message(role="user", content="hi"))
        engine.session.add_message(Message(role="assistant", content="yo"))

        pending = [
            PendingFile(
                name="chart.png",
                path="/tmp/chart.png",
                media_type="image/png",
                size=8,
                kind="image",
                data=b"\x89PNG\r\n\x1a\n",
            )
        ]
        result = handle_save(
            _make_context(engine, pending_files=pending), "with_pending"
        )
        # Save succeeds regardless of the staged attachment.
        assert result.status == ResultStatus.SUCCESS
        # But the message carries a visible warning naming the file.
        assert result.details["pending_attachments_warning"] is True
        assert "chart.png" in result.message
        assert "/attach" in result.message  # points at the fix
        # And the saved session JSON does NOT contain the staged file
        # because nothing has been sent to the engine yet.
        filepath = engine.session.sessions_dir / "with_pending.json"
        assert filepath.exists()
        data = json.loads(filepath.read_text())
        # Messages list should contain only the user/assistant pair —
        # no synthetic message carrying the staged attachment.
        assert len(data["messages"]) == 2
        assert all(
            msg["role"] in ("user", "assistant") for msg in data["messages"]
        )
        # No image_url parts anywhere in the saved content.
        for msg in data["messages"]:
            content = msg["content"]
            if isinstance(content, list):
                for block in content:
                    assert block.get("type") != "image_url"

    def test_warning_truncates_long_filename_list(self, engine):
        engine.session.add_message(Message(role="user", content="hi"))
        engine.session.add_message(Message(role="assistant", content="yo"))

        pending = [
            PendingFile(
                name=f"file_{i}.png",
                path=f"/tmp/file_{i}.png",
                media_type="image/png",
                size=8,
                kind="image",
                data=b"\x89PNG\r\n\x1a\n",
            )
            for i in range(7)
        ]
        result = handle_save(
            _make_context(engine, pending_files=pending), "many_pending"
        )
        # First 3 named, rest summarized.
        assert "file_0.png" in result.message
        assert "file_2.png" in result.message
        assert "+4 more" in result.message
