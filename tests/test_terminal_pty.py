"""PtyProcess.kill() must terminate a SIGTERM-ignoring child promptly.

Interactive shells ignore SIGTERM (POSIX job control). Before v1.19.1 the
kill path did SIGTERM + blocking ``waitpid(pid, 0)`` on the event loop
thread, so closing a terminal whose shell had finished initializing froze
the entire server (every endpoint, including /health).
"""

import os
import platform
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(
    platform.system() == "Windows", reason="PTY is Unix-only"
)


def test_kill_returns_promptly_for_sigterm_ignoring_child(tmp_path):
    from ppxai.server.routes.terminal import PtyProcess

    script = tmp_path / "stubborn.sh"
    script.write_text("#!/bin/sh\ntrap '' TERM HUP\nwhile :; do sleep 0.1; done\n")
    script.chmod(0o755)

    proc = PtyProcess(str(script), str(tmp_path))
    proc.spawn()
    time.sleep(0.5)  # let the trap install (mirrors an initialized shell)
    child = proc.child_pid

    # Run kill() in a thread so a regression to blocking waitpid shows up as
    # a clean assertion failure instead of hanging the test session.
    t = threading.Thread(target=proc.kill, daemon=True)
    start = time.monotonic()
    t.start()
    t.join(timeout=8)
    elapsed = time.monotonic() - start

    assert not t.is_alive(), "kill() blocked (regression: blocking waitpid)"
    assert elapsed < 5, f"kill() took {elapsed:.1f}s"
    assert proc.child_pid is None
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)  # child must actually be gone


def test_kill_returns_promptly_when_child_is_never_reapable(tmp_path):
    """The SIGKILL backstop must be bounded too.

    `kill()` fell back to a plain `os.waitpid(pid, 0)` after SIGKILL. SIGKILL
    does not make that safe: a child STOPPED by job control is not reaped by
    a waitpid without WUNTRACED, so the call waits for an exit that never
    comes. That is the same unbounded wait the method's docstring exists to
    avoid, left on the backstop path — and it hung the whole suite via
    test_spawn_launches_interactive_shell_with_history, which calls kill()
    directly rather than in a thread.

    Simulated with a waitpid that never reports the child as reaped, which is
    what a stopped child looks like to this code.
    """
    from unittest.mock import patch

    from ppxai.server.routes.terminal import PtyProcess

    script = tmp_path / "sleeper.sh"
    script.write_text("#!/bin/sh\nwhile :; do sleep 0.1; done\n")
    script.chmod(0o755)

    proc = PtyProcess(str(script), str(tmp_path))
    proc.spawn()
    time.sleep(0.3)

    real_waitpid = os.waitpid

    def never_reaped(pid, options):
        if options == 0:            # the unbounded form -- must not be used
            raise AssertionError(
                "kill() used a blocking waitpid(pid, 0); that is the hang"
            )
        return (0, 0)               # WNOHANG: "not reaped yet", forever

    with patch("os.waitpid", side_effect=never_reaped):
        t = threading.Thread(target=proc.kill, daemon=True)
        start = time.monotonic()
        t.start()
        t.join(timeout=12)
        elapsed = time.monotonic() - start

    assert not t.is_alive(), "kill() blocked on an unreapable child"
    assert elapsed < 10, f"kill() took {elapsed:.1f}s"
    assert proc.child_pid is None

    # Don't leave the real process behind now that waitpid is un-patched.
    try:
        real_waitpid(-1, os.WNOHANG)
    except (ChildProcessError, OSError):
        pass


def test_kill_reaps_cooperative_child_quickly(tmp_path):
    from ppxai.server.routes.terminal import PtyProcess

    script = tmp_path / "cooperative.sh"
    script.write_text("#!/bin/sh\nwhile :; do sleep 0.1; done\n")
    script.chmod(0o755)

    proc = PtyProcess(str(script), str(tmp_path))
    proc.spawn()
    time.sleep(0.2)

    start = time.monotonic()
    proc.kill()
    assert time.monotonic() - start < 3
    assert proc.child_pid is None


# ---------------------------------------------------------------------------
# Interactive-shell fix: the browser terminal must give history + line editing.
# ---------------------------------------------------------------------------


class TestResolveTerminalShell:
    """The unconfigured fallback must not land on /bin/sh→dash (no history,
    no readline). It prefers bash so the browser terminal behaves like a real
    shell — the user-reported "no command history / line editing" symptom."""

    def test_config_value_wins(self, monkeypatch):
        from ppxai.server.routes.terminal import _resolve_terminal_shell
        monkeypatch.setenv("SHELL", "/usr/bin/zsh")
        assert _resolve_terminal_shell("/opt/custom/fish") == "/opt/custom/fish"

    def test_env_shell_next(self, monkeypatch):
        from ppxai.server.routes.terminal import _resolve_terminal_shell
        monkeypatch.setenv("SHELL", "/usr/bin/zsh")
        assert _resolve_terminal_shell(None) == "/usr/bin/zsh"

    def test_prefers_bash_when_no_config_no_env(self, monkeypatch):
        # THE coder case: $SHELL empty, no config → must pick bash, not /bin/sh.
        from ppxai.server.routes import terminal
        monkeypatch.delenv("SHELL", raising=False)
        monkeypatch.setattr(
            terminal.shutil, "which",
            lambda n: "/usr/bin/bash" if n == "bash" else None,
        )
        assert terminal._resolve_terminal_shell(None) == "/usr/bin/bash"

    def test_falls_back_to_sh_only_when_no_bash(self, monkeypatch):
        from ppxai.server.routes import terminal
        monkeypatch.delenv("SHELL", raising=False)
        monkeypatch.setattr(terminal.shutil, "which", lambda n: None)
        assert terminal._resolve_terminal_shell(None) == "/bin/sh"


def test_spawn_launches_interactive_shell_with_history(tmp_path):
    """The spawned shell must be interactive (readline/history on) and write to
    a HISTFILE. We prove it by driving a real bash through the PTY: run a
    command, then send an up-arrow (history recall) and confirm the previous
    command comes back — which only works when bash is interactive."""
    import shutil as _sh
    from ppxai.server.routes.terminal import PtyProcess

    bash = _sh.which("bash")
    if not bash:
        pytest.skip("bash not available")

    home = tmp_path / "home"
    home.mkdir()
    proc = PtyProcess(bash, str(home), login_shell=False)
    # Point HOME at the tmp home so HISTFILE lands there.
    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        proc.spawn()
        time.sleep(0.4)
        proc.write(b"echo marker_one\n")
        time.sleep(0.3)
        # Up-arrow = ESC [ A ; interactive readline recalls the last command.
        proc.write(b"\x1b[A")
        time.sleep(0.3)
        out = b""
        for _ in range(5):
            out += proc.read(8192)
            time.sleep(0.1)
        # The recalled command text must appear a SECOND time (echoed by
        # readline on the input line), which only happens interactively.
        assert out.count(b"echo marker_one") >= 2, (
            "shell not interactive — up-arrow did not recall history: " + repr(out[-200:])
        )
    finally:
        proc.kill()
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home
