"""`ppxai-server --detach` from a PyInstaller one-file binary (ADR 0013 S3).

Found live 2026-09-28: a frozen launcher that simply forked left the daemon
running out of the bootloader's extraction dir (`sys._MEIPASS`), which the
bootloader deletes when the launcher's Python process exits. Every chat on a
hub-launched WSL server then failed with `No such file or directory:
'/tmp/_MEI…/base_library.zip'`. The frozen path now re-spawns the executable
as an independent PyInstaller instance instead.

What a source checkout can pin is the contract of that path: the re-spawn
asks for an independent instance, runs in its own session and hands the
report pipe over; the launcher stops at the first complete JSON document
(the re-spawned bootloader may keep the pipe's write end open, so EOF may
never come) and fails when the daemon dies first. The end-to-end proof needs
a real one-file build; see `docs/plan-ssh-remote-backend.md`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import pytest

from ppxai.server import http as server_http

POSIX = os.name == "posix"
posix_only = pytest.mark.skipif(not POSIX, reason="select() on a pipe and --detach are POSIX-only")


class _ExitedError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@pytest.fixture
def no_exit(monkeypatch):
    def fake_exit(code):
        raise _ExitedError(code)
    monkeypatch.setattr(server_http.os, "_exit", fake_exit)


@posix_only
class TestTheLauncherWait:
    def test_a_complete_entry_is_printed_without_waiting_for_eof(self, no_exit, capsys):
        read_fd, write_fd = os.pipe()
        entry = {"contract": 1, "id": "abc", "pid": 42, "socket": "/tmp/x.sock"}
        # Written in two pieces, and the write end stays OPEN (as the
        # re-spawned bootloader's inherited copy would).
        text = json.dumps(entry, indent=2)
        os.write(write_fd, text[:10].encode())

        def rest():
            time.sleep(0.3)
            os.write(write_fd, text[10:].encode())
        threading.Thread(target=rest, daemon=True).start()
        start = time.monotonic()
        try:
            with pytest.raises(_ExitedError) as done:
                server_http._await_announcement(read_fd, lambda: None)
        finally:
            os.close(write_fd)
        assert done.value.code == 0
        assert time.monotonic() - start < 10
        assert json.loads(capsys.readouterr().out) == entry

    def test_an_error_entry_exits_1(self, no_exit, capsys):
        read_fd, write_fd = os.pipe()
        os.write(write_fd, json.dumps({"error": "bind failed"}).encode())
        try:
            with pytest.raises(_ExitedError) as done:
                server_http._await_announcement(read_fd, lambda: None)
        finally:
            os.close(write_fd)
        assert done.value.code == 1
        assert "bind failed" in capsys.readouterr().out

    def test_a_daemon_that_dies_before_announcing_exits_1(self, no_exit, capsys):
        read_fd, write_fd = os.pipe()  # write end held open: no EOF will come
        try:
            with pytest.raises(_ExitedError) as done:
                server_http._await_announcement(read_fd, lambda: 3)  # already exited
        finally:
            os.close(write_fd)
        assert done.value.code == 1
        assert "exited before announcing" in capsys.readouterr().err

    def test_eof_without_an_entry_exits_1(self, no_exit, capsys):
        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        with pytest.raises(_ExitedError) as done:
            server_http._await_announcement(read_fd, lambda: None)
        assert done.value.code == 1


class TestTheFrozenRespawn:
    def test_a_frozen_launcher_respawns_an_independent_instance(self, monkeypatch):
        seen = {}

        class FakePopen:
            def __init__(self, argv, **kwargs):
                seen["argv"], seen["kwargs"] = argv, kwargs

            def poll(self):
                return None

        def stop(read_fd, exited):
            seen["read_fd"] = read_fd
            raise _ExitedError(0)

        monkeypatch.setattr(server_http.sys, "frozen", True, raising=False)
        monkeypatch.setattr(server_http.sys, "executable", "/opt/ppxai/ppxai-server")
        monkeypatch.setattr(server_http.sys, "argv",
                            ["ppxai-server", "--uds", "--announce", "--detach", "--label", "a b"])
        monkeypatch.setattr(server_http.subprocess, "Popen", FakePopen)
        monkeypatch.setattr(server_http, "_await_announcement", stop)
        monkeypatch.setattr(server_http.os, "fork",
                            lambda: pytest.fail("a frozen launcher must not fork"), raising=False)
        monkeypatch.delenv(server_http._DETACH_REPORT_FD_ENV, raising=False)
        with pytest.raises(_ExitedError):
            server_http._detach()
        os.close(seen["read_fd"])

        kwargs = seen["kwargs"]
        assert seen["argv"] == ["/opt/ppxai/ppxai-server", "--uds", "--announce", "--detach",
                                "--label", "a b"]
        # PyInstaller >= 6.9 treats a sys.executable child as the SAME
        # instance (reusing, then losing, the parent's _MEIPASS) unless this
        # is set.
        assert kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
        fd = int(kwargs["env"][server_http._DETACH_REPORT_FD_ENV])
        assert kwargs["pass_fds"] == (fd,)
        assert kwargs["start_new_session"] is True
        assert kwargs["stdin"] == subprocess.DEVNULL

    def test_the_respawned_daemon_takes_the_inherited_pipe(self, monkeypatch):
        redirected = []
        monkeypatch.setenv(server_http._DETACH_REPORT_FD_ENV, "17")
        monkeypatch.setattr(server_http, "_daemon_stdio", lambda: redirected.append(True))
        monkeypatch.setattr(server_http.os, "fork",
                            lambda: pytest.fail("the daemon must not fork again"), raising=False)
        assert server_http._detach() == 17
        assert redirected == [True]
        # Consumed, so a server this daemon starts later cannot mistake
        # itself for a re-spawned daemon.
        assert server_http._DETACH_REPORT_FD_ENV not in os.environ


def test_the_frozen_path_is_the_only_one_that_respawns():
    # The source path keeps the double fork (and its existing end-to-end
    # test in test_server_registry.py); only a frozen binary re-spawns.
    src = open(server_http.__file__, encoding="utf-8").read()
    body = src[src.index("def _detach"):src.index("def _await_announcement")]
    assert 'getattr(sys, "frozen", False)' in body
    assert "PYINSTALLER_RESET_ENVIRONMENT" in body
    assert sys.executable  # sanity: the interpreter itself is not frozen here
