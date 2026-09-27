"""An embedder's `EngineClient()` works without calling `initialize()` first.

Found 2026-09-27 by ppxai-sre: its manager built `EngineClient()` without
`ppxai.config.initialize()`, so PROVIDERS was empty and every
`set_provider()` returned False. The manager never switched provider and
nothing said so. `EngineClient.__init__` now calls
`ppxai.config.ensure_initialized()`.

The first test needs a fresh interpreter: this suite's `pytest_configure`
has already initialized config in-process, which is exactly the state that
hid the bug.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import ppxai.config as config_pkg

REPO = Path(__file__).resolve().parent.parent

_PROBE = textwrap.dedent("""
    import ppxai.config as c
    assert c._initialized is False, "probe must start uninitialized"
    from ppxai.engine import EngineClient
    engine = EngineClient()
    assert c._initialized is True
    assert "gemini" in engine.providers_config, sorted(engine.providers_config)
    assert engine.set_provider("gemini") is True
    print("OK", engine.provider_name, engine.model)
""")


def test_a_fresh_process_engine_sees_its_providers(tmp_path):
    env = {
        k: v for k, v in os.environ.items()
        if not k.endswith("_API_KEY") and k != "MODEL_PROVIDER"
    }
    env.update({
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "PPXAI_CONFIG_FILE": str(REPO / "ppxai-config.json"),
        "GEMINI_API_KEY": "test-not-a-key",
    })
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    # First-run seeding prints a notice before the probe's own line.
    assert proc.stdout.strip().splitlines()[-1].startswith("OK gemini ")


def test_ensure_initialized_does_not_rerun_a_completed_initialize(monkeypatch):
    """Re-running would re-read PROVIDERS and discard in-place changes."""
    assert config_pkg._initialized is True
    monkeypatch.setitem(config_pkg.PROVIDERS, "sentinel-provider", {"name": "S"})
    config_pkg.ensure_initialized()
    assert "sentinel-provider" in config_pkg.PROVIDERS


def test_ensure_initialized_runs_initialize_when_needed(monkeypatch):
    calls = []
    monkeypatch.setattr(config_pkg, "_initialized", False)
    monkeypatch.setattr(config_pkg, "initialize", lambda: calls.append(1))
    config_pkg.ensure_initialized()
    assert calls == [1]


@pytest.mark.parametrize("name", ["ensure_initialized"])
def test_it_is_public(name):
    assert name in config_pkg.__all__
