"""Web UI directory resolution (v1.19.0).

`ppxai/server/routes/static.py` serves the web UI from a single directory that
ALL clients (server, desktop, `uv run`) read — by default `~/.ppxai/web`, NOT
the source tree. The `PPXAI_WEB_DIR` override lets web development serve a
checkout's `ppxai/web` directly without syncing `~/.ppxai/web` after each edit.

These pin the resolution order so the dev override can't silently regress.
"""

from __future__ import annotations

from pathlib import Path

from ppxai.server.routes.static import _resolve_web_ui_dir


class TestWebUiDirResolution:
    def test_defaults_to_home_ppxai_web(self, monkeypatch):
        monkeypatch.delenv("PPXAI_WEB_DIR", raising=False)
        assert _resolve_web_ui_dir() == Path.home() / ".ppxai" / "web"

    def test_env_override_wins(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PPXAI_WEB_DIR", str(tmp_path / "web"))
        assert _resolve_web_ui_dir() == tmp_path / "web"

    def test_env_override_expands_user(self, monkeypatch):
        monkeypatch.setenv("PPXAI_WEB_DIR", "~/some/web")
        assert _resolve_web_ui_dir() == Path.home() / "some" / "web"

    def test_empty_env_falls_through_to_default(self, monkeypatch):
        # An empty string is not a usable override — fall back to the default.
        monkeypatch.setenv("PPXAI_WEB_DIR", "")
        assert _resolve_web_ui_dir() == Path.home() / ".ppxai" / "web"
