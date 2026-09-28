"""An announced server runs in, and reports, the directory it was launched in.

Found by win32-ppxai's live hub run (2026-09-28): a server the hub launched on
WSL reported `workdir` = `~/.local/bin`. The frozen `ppxai-server` entry
script (`ppxai-server.py`) chdirs to its own binary's directory, so the
announce path's `os.getcwd()` named the binary's directory whatever directory
the hub had `cd`-ed into -- and the remote engine's tools ran there too. The
source-run tests never saw it: only a PyInstaller build is `frozen`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ppxai.server import http as http_module

ENTRY = Path(__file__).resolve().parent.parent / "ppxai-server.py"


class TestTheFrozenEntryScript:
    def test_it_records_the_launch_directory_before_moving(self, tmp_path):
        launch = tmp_path / "project"
        launch.mkdir()
        bindir = tmp_path / "bin"
        bindir.mkdir()
        # Run the real entry script as a frozen binary would, without serving:
        # run_name != "__main__", so run_server() is not called.
        probe = (
            "import json, os, runpy, sys\n"
            "sys.frozen = True\n"
            f"sys.executable = {str(bindir / 'ppxai-server')!r}\n"
            f"runpy.run_path({str(ENTRY)!r}, run_name='probe')\n"
            "print(json.dumps({'cwd': os.getcwd(), 'launch': os.environ.get('PPXAI_LAUNCH_CWD')}))\n"
        )
        env = {k: v for k, v in os.environ.items() if k != "PPXAI_LAUNCH_CWD"}
        done = subprocess.run([sys.executable, "-c", probe], cwd=str(launch), env=env,
                              capture_output=True, text=True, timeout=120)
        assert done.returncode == 0, done.stderr
        seen = json.loads(done.stdout.strip().splitlines()[-1])
        assert os.path.realpath(seen["cwd"]) == os.path.realpath(bindir)
        assert os.path.realpath(seen["launch"]) == os.path.realpath(launch)


class TestAnnouncedWorkdir:
    def test_the_launch_directory_wins_and_becomes_the_cwd(self, tmp_path, monkeypatch):
        launch = tmp_path / "project"
        launch.mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PPXAI_LAUNCH_CWD", str(launch))
        assert http_module._announced_workdir() == str(launch)
        assert os.path.realpath(os.getcwd()) == os.path.realpath(launch)
        assert "PPXAI_LAUNCH_CWD" not in os.environ, "must not leak into tool subprocesses"

    def test_without_it_the_cwd_is_kept(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PPXAI_LAUNCH_CWD", raising=False)
        assert os.path.realpath(http_module._announced_workdir()) == os.path.realpath(tmp_path)

    def test_a_vanished_launch_directory_falls_back_to_the_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("PPXAI_LAUNCH_CWD", str(tmp_path / "gone"))
        assert os.path.realpath(http_module._announced_workdir()) == os.path.realpath(tmp_path)
