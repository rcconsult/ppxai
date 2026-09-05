"""A project-local `ppxai-config.json` is READ-ONLY. Writes go to the user config.

Reads and writes resolve differently on purpose:

    read     PPXAI_CONFIG_FILE -> ./ppxai-config.json -> ~/.ppxai/...
    write    PPXAI_CONFIG_FILE -> ~/.ppxai/...

`./ppxai-config.json` is dropped from the write path because it is a file a
project *ships* — checked in, shared, often an example. Persisting a UI
toggle into it edits somebody's repository as a side effect.

This is not hypothetical. Until v1.19.1 `set_tui_config` wrote to
`find_config_file()`, and ppxai's own suite therefore rewrote ppxai's own
tracked `ppxai-config.json` on every run (debt Item 70): a smoke test POSTs
a body to every route, `/debug-log` persists a setting, and pytest's cwd is
the repo root. Nothing failed — the rewrite was an encoding round-trip — so
it survived for as long as anyone was willing to type `git checkout --`.

`USER_CONFIG_FILE` is patched on its DEFINING module, never via `HOME`: it
is `Path.home() / ".ppxai" / ...` evaluated at import, so a monkeypatched
`HOME` moves nothing. That trap has cost this repo real time before.
"""

from __future__ import annotations

import json
import logging

import pytest

from ppxai.config import features, loader


@pytest.fixture
def user_home(tmp_path, monkeypatch):
    """Redirect the user config at its defining module. Yields the path."""
    user_config = tmp_path / "userhome" / ".ppxai" / "ppxai-config.json"
    monkeypatch.setattr(loader, "USER_CONFIG_FILE", user_config)
    monkeypatch.delenv("PPXAI_CONFIG_FILE", raising=False)
    return user_config


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """cwd holding a project config, as a checkout would. Yields the file."""
    project = tmp_path / "checkout"
    project.mkdir()
    project_config = project / "ppxai-config.json"
    project_config.write_text(
        json.dumps({"providers": {}, "tui": {"theme": "shipped"}}, indent=2),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)
    return project_config


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch):
    """Keep `set_tui_config`'s in-memory update off the real singleton."""
    class _Store:
        def __init__(self):
            self._config = {}

        @property
        def config(self):
            return self._config

    store = _Store()
    monkeypatch.setattr(features.ConfigStore, "get_instance",
                        classmethod(lambda cls: store))
    return store


class TestWriteTargetNeverTheProjectConfig:
    """The invariant, stated four ways."""

    def test_project_config_is_not_the_write_target(self, user_home, project_dir):
        assert loader.find_config_file() == project_dir.relative_to(project_dir.parent) \
            or loader.find_config_file().name == "ppxai-config.json"
        assert loader.find_writable_config_file() == user_home

    def test_setting_leaves_the_project_config_byte_identical(
        self, user_home, project_dir
    ):
        before = project_dir.read_bytes()

        assert features.set_tui_config("debug_log", True) is True

        assert project_dir.read_bytes() == before, (
            "a UI toggle rewrote the project's checked-in config"
        )
        assert json.loads(user_home.read_text(encoding="utf-8")) == {
            "tui": {"debug_log": True}
        }

    def test_the_repo_config_survives_the_route_that_caused_item_70(
        self, user_home, project_dir
    ):
        """The exact shape of Item 70: `/debug-log` under a project cwd."""
        before = project_dir.read_bytes()

        features.set_tui_config("debug_log", False)   # POST /debug-log
        features.set_tui_config("debug_log", True)

        assert project_dir.read_bytes() == before

    def test_write_target_creates_the_user_dir(self, user_home, project_dir):
        assert not user_home.parent.exists()
        assert loader.find_writable_config_file() == user_home
        assert user_home.parent.is_dir(), "callers must not have to mkdir"


class TestExplicitEnvOverrideStaysWritable:
    """`PPXAI_CONFIG_FILE` is somebody's deliberate act, so it keeps writes."""

    def test_env_target_is_written(self, tmp_path, monkeypatch, project_dir):
        target = tmp_path / "explicit" / "ppxai-config.json"
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(target))

        assert loader.find_writable_config_file() == target
        assert features.set_tui_config("theme", "midnight") is True
        assert json.loads(target.read_text(encoding="utf-8"))["tui"]["theme"] == "midnight"
        assert "midnight" not in project_dir.read_text(encoding="utf-8")


class TestShadowedWriteIsNotSilent:
    """Reads take the FIRST config found; they do not merge."""

    def test_warns_naming_both_paths(
        self, user_home, project_dir, caplog
    ):
        with caplog.at_level(logging.WARNING, logger="ppxai.config"):
            features.set_tui_config("debug_log", True)

        warnings = [r.getMessage() for r in caplog.records
                    if r.levelno >= logging.WARNING]
        assert any(str(user_home) in m and "shadows it" in m for m in warnings), (
            f"expected a shadow warning naming both paths, got: {warnings}"
        )

    def test_no_warning_when_the_paths_agree(self, user_home, tmp_path,
                                             monkeypatch, caplog):
        monkeypatch.chdir(tmp_path)          # no project config in cwd
        user_home.parent.mkdir(parents=True, exist_ok=True)
        user_home.write_text("{}", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="ppxai.config"):
            features.set_tui_config("debug_log", True)

        assert not [r for r in caplog.records if "shadows it" in r.getMessage()]
