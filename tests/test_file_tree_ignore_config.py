"""Tests for `file_tree.ignore_dirs` config setting (v1.18.7).

Promoted from hard-coded `IGNORE_DIRS` set in `ppxai/server/routes/files.py`
to a configurable list under `file_tree.ignore_dirs` in `ppxai-config.json`.
Default list unchanged (same 10 entries); users can now override to
unhide e.g. `venv/` or `build/` when their workflow needs visibility
into those directories.

Three concerns covered:

1. **Default behavior unchanged.** `get_file_tree_ignore_dirs()` returns
   the legacy set when no config override is set. Existing behavior
   (hide .git, node_modules, venv, etc.) keeps working for every user
   who doesn't touch their config.

2. **Override semantics: REPLACE not merge.** A user-provided
   `file_tree.ignore_dirs` list is used verbatim. The empty list
   disables ignoring entirely.

3. **End-to-end via the routes.** `/files/list` and `/files/tree`
   honor the configured ignore list — adding `myhidden/` to the list
   removes it from listings; removing `venv/` from the list shows it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Unit tests for the config-layer accessor
# ---------------------------------------------------------------------------


class TestGetFileTreeIgnoreDirs:
    """Pure config-layer behavior — no HTTP."""

    def test_default_set_matches_legacy_constant(self):
        # When no override is set, the function returns the same 10
        # entries the legacy module-level constant had — proves the
        # promotion to config is behavior-preserving for the default
        # case (which is every existing user).
        from ppxai.config import get_file_tree_ignore_dirs, DEFAULT_FILE_TREE_IGNORE_DIRS

        expected = {
            '.git', 'node_modules', '__pycache__',
            '.venv', 'venv', '.tox',
            'dist', 'build', '.eggs', '.mypy_cache',
        }
        assert set(DEFAULT_FILE_TREE_IGNORE_DIRS) == expected
        # The function may pick up user config — but at the very least
        # the DEFAULT constant should match.

    def test_returns_a_set_not_a_list(self):
        # Set membership is O(1); the call sites do `x in ignored` and
        # `any(d in path.parts for d in ignored)` — both want set perf.
        from ppxai.config import get_file_tree_ignore_dirs
        assert isinstance(get_file_tree_ignore_dirs(), set)

    def test_user_override_replaces_default(self, monkeypatch):
        # REPLACE semantics — a user list of ['only-this'] hides ONLY
        # 'only-this', NOT the legacy defaults plus 'only-this'. Forces
        # the user to copy-edit the defaults if they want to ADD; this
        # is the predictable "what you write is what you get" shape.
        from ppxai.config.store import ConfigStore
        store = ConfigStore.get_instance()
        original = dict(store.config)
        try:
            store.config["file_tree"] = {"ignore_dirs": ["only-this"]}
            from ppxai.config import get_file_tree_ignore_dirs
            assert get_file_tree_ignore_dirs() == {"only-this"}
            # venv is no longer hidden under this override
            assert "venv" not in get_file_tree_ignore_dirs()
        finally:
            store.config.clear()
            store.config.update(original)

    def test_loader_carries_file_tree_through(self, monkeypatch, tmp_path):
        # Regression: v1.18.7 shipped the feature but forgot to add
        # `file_tree` to the explicit allowlist of top-level keys in
        # load_config() — so users could set the key in their JSON
        # and the loader would silently drop it on the floor. The
        # other unit tests in this file all patched store.config in
        # memory, bypassing the loader entirely, so the bug stayed
        # hidden until coder.trad.int dogfooding caught it.
        #
        # This test runs the loader on a real JSON file with the
        # override set and asserts the file_tree key survives.
        import json
        cfg_path = tmp_path / "ppxai-config.json"
        cfg_path.write_text(json.dumps({
            "default_provider": "perplexity",
            "providers": {
                "perplexity": {
                    "name": "Perplexity",
                    "base_url": "https://api.perplexity.ai",
                    "api_key_env": "PERPLEXITY_API_KEY",
                    "models": {"sonar-pro": {"name": "Sonar Pro"}},
                },
            },
            "file_tree": {
                "ignore_dirs": [".git", "node_modules"],  # NO venv/.venv
            },
        }))
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg_path))

        from ppxai.config.loader import load_config
        cfg = load_config()
        assert "file_tree" in cfg, (
            "load_config() dropped the file_tree top-level key — see "
            "the allowlist in ppxai/config/loader.py near 'paths'."
        )
        assert cfg["file_tree"] == {"ignore_dirs": [".git", "node_modules"]}

        # And the full chain: ConfigStore.reload() picks it up, and
        # get_file_tree_ignore_dirs() returns the override (not the
        # default that has venv in it).
        from ppxai.config.store import ConfigStore
        from ppxai.config import get_file_tree_ignore_dirs
        store = ConfigStore.get_instance()
        original = dict(store.config)
        try:
            store.reload()
            ignored = get_file_tree_ignore_dirs()
            assert ignored == {".git", "node_modules"}
            assert "venv" not in ignored
            assert ".venv" not in ignored
        finally:
            store.config.clear()
            store.config.update(original)

    def test_empty_list_disables_all_ignoring(self, monkeypatch):
        # An explicit empty list means "show everything" — useful for
        # power users who want to see node_modules etc. in the tree.
        from ppxai.config.store import ConfigStore
        store = ConfigStore.get_instance()
        original = dict(store.config)
        try:
            store.config["file_tree"] = {"ignore_dirs": []}
            from ppxai.config import get_file_tree_ignore_dirs
            assert get_file_tree_ignore_dirs() == set()
        finally:
            store.config.clear()
            store.config.update(original)

    def test_invalid_type_falls_back_to_defaults(self, monkeypatch):
        # If ignore_dirs is set to something that isn't a list (string,
        # int, dict), the loader logs a warning and falls back to the
        # default set instead of crashing.
        from ppxai.config.store import ConfigStore
        store = ConfigStore.get_instance()
        original = dict(store.config)
        try:
            store.config["file_tree"] = {"ignore_dirs": "venv"}  # str, not list
            from ppxai.config import get_file_tree_ignore_dirs, DEFAULT_FILE_TREE_IGNORE_DIRS
            assert get_file_tree_ignore_dirs() == set(DEFAULT_FILE_TREE_IGNORE_DIRS)
        finally:
            store.config.clear()
            store.config.update(original)


# ---------------------------------------------------------------------------
# End-to-end via HTTP routes
# ---------------------------------------------------------------------------


@pytest.fixture
def http_client():
    import ppxai.server.http as http_module
    with TestClient(http_module.app, raise_server_exceptions=False) as client:
        yield client


def _session(name: str) -> dict:
    return {"X-Session-Id": f"ftignore-{name}"}


def _anchor_to(client: TestClient, headers: dict, path: Path) -> None:
    client.post(
        "/context/working_dir",
        json={"path": str(path)},
        headers=headers,
    )


def _has_label(node, target):
    if node.get("label") == target:
        return True
    for c in node.get("children", []):
        if _has_label(c, target):
            return True
    return False


class TestFilesListHonorsIgnoreConfig:
    """The /files/list route calls get_file_tree_ignore_dirs() at
    request time. Per-session config reload in get_or_create_session
    wipes in-memory ConfigStore mutations, so to test the override
    behavior we monkeypatch the function the route actually calls.
    Unit tests above already prove the function reads ConfigStore."""

    def test_default_hides_venv(self, http_client, tmp_path):
        # Default config hides venv but shows the regular dir.
        (tmp_path / "venv").mkdir()
        (tmp_path / "src").mkdir()
        headers = _session("default-hide-venv")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.get("/files/list", headers=headers)
        assert resp.status_code == 200, resp.text
        names = [f["name"] for f in resp.json()["files"]]
        assert "src/" in names
        assert "venv/" not in names

    def test_override_unhides_venv(self, http_client, tmp_path, monkeypatch):
        # Patch the route's view of get_file_tree_ignore_dirs to
        # return a set that excludes venv. Proves the route honors
        # whatever the function returns — config wiring is unit-tested.
        (tmp_path / "venv").mkdir()
        (tmp_path / "src").mkdir()
        headers = _session("override-unhide-venv")
        _anchor_to(http_client, headers, tmp_path)

        import ppxai.server.routes.files as files_module
        monkeypatch.setattr(
            files_module, "get_file_tree_ignore_dirs",
            lambda: {'.git', 'node_modules', '__pycache__',
                     '.tox', 'dist', 'build', '.eggs', '.mypy_cache'},
        )

        resp = http_client.get("/files/list", headers=headers)
        assert resp.status_code == 200, resp.text
        names = [f["name"] for f in resp.json()["files"]]
        assert "src/" in names
        assert "venv/" in names  # No longer hidden

    def test_empty_list_shows_everything(self, http_client, tmp_path, monkeypatch):
        (tmp_path / "venv").mkdir()
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "src").mkdir()
        headers = _session("empty-shows-all")
        _anchor_to(http_client, headers, tmp_path)

        import ppxai.server.routes.files as files_module
        monkeypatch.setattr(files_module, "get_file_tree_ignore_dirs", lambda: set())

        resp = http_client.get("/files/list", headers=headers)
        assert resp.status_code == 200, resp.text
        names = [f["name"] for f in resp.json()["files"]]
        assert "src/" in names
        assert "venv/" in names
        assert "node_modules/" in names


class TestFilesTreeHonorsIgnoreConfig:
    """Symmetry with /files/list — the tree endpoint also honors the
    config. Tree route resolves the set ONCE per request (closure over
    `build_tree`) rather than per directory, so deeply-nested trees
    don't pay per-dir config-lookup cost."""

    def test_default_hides_venv_in_tree(self, http_client, tmp_path):
        (tmp_path / "venv").mkdir()
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x", encoding="utf-8")
        headers = _session("tree-default-hide-venv")
        _anchor_to(http_client, headers, tmp_path)

        resp = http_client.get("/files/tree?depth=3", headers=headers)
        assert resp.status_code == 200, resp.text
        tree = resp.json()["tree"]
        assert _has_label(tree, "src/")
        assert not _has_label(tree, "venv/")

    def test_override_unhides_venv_in_tree(self, http_client, tmp_path, monkeypatch):
        (tmp_path / "venv").mkdir()
        (tmp_path / "src").mkdir()
        headers = _session("tree-override-unhide-venv")
        _anchor_to(http_client, headers, tmp_path)

        import ppxai.server.routes.files as files_module
        monkeypatch.setattr(
            files_module, "get_file_tree_ignore_dirs",
            lambda: {'.git', 'node_modules', '__pycache__',
                     '.tox', 'dist', 'build', '.eggs', '.mypy_cache'},
        )

        resp = http_client.get("/files/tree?depth=3", headers=headers)
        assert resp.status_code == 200, resp.text
        tree = resp.json()["tree"]
        assert _has_label(tree, "src/")
        assert _has_label(tree, "venv/")
