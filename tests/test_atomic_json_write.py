"""`write_json_atomic`: a reader never sees a partial file.

Found by wsl2-builder (2026-09-28): two full-suite failures under `-n auto`,
both a 500 from `/command/usage` with "Invalid JSON in config file
.../ppxai-config.json: Expecting value: line 1 column 1 (char 0)". The
settings writer (`config/features.py::set_tui_config`) saved with
`open(path, "w")` + `json.dump`: truncate first, write after, so a read
landing in between saw an empty file. The same pattern saved sessions, the
session-state pointer and `usage.json`. A crash mid-save could leave any of
them empty -- the user's hand-edited config included.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import pytest

from ppxai import usage as usage_module
from ppxai.common import atomic_file
from ppxai.common.atomic_file import read_json, write_json_atomic
from ppxai.config import features
from ppxai.config.store import ConfigStore
from ppxai.engine.session import SessionManager
from ppxai.usage import UsageStorage


class TestWriteJsonAtomic:
    def test_writes_the_json_with_the_requested_shape(self, tmp_path):
        target = tmp_path / "c.json"
        write_json_atomic(target, {"a": "é", "b": [1]}, indent=2, ensure_ascii=False,
                          trailing_newline=True)
        text = target.read_text(encoding="utf-8")
        assert json.loads(text) == {"a": "é", "b": [1]}
        assert text.endswith("}\n") and "é" in text and '\n  "a"' in text

    def test_replaces_an_existing_file_and_leaves_no_temp_behind(self, tmp_path):
        target = tmp_path / "c.json"
        target.write_text('{"old": true}', encoding="utf-8")
        write_json_atomic(target, {"new": True})
        assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}
        assert [p.name for p in tmp_path.iterdir()] == ["c.json"]

    def test_a_failed_write_leaves_the_target_untouched(self, tmp_path):
        target = tmp_path / "c.json"
        target.write_text('{"keep": 1}', encoding="utf-8")
        with pytest.raises(TypeError):
            write_json_atomic(target, {"bad": object()})
        assert target.read_text(encoding="utf-8") == '{"keep": 1}'
        assert [p.name for p in tmp_path.iterdir()] == ["c.json"]

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
    def test_an_existing_file_keeps_its_mode_and_a_new_one_is_private(self, tmp_path):
        target = tmp_path / "c.json"
        target.write_text("{}", encoding="utf-8")
        os.chmod(target, 0o640)
        write_json_atomic(target, {"x": 1})
        assert (target.stat().st_mode & 0o777) == 0o640
        fresh = tmp_path / "new.json"
        write_json_atomic(fresh, {})
        assert (fresh.stat().st_mode & 0o777) == 0o600

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks need Developer Mode on Windows")
    def test_a_symlinked_target_stays_a_symlink(self, tmp_path):
        real = tmp_path / "dotfiles" / "ppxai-config.json"
        real.parent.mkdir()
        real.write_text("{}", encoding="utf-8")
        link = tmp_path / "ppxai-config.json"
        link.symlink_to(real)
        write_json_atomic(link, {"via": "link"})
        assert link.is_symlink()
        assert json.loads(real.read_text(encoding="utf-8")) == {"via": "link"}

    def test_a_concurrent_reader_never_sees_a_partial_file(self, tmp_path):
        # The race behind the flake: with truncate-then-write this fails
        # within a few hundred saves (an empty or cut-off read).
        target = tmp_path / "c.json"
        payload = {"k": ["x" * 200] * 400}
        write_json_atomic(target, payload)
        stop = threading.Event()
        bad: list[str] = []

        def reader():
            while not stop.is_set():
                try:
                    with open(target, encoding="utf-8") as f:
                        json.load(f)
                except json.JSONDecodeError as exc:
                    bad.append(str(exc))
                except PermissionError:
                    pass  # Windows: open raced the rename; not a partial read
                time.sleep(0.001)  # a real reader re-reads, it does not spin

        t = threading.Thread(target=reader)
        t.start()
        saved = 0
        try:
            for i in range(300):
                try:
                    write_json_atomic(target, {**payload, "i": i})
                    saved += 1
                except PermissionError:
                    # Windows: the reader held the file through every retry.
                    # The save failed whole; the old file is intact.
                    if sys.platform != "win32":
                        raise
        finally:
            stop.set()
            t.join()
        assert bad == [], bad[:3]
        assert saved > 0
        assert json.loads(target.read_text(encoding="utf-8"))["k"] == payload["k"]

    def test_windows_raises_and_keeps_the_old_file_when_the_rename_stays_denied(
            self, tmp_path, monkeypatch):
        # ppxai-64, 2026-09-28: on Windows os.replace over a file a reader
        # holds open is denied. More, jittered retries -- then raise with the
        # target intact. Never write in place: that truncates under the very
        # reader holding the file (win32-ppxai).
        target = tmp_path / "c.json"
        target.write_text('{"old": 1}', encoding="utf-8")
        attempts = []

        def denied(self_path, target_path):
            attempts.append(1)
            raise PermissionError(13, "[WinError 5] Access is denied")

        monkeypatch.setattr(atomic_file.sys, "platform", "win32")
        monkeypatch.setattr(atomic_file.time, "sleep", lambda s: None)
        monkeypatch.setattr(Path, "replace", denied)
        with pytest.raises(PermissionError):
            write_json_atomic(target, {"new": 1})
        assert target.read_text(encoding="utf-8") == '{"old": 1}'
        assert len(attempts) == atomic_file._WINDOWS_JSON_RETRIES
        assert [p.name for p in tmp_path.iterdir()] == ["c.json"]

    def test_off_windows_a_denied_rename_still_raises(self, tmp_path, monkeypatch):
        target = tmp_path / "c.json"
        target.write_text('{"old": 1}', encoding="utf-8")

        def denied(self_path, target_path):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(atomic_file.sys, "platform", "linux")
        monkeypatch.setattr(Path, "replace", denied)
        with pytest.raises(PermissionError):
            write_json_atomic(target, {"new": 1})
        assert target.read_text(encoding="utf-8") == '{"old": 1}'
        assert [p.name for p in tmp_path.iterdir()] == ["c.json"]


_IN_PLACE_WRITE = re.compile(r"""open\([^)]*,\s*['"]w['"]""")


