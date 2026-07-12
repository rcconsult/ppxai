"""install_web_ui() version gate — the desktop launcher must not clobber
same-version local web syncs (live 2026-07-12: a hotfixed
task-run-view.js in ~/.ppxai/web was silently reverted to the binary's
build-time snapshot on every ppxai-desktop launch; same mechanism behind
the 2026-06-19 macOS "web dir reverts after launching the .app"
observation). The launcher lives at the repo ROOT (ppxai-desktop.py, the
PyInstaller entry) — NOT inside ppxai/ — which is why earlier searches
for the copier came up empty.

Contract pinned here:
  - fresh install → bundle copied, `.installed-by` marker = launcher version
  - same-version marker → local edits + extra files SURVIVE a launch
  - different-version marker (upgrade) → refreshed from the bundle
  - legacy install (no marker) → refreshed once, marker written
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_LAUNCHER = Path(__file__).resolve().parents[1] / "ppxai-desktop.py"


@pytest.fixture()
def launcher(monkeypatch, tmp_path):
    """Import the root launcher script and sandbox it into tmp_path."""
    spec = importlib.util.spec_from_file_location("ppxai_desktop", _LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(mod.Path, "home", classmethod(lambda cls: home))

    bundle = tmp_path / "bundle-web"
    bundle.mkdir()
    (bundle / "index.html").write_text("<bundle index>", encoding="utf-8")
    sub = bundle / "components"
    sub.mkdir()
    (sub / "task-run-view.js").write_text("bundle view", encoding="utf-8")
    monkeypatch.setattr(mod, "get_resource_path", lambda rel: bundle)

    return mod, home / ".ppxai" / "web"


def test_fresh_install_copies_bundle_and_writes_marker(launcher):
    mod, web_dir = launcher
    out = mod.install_web_ui()
    assert out == web_dir
    assert (web_dir / "index.html").read_text(encoding="utf-8") == "<bundle index>"
    assert (web_dir / "components" / "task-run-view.js").exists()
    assert (web_dir / ".installed-by").read_text(encoding="utf-8").strip() == mod.__version__


def test_same_version_local_edits_survive_relaunch(launcher):
    # The live bug: a synced hotfix (different SIZE than the bundle) was
    # reverted on every launch by the old name+size comparison.
    mod, web_dir = launcher
    mod.install_web_ui()
    hotfix = web_dir / "components" / "task-run-view.js"
    hotfix.write_text("bundle view PLUS A HOTFIX (bigger than the bundle's)",
                      encoding="utf-8")
    extra = web_dir / "components" / "new-view.js"
    extra.write_text("added after install", encoding="utf-8")

    mod.install_web_ui()  # relaunch

    assert "HOTFIX" in hotfix.read_text(encoding="utf-8"), \
        "same-version launch clobbered a local web sync"
    assert extra.exists(), "same-version launch deleted a locally added file"


def test_version_change_refreshes_from_bundle(launcher):
    mod, web_dir = launcher
    mod.install_web_ui()
    (web_dir / "components" / "task-run-view.js").write_text("local edit",
                                                             encoding="utf-8")
    # Simulate an older install: the marker was written by a previous version.
    (web_dir / ".installed-by").write_text("0.0.1\n", encoding="utf-8")

    mod.install_web_ui()  # upgrade launch

    assert (web_dir / "components" / "task-run-view.js").read_text(
        encoding="utf-8") == "bundle view", "upgrade did not refresh the web assets"
    assert (web_dir / ".installed-by").read_text(
        encoding="utf-8").strip() == mod.__version__


def test_legacy_install_without_marker_refreshes_once(launcher):
    mod, web_dir = launcher
    (web_dir / "components").mkdir(parents=True)
    (web_dir / "components" / "task-run-view.js").write_text("pre-marker era",
                                                             encoding="utf-8")

    mod.install_web_ui()

    assert (web_dir / "components" / "task-run-view.js").read_text(
        encoding="utf-8") == "bundle view"
    assert (web_dir / ".installed-by").exists()
    # And the refresh happens only ONCE: the second launch respects edits.
    (web_dir / "index.html").write_text("edited", encoding="utf-8")
    mod.install_web_ui()
    assert (web_dir / "index.html").read_text(encoding="utf-8") == "edited"
