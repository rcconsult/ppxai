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