@pytest.mark.parametrize("func", [
    features.set_tui_config,
    SessionManager._write_session_json_in_place,
    SessionManager._update_state_file,
    UsageStorage._save,
], ids=lambda f: f.__qualname__)
def test_state_files_are_saved_atomically(func):
    """These four save files other code reads concurrently (the config, a
    session, the restore pointer, usage.json). Each must go through
    write_json_atomic, never a truncating open(..., "w")."""
    src = inspect.getsource(func)
    assert "write_json_atomic(" in src, f"{func.__qualname__} no longer saves atomically"
    assert not _IN_PLACE_WRITE.search(src), f"{func.__qualname__} truncates in place again"


class TestReadJson:
    def test_reads_json_with_the_given_encoding(self, tmp_path):
        target = tmp_path / "c.json"
        target.write_bytes(b'\xef\xbb\xbf{"bom": true}')
        assert read_json(target, encoding="utf-8-sig") == {"bom": True}

    def test_retries_the_windows_rename_race(self, tmp_path, monkeypatch):
        # A reader opening the file while os.replace swaps it gets a
        # PermissionError on Windows (win32-ppxai, 2026-09-28).
        target = tmp_path / "c.json"
        target.write_text('{"ok": 1}', encoding="utf-8")
        real_open = open
        calls = []

        def flaky_open(*args, **kwargs):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError(13, "sharing violation")
            return real_open(*args, **kwargs)

        monkeypatch.setattr(atomic_file.sys, "platform", "win32")
        monkeypatch.setattr("builtins.open", flaky_open)
        assert read_json(target) == {"ok": 1}
        assert len(calls) == 3

    def test_does_not_retry_off_windows(self, tmp_path, monkeypatch):
        target = tmp_path / "c.json"
        target.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(atomic_file.sys, "platform", "linux")

        def denied(*args, **kwargs):
            raise PermissionError(13, "denied")

        monkeypatch.setattr("builtins.open", denied)
        with pytest.raises(PermissionError):
            read_json(target)


