"""Session save/restore format handling (codex review, v1.18.8).

Two findings:
  #1 auto-restore pre-check ignored directory-format (multimodal) sessions —
     it checked only `<name>.json`, so a saved `<name>/session.json` looked
     missing and the restore pointer was cleared.
  #2 POST /sessions/save bound `name` as a query param, but web/VSCode send it
     in the JSON body, so a named save was silently saved under the auto-name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ppxai.engine.session import SessionManager


# ---------------------------------------------------------------------------
# Finding #1 — dual-format existence check
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Finding #2 — POST /sessions/save reads name from the JSON body
# ---------------------------------------------------------------------------

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


class TestNamedSaveFromBody:
    def test_save_honors_name_in_json_body(self):
        from fastapi.testclient import TestClient
        import ppxai.server.http as http_module

        name = "route-named-save-regression-xyz"
        sd = Path.home() / ".ppxai" / "sessions"
        try:
            with TestClient(http_module.app, raise_server_exceptions=False) as client:
                resp = client.post(
                    "/sessions/save",
                    json={"name": name},
                    headers={"X-Session-Id": "named-save-test"},
                )
            assert resp.status_code == 200, resp.text
            # The body name must be honored — previously `name` was a query
            # param, so the JSON body was ignored and an auto-name returned.
            assert resp.json()["name"] == name
        finally:
            (sd / f"{name}.json").unlink(missing_ok=True)
            dir_form = sd / name
            if dir_form.is_dir():
                (dir_form / "session.json").unlink(missing_ok=True)
                # best-effort cleanup of the directory tree
                import shutil
                shutil.rmtree(dir_form, ignore_errors=True)
