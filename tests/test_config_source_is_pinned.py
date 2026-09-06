"""The suite's config SOURCE is pinned; the developer's own config is unreachable.

Debt Item 69. `find_config_file()` resolves

    PPXAI_CONFIG_FILE -> ./ppxai-config.json -> ~/.ppxai/ppxai-config.json

and takes the first hit. Nothing pinned it, so any test that reached provider
config read whichever file the developer happened to have, and its verdict
varied by machine, by cwd, and by the state of a file that is not under
version control.

It failed in the dangerous direction. On 2026-09-01
`test_the_message_names_the_capable_models` passed in the main checkout and
failed in a worktree at the same commit, because the developer's `~/.ppxai`
config still carried `sonar-pro` / `sonar-reasoning-pro` — ids retired from
both shipped configs in `e6c366b9`. The personal file MASKED a real
regression; a machine-specific green looks exactly like a correct one until
CI or a user finds it.

`tests/conftest.py` now pins the env var and redirects the fallback
constant. **This file is what makes that pin loud.** Without it the pin is
itself unverified state: it could be silently dropped by a refactor, and the
suite would go back to reading personal config with nothing to say so — the
same shape as a tripwire that passes while the bug is live.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from ppxai.config import loader
from tests.conftest import REPO_CONFIG_FILE

#: The real user config, computed independently of the patched constant.
REAL_USER_CONFIG = Path.home() / ".ppxai" / "ppxai-config.json"


class TestTheSourceIsPinned:
    def test_the_env_var_names_the_repo_config(self):
        assert os.environ.get("PPXAI_CONFIG_FILE") == str(REPO_CONFIG_FILE)

    def test_resolution_lands_on_the_shipped_config(self):
        resolved = loader.find_config_file()
        assert resolved is not None
        assert resolved.resolve() == REPO_CONFIG_FILE.resolve()

    def test_the_fallback_constant_is_redirected_out_of_the_real_home(self):
        """The conftest fixture must actually be installed."""
        assert loader.USER_CONFIG_FILE.resolve() != REAL_USER_CONFIG.resolve()
        assert not loader.USER_CONFIG_FILE.exists()


class TestTheDevelopersConfigStaysUnreachable:
    """The hole the env pin alone does not close."""

    def test_a_cleared_environment_does_not_reach_the_user_config(
        self, tmp_path, monkeypatch
    ):
        """`patch.dict(os.environ, {}, clear=True)` is common in this suite.

        Combined with a cwd that has no project config, that used to fall
        straight through to `~/.ppxai/ppxai-config.json`.
        """
        monkeypatch.chdir(tmp_path)

        with patch.dict(os.environ, {}, clear=True):
            resolved = loader.find_config_file()

        assert resolved is None or resolved.resolve() != REAL_USER_CONFIG.resolve(), (
            f"config resolution reached the developer's own file "
            f"({resolved}) — this test run's verdicts depend on machine state"
        )

    def test_a_write_cannot_land_in_the_real_home_either(self, tmp_path, monkeypatch):
        """`find_writable_config_file()` reads the same redirected constant."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PPXAI_CONFIG_FILE", raising=False)

        target = loader.find_writable_config_file()

        assert target.resolve() != REAL_USER_CONFIG.resolve()


class TestTheRegressionThatMotivatedThis:
    """The concrete 2026-09-01 case, pinned so it cannot come back."""

    def test_the_shipped_config_carries_no_retired_perplexity_ids(self):
        """`sonar-pro` / `sonar-reasoning-pro` were retired in e6c366b9.

        A developer config still carrying them made a real regression pass.
        Asserting on the file the suite is now pinned to means this fails on
        every machine or none — which is the entire point of the pin.
        """
        text = REPO_CONFIG_FILE.read_text(encoding="utf-8")

        for retired in ("sonar-pro", "sonar-reasoning-pro"):
            assert f'"{retired}"' not in text, (
                f"{retired} is back in the shipped config; it was retired in "
                "e6c366b9 and 400s on the Responses wire (debt Item 64)"
            )