class TestAFailedReadNeverWipesTheFile:
    """Before 2026-09-28 both writers treated an unreadable file as empty
    and saved that back: one failed read wiped the whole file."""

    @pytest.fixture
    def config_file(self, tmp_path, monkeypatch):
        path = tmp_path / "ppxai-config.json"
        monkeypatch.setattr(features, "find_writable_config_file", lambda: path)
        monkeypatch.setattr(features, "find_config_file", lambda: path)
        store = ConfigStore.get_instance()
        monkeypatch.setitem(store.config, "tui", dict(store.config.get("tui", {})))
        return path

    def test_an_unparseable_config_is_not_overwritten(self, config_file):
        config_file.write_text('{"providers": {"x": 1}, BROKEN', encoding="utf-8")
        assert features.set_tui_config("debug_log", True) is False
        assert config_file.read_text(encoding="utf-8") == '{"providers": {"x": 1}, BROKEN'
        assert ConfigStore.get_instance().config["tui"]["debug_log"] is True

    def test_an_unreadable_config_is_not_overwritten(self, config_file, monkeypatch):
        config_file.write_text('{"providers": {"x": 1}}', encoding="utf-8")

        def locked(*args, **kwargs):
            raise PermissionError(13, "locked")

        monkeypatch.setattr(features, "read_json", locked)
        assert features.set_tui_config("debug_log", True) is False
        assert json.loads(config_file.read_text(encoding="utf-8")) == {"providers": {"x": 1}}

    def test_a_readable_config_keeps_everything_else(self, config_file):
        config_file.write_text('{"providers": {"x": 1}, "tui": {"theme": "dark"}}',
                               encoding="utf-8")
        assert features.set_tui_config("debug_log", True) is True
        saved = json.loads(config_file.read_text(encoding="utf-8"))
        assert saved == {"providers": {"x": 1}, "tui": {"theme": "dark", "debug_log": True}}

    def test_a_failed_save_keeps_the_file_and_the_setting(self, config_file, monkeypatch):
        config_file.write_text('{"providers": {"x": 1}}', encoding="utf-8")

        def denied(*args, **kwargs):
            raise PermissionError(13, "[WinError 5] Access is denied")

        monkeypatch.setattr(features, "write_json_atomic", denied)
        assert features.set_tui_config("debug_log", True) is False
        assert json.loads(config_file.read_text(encoding="utf-8")) == {"providers": {"x": 1}}
        assert ConfigStore.get_instance().config["tui"]["debug_log"] is True

    def test_corrupt_usage_is_moved_aside_not_overwritten(self, tmp_path):
        usage_file = tmp_path / "usage.json"
        usage_file.write_text('{"sessions": [TRUNCATED', encoding="utf-8")
        storage = UsageStorage(usage_dir=tmp_path)
        storage._save()
        backups = list(tmp_path.glob("usage.json.corrupt-*"))
        assert len(backups) == 1
        assert backups[0].read_text(encoding="utf-8") == '{"sessions": [TRUNCATED'
        assert json.loads(usage_file.read_text(encoding="utf-8"))["sessions"] == []

    def test_unreadable_usage_is_never_saved_over(self, tmp_path, monkeypatch):
        usage_file = tmp_path / "usage.json"
        usage_file.write_text('{"version": 1, "sessions": [{"id": "keep"}]}', encoding="utf-8")

        def locked(*args, **kwargs):
            raise PermissionError(13, "locked")

        monkeypatch.setattr(usage_module, "read_json", locked)
        storage = UsageStorage(usage_dir=tmp_path)
        storage._save()
        assert json.loads(usage_file.read_text(encoding="utf-8"))["sessions"] == [{"id": "keep"}]
