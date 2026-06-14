"""Session save/load security & integrity (codex review, v1.18.8).

Three findings, each reproduced here:
  #1 path traversal in session names (save + the JSON's internal session_name)
  #2 stale attachment file_ids after loading a text-only session
  #3 a failed/corrupt load corrupting the current file store
"""

from __future__ import annotations

import json

import pytest

from ppxai.engine.session import SessionManager, _safe_session_name
from ppxai.engine.session_store import SessionFileStore


def _sm(tmp_path):
    sm = SessionManager(sessions_dir=tmp_path / "sessions")
    sm.sessions_dir.mkdir(parents=True, exist_ok=True)
    return sm


# ---------------------------------------------------------------------------
# Finding #1 — path traversal in session names
# ---------------------------------------------------------------------------

class TestSessionNameTraversal:
    def test_safe_name_passes(self):
        assert _safe_session_name("session_2026_06_14") == "session_2026_06_14"

    @pytest.mark.parametrize("bad", [
        "../escaped", "a/b", "..", ".", "", "   ", "x\\y", "foo/../bar", "a\x00b",
    ])
    def test_unsafe_name_raises(self, bad):
        with pytest.raises(ValueError):
            _safe_session_name(bad)

    def test_unsafe_name_uses_fallback(self):
        assert _safe_session_name("../escaped", fallback="safe") == "safe"

    def test_save_rejects_traversal_and_writes_nothing_outside(self, tmp_path):
        sm = _sm(tmp_path)
        outside = tmp_path / "escaped.json"
        with pytest.raises(ValueError):
            sm.save("../escaped")
        assert not outside.exists(), "save() escaped sessions_dir"

    def test_load_ignores_poisoned_in_file_session_name(self, tmp_path):
        sm = _sm(tmp_path)
        # A safe, in-tree file whose INTERNAL session_name is a traversal.
        (sm.sessions_dir / "safe.json").write_text(
            json.dumps({"session_name": "../escaped", "metadata": {}, "messages": []})
        )
        assert sm.load("safe") is True
        # The poisoned name must NOT stick (it would escape on next autosave).
        assert sm.session_name == "safe"
        sm.save()  # autosave with the loaded name
        assert (sm.sessions_dir / "safe.json").exists()
        assert not (tmp_path / "escaped.json").exists()


# ---------------------------------------------------------------------------
# Finding #2 — stale attachment file_ids after loading a text-only session
# ---------------------------------------------------------------------------

class TestFileStoreResetOnLoad:
    def test_flat_load_resets_file_store(self, tmp_path):
        sm = _sm(tmp_path)
        sm.file_store = SessionFileStore(base_dir=tmp_path / "store")
        meta = sm.file_store.save("old.png", b"\x89PNGDATA", media_type="image/png")
        fid = meta.file_id
        assert sm.file_store.get_metadata(fid) is not None

        # Load a flat / text-only session (no uploads/ dir).
        (sm.sessions_dir / "textonly.json").write_text(
            json.dumps({"session_name": "textonly", "metadata": {}, "messages": []})
        )
        assert sm.load("textonly") is True

        assert sm.file_store.get_metadata(fid) is None, \
            "prior session's file_id still resolves after loading a flat session"

    def test_directory_load_without_uploads_resets(self, tmp_path):
        sm = _sm(tmp_path)
        sm.file_store = SessionFileStore(base_dir=tmp_path / "store")
        fid = sm.file_store.save("old.png", b"DATA", media_type="image/png").file_id
        # Directory session but no uploads/ subdir.
        sdir = sm.sessions_dir / "dirsess"
        sdir.mkdir(parents=True)
        (sdir / "session.json").write_text(
            json.dumps({"session_name": "dirsess", "metadata": {}, "messages": []})
        )
        assert sm.load("dirsess") is True
        assert sm.file_store.get_metadata(fid) is None


# ---------------------------------------------------------------------------
# Finding #3 — a corrupt load must not touch the current file store
# ---------------------------------------------------------------------------

class TestCorruptLoadPreservesFileStore:
    def test_corrupt_directory_load_keeps_store_and_messages(self, tmp_path):
        sm = _sm(tmp_path)
        sm.file_store = SessionFileStore(base_dir=tmp_path / "store")
        fid = sm.file_store.save("current.png", b"DATA", media_type="image/png").file_id

        # Seed a current message so we can assert it's preserved too.
        from ppxai.engine.types import Message
        sm.messages = [Message("user", "current work")]

        # Corrupt directory session (parses AFTER the store would be touched
        # in the old code).
        sdir = sm.sessions_dir / "corruptdir"
        (sdir / "uploads").mkdir(parents=True)
        (sdir / "session.json").write_text("{ this is not valid json")

        ok = sm.load("corruptdir")

        assert ok is False
        # The current store must be intact — the failed load didn't wipe it.
        assert sm.file_store.get_metadata(fid) is not None, \
            "corrupt load wiped the current file store"
        # Messages unchanged (existing contract).
        assert [m.text_content() for m in sm.messages] == ["current work"]
