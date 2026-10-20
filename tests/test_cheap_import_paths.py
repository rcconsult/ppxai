"""The cheap paths stay cheap (ADR 0016 §6, §7).

`ppxai/__init__.py` re-exports the config and `__version__` only, so
`import ppxai.version` (what `--version` banners and the SSH hub's probes
reach first) loads neither the engine nor any provider SDK. `from ppxai
import EngineClient` is gone; `from ppxai.engine import EngineClient` is the
form. And `ppxai-server`'s probes (`--version`, `--registry-contract`,
`--list --json`) load neither the Anthropic nor the Google SDK.

Each is measured in a fresh interpreter: the test process has long since
imported everything.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import ppxai
from ppxai.engine import EngineClient

REPO = Path(__file__).resolve().parent.parent

HEAVY = ("ppxai.engine", "openai", "anthropic", "google.genai", "fastapi")


def _loaded(code: str, watch=HEAVY) -> list[str]:
    """Which of `watch` are in sys.modules when `code` finishes or exits."""
    probe = textwrap.dedent(f"""
        import atexit, sys
        atexit.register(lambda: print(
            "LOADED=" + ",".join(m for m in {list(watch)!r} if m in sys.modules), flush=True))
    """) + textwrap.dedent(code)
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                         timeout=120, cwd=REPO)
    lines = [ln for ln in out.stdout.splitlines() if ln.startswith("LOADED=")]
    assert lines, f"probe printed nothing (rc={out.returncode}): {out.stdout!r} {out.stderr!r}"
    return [m for m in lines[-1][len("LOADED="):].split(",") if m]


class TestThePackageIsLight:
    def test_import_ppxai_version_loads_nothing_heavy(self):
        assert _loaded("import ppxai.version") == []

    def test_import_ppxai_loads_nothing_heavy(self):
        assert _loaded("import ppxai") == []

    def test_the_probe_sees_a_heavy_import(self):
        """Control: importing the engine does register."""
        assert "ppxai.engine" in _loaded("import ppxai.engine")

    def test_engine_client_is_not_re_exported(self):
        assert "EngineClient" not in ppxai.__all__
        assert not hasattr(ppxai, "EngineClient")

    def test_the_documented_form_still_works(self):
        assert EngineClient.__module__ == "ppxai.engine.client"


class TestServerProbes:
    #: `openai` is not in the list: `engine/search/perplexity.py` imports it
    #: at module top (owner decision 3, ADR 0016), and the probes run after
    #: the server module is imported.
    SDKS = ("anthropic", "google.genai")

    @pytest.mark.parametrize("argv", [["--version"], ["--registry-contract"], ["--list", "--json"]])
    def test_a_probe_loads_no_optional_sdk(self, argv, tmp_path):
        code = f"""
            import os, sys
            os.environ["HOME"] = {str(tmp_path)!r}
            os.environ["USERPROFILE"] = {str(tmp_path)!r}
            sys.argv = ["ppxai-server"] + {argv!r}
            from ppxai.server.http import run_server
            run_server()
        """
        assert _loaded(code, watch=self.SDKS) == []
