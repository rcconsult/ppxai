"""ppxai-desktop stops the server it started, child included.

The installed ppxai-server is a PyInstaller one-file build: the process the
launcher spawns is a bootloader and the real server is its child. When the
server does not come up in time the launcher used to call
`process.terminate()`, which on Windows ends the bootloader alone and leaves
the server holding port 54320. `stop_server()` takes the whole tree:
`taskkill /T /F` on Windows, the process group on Unix (the server is spawned
with `start_new_session=True`). See
docs/lessons/killing-a-onefile-binary-kills-only-its-bootloader.md.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_LAUNCHER = Path(__file__).resolve().parents[1] / "ppxai-desktop.py"

#: A stand-in for the one-file bootloader: it starts a child, prints the
#: child's PID, and waits. Like a plain parent it forwards nothing.
_BOOTLOADER = textwrap.dedent("""
    import subprocess, sys
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    print(child.pid, flush=True)
    child.wait()
""")


@pytest.fixture()
def launcher():
    spec = importlib.util.spec_from_file_location("ppxai_desktop", _LAUNCHER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still answers kill(0); reap check via ps would be overkill,
    # so treat "answers" as alive and let the deadline loop below decide.
    return True


def _wait_gone(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def _spawn_tree():
    proc = subprocess.Popen([sys.executable, "-c", _BOOTLOADER],
                            stdout=subprocess.PIPE, text=True, start_new_session=True)
    child_pid = int(proc.stdout.readline())
    return proc, child_pid


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are POSIX")
class TestUnixStopsTheGroup:
    def test_stop_server_ends_the_child_too(self, launcher):
        proc, child = _spawn_tree()
        try:
            launcher.stop_server(proc)
            proc.wait(timeout=5)
            assert _wait_gone(child), "the server child survived stop_server()"
        finally:
            for pid in (proc.pid, child):
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass

    def test_terminating_only_the_parent_orphans_the_child(self):
        """Control: the trap is real for this stand-in, so the test above means something."""
        proc, child = _spawn_tree()
        try:
            proc.terminate()
            proc.wait(timeout=5)
            time.sleep(0.2)
            assert _alive(child)
        finally:
            try:
                os.kill(child, 9)
            except ProcessLookupError:
                pass


class TestWindowsTakesTheTree:
    def test_taskkill_walks_the_tree(self, launcher, monkeypatch):
        calls = []
        monkeypatch.setattr(launcher.sys, "platform", "win32")
        monkeypatch.setattr(launcher.subprocess, "run",
                            lambda args, **kw: calls.append(args))
        proc = SimpleNamespace(pid=4242, poll=lambda: None,
                               terminate=lambda: pytest.fail("bootloader-only kill"))

        launcher.stop_server(proc)

        assert calls == [["taskkill", "/PID", "4242", "/T", "/F"]]

    def test_missing_taskkill_falls_back_to_the_bootloader(self, launcher, monkeypatch):
        def boom(args, **kw):
            raise FileNotFoundError("taskkill")
        terminated = []
        monkeypatch.setattr(launcher.sys, "platform", "win32")
        monkeypatch.setattr(launcher.subprocess, "run", boom)
        proc = SimpleNamespace(pid=1, poll=lambda: None, terminate=lambda: terminated.append(1))

        launcher.stop_server(proc)

        assert terminated == [1]

    def test_an_exited_server_is_left_alone(self, launcher, monkeypatch):
        monkeypatch.setattr(launcher.subprocess, "run",
                            lambda *a, **kw: pytest.fail("nothing to kill"))
        launcher.stop_server(SimpleNamespace(pid=1, poll=lambda: 0))


class TestTheLauncherUsesIt:
    def test_main_never_terminates_the_bootloader_directly(self):
        tree = ast.parse(_LAUNCHER.read_text(encoding="utf-8"))
        main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
        calls = {n.func.attr for n in ast.walk(main)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        names = {n.func.id for n in ast.walk(main)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert "terminate" not in calls and "kill" not in calls
        assert "stop_server" in names
