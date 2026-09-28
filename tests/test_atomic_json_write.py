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

import pytest

from ppxai.common.atomic_file import write_json_atomic
from ppxai.config import features
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

        t = threading.Thread(target=reader)
        t.start()
        try:
            for i in range(300):
                write_json_atomic(target, {**payload, "i": i})
        finally:
            stop.set()
            t.join()
        assert bad == [], bad[:3]


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
