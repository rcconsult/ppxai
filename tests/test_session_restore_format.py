"""Dual-format session existence check (codex review, v1.18.8, finding #1).

Auto-restore pre-checks ignored directory-format (multimodal) sessions — they
checked only `<name>.json`, so a saved `<name>/session.json` looked missing and
the restore pointer was cleared. `SessionManager.session_file_exists()` now
accepts both formats; both the Textual restore and the server
`/sessions/restore` pre-check route through it.

(The companion finding #2 — POST /sessions/save reading `name` from the JSON
body — is tested in test_server_routes.py with the isolated mocked-route
harness, so it doesn't spin up the real app / write under ~/.ppxai.)
"""

from __future__ import annotations

from ppxai.engine.session import SessionManager


class TestSessionFileExists:
    def test_flat_format(self, tmp_path):
        (tmp_path / "flat.json").write_text("{}", encoding="utf-8")
        assert SessionManager.session_file_exists("flat", sessions_dir=tmp_path)

    def test_directory_format(self, tmp_path):
        d = tmp_path / "multimodal"
        d.mkdir()
        (d / "session.json").write_text("{}", encoding="utf-8")
        # The flat-only check used to miss this and clear the restore pointer.
        assert SessionManager.session_file_exists("multimodal", sessions_dir=tmp_path)

    def test_missing_both(self, tmp_path):
        assert not SessionManager.session_file_exists("nope", sessions_dir=tmp_path)
