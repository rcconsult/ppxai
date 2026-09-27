"""A hung provider call must not keep `ppxai-server` alive after a stop.

Found 2026-09-28 on WSL: a provider that accepted a request and never
answered held the server past SIGTERM until SIGKILL. Three things combined:
uvicorn's `timeout_graceful_shutdown` defaulted to None (wait for ever), our
signal handler replaced uvicorn's without its "second signal forces" rule,
and provider calls run in `asyncio.to_thread`, whose executor `asyncio.run`
(and then the interpreter) joins without a limit.

Every hang runs in a CHILD process: a thread that never returns inside the
pytest process would stop pytest itself from exiting.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time

import httpx
import openai
import pytest

from ppxai.config import paths as config_paths
from ppxai.engine.providers import base as provider_base
from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

POSIX = sys.platform != "win32"


# ---------------------------------------------------------------------------
# Config readers
# ---------------------------------------------------------------------------

class TestShutdownGraceConfig:
    @pytest.mark.parametrize("raw, expected", [
        (None, config_paths.DEFAULT_SHUTDOWN_GRACE_S),
        (3, 3.0),
        ("2.5", 2.5),
        (0, 0.0),
        (-1, config_paths.DEFAULT_SHUTDOWN_GRACE_S),
        ("soon", config_paths.DEFAULT_SHUTDOWN_GRACE_S),
    ])
    def test_values(self, monkeypatch, raw, expected):
        server = {} if raw is None else {"shutdown_grace_s": raw}
        monkeypatch.setattr(config_paths, "get_server_config", lambda: server)
        assert config_paths.get_shutdown_grace_s() == expected


class TestProviderClientTimeout:
    @pytest.mark.parametrize("raw, expected", [
        (None, openai.NOT_GIVEN),
        (30, 30.0),
        ("45", 45.0),
        (0, openai.NOT_GIVEN),
        (-5, openai.NOT_GIVEN),
        ("never", openai.NOT_GIVEN),
    ])
    def test_values(self, monkeypatch, raw, expected):
        cfg = {} if raw is None else {"timeout_s": raw}
        monkeypatch.setattr(provider_base, "get_provider_config", lambda _pid: cfg)
        assert provider_base.client_timeout("p") == expected

    def test_no_provider_id_keeps_the_sdk_default(self):
        assert provider_base.client_timeout(None) is openai.NOT_GIVEN

    def test_the_client_is_built_with_it(self, monkeypatch):
        """End to end through BaseProvider.__init__: the OpenAI client carries
        the configured timeout, and the SDK default when unset."""
        monkeypatch.setattr(provider_base, "get_provider_config",
                            lambda pid: {"timeout_s": 12} if pid == "slow" else {})
        slow = OpenAICompatibleProvider(api_key="k", base_url="http://127.0.0.1:9/v1",
                                        provider_id="slow")
        plain = OpenAICompatibleProvider(api_key="k", base_url="http://127.0.0.1:9/v1",
                                         provider_id="plain")
        assert slow.client.timeout == 12
        assert plain.client.timeout == openai.OpenAI(api_key="k").timeout  # SDK default


# ---------------------------------------------------------------------------
# Worker threads are let go (every platform, no signals)
# ---------------------------------------------------------------------------

_RELEASE_CHILD = textwrap.dedent("""
    import asyncio, sys, threading
    from ppxai.server import http as h

    hang = sys.argv[1] == "hang"
    block = threading.Event()

    async def main():
        workers = h._install_worker_executor()  # as _run_server_with_graceful_shutdown does
        if hang:
            asyncio.ensure_future(asyncio.to_thread(block.wait))  # never returns
            await asyncio.sleep(0.1)
        else:
            await asyncio.to_thread(lambda: None)  # the executor has run work
        await h._release_worker_threads(workers, 0.5)
        print("HUNG", h._workers_hung, flush=True)

    asyncio.run(main())
    print("CLEANUP-RAN", flush=True)  # an entry point's own cleanup
    h._exit_if_workers_hung()
    print("NORMAL-EXIT", flush=True)
""")


def _run_child(*args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", _RELEASE_CHILD, *args],
                          capture_output=True, text=True, timeout=timeout)


class TestWorkerThreadsAreReleased:
    def test_a_hung_call_no_longer_blocks_exit(self):
        """Before the fix this child never exited: asyncio.run joined the
        executor without a limit (the subprocess timeout would fire). The
        first fix still hung on Python 3.10/3.11, whose
        `shutdown_default_executor` ends in an unbounded `thread.join()`;
        run this on 3.11 too (macOS did)."""
        started = time.monotonic()
        proc = _run_child("hang")
        assert proc.returncode == 0, proc.stderr
        assert "HUNG True" in proc.stdout
        assert "CLEANUP-RAN" in proc.stdout, "cleanup must run BEFORE the forced exit"
        assert "NORMAL-EXIT" not in proc.stdout
        assert time.monotonic() - started < 30

    def test_no_hung_call_exits_normally(self):
        """Control: with nothing stuck, nothing is forced."""
        proc = _run_child("idle")
        assert proc.returncode == 0, proc.stderr
        assert "HUNG False" in proc.stdout
        assert "NORMAL-EXIT" in proc.stdout


# ---------------------------------------------------------------------------
# The real server loop under a real signal (POSIX: Windows has no SIGTERM to
# deliver to a child; its Ctrl+C path shares the same handler and release)
# ---------------------------------------------------------------------------

_SERVER_CHILD = textwrap.dedent("""
    import asyncio, signal, sys, threading, time
    from fastapi import FastAPI
    from ppxai.server import http as h

    from contextlib import asynccontextmanager

    port, grace = int(sys.argv[1]), float(sys.argv[2])
    h.get_shutdown_grace_s = lambda: grace

    @asynccontextmanager
    async def lifespan(app):
        yield
        print("APP-SHUTDOWN-RAN", flush=True)  # ppxai saves sessions here

    app = FastAPI(lifespan=lifespan)
    block = threading.Event()

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    @app.get("/hang")
    async def hang():  # a provider call that never answers
        await asyncio.to_thread(block.wait)
        return {}

    @app.post("/ctrl-c")
    async def ctrl_c(times: int = 1, gap: float = 1.0):
        # Ctrl+C as the process sees it (SIGINT to itself) -- works on
        # Windows too, where a parent cannot signal a child this way.
        def fire():
            for _ in range(times):
                signal.raise_signal(signal.SIGINT)
                time.sleep(gap)
        threading.Thread(target=fire, daemon=True).start()
        return {}

    asyncio.run(h._run_server_with_graceful_shutdown(
        app, host="127.0.0.1", port=port, log_level="warning"))
    h._exit_if_workers_hung()
""")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_hung_server(grace_s: float):
    """Start the child server with one request hung in a worker thread.
    Returns (proc, port)."""
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-c", _SERVER_CHILD, str(port), str(grace_s)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/ok", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail(f"server never came up: {proc.communicate()[0]}")

    def _hang():
        try:
            httpx.get(f"http://127.0.0.1:{port}/hang", timeout=120)
        except httpx.HTTPError:
            pass

    threading.Thread(target=_hang, daemon=True).start()
    time.sleep(0.5)  # the request is in flight, its worker thread blocked
    return proc, port


def _exit_within(proc, seconds: float) -> tuple[bool, str]:
    try:
        out, _ = proc.communicate(timeout=seconds)
        return True, out
    except subprocess.TimeoutExpired:
        proc.kill()
        return False, proc.communicate()[0]


@pytest.mark.slow
class TestCtrlCStopsItDespiteAHungCall:
    """Every platform: the server loop, its handler and the release, driven
    by SIGINT the way Ctrl+C delivers it."""

    def test_one_ctrl_c_stops_it_within_the_grace(self):
        proc, port = _start_hung_server(grace_s=1.0)
        started = time.monotonic()
        httpx.post(f"http://127.0.0.1:{port}/ctrl-c", timeout=10)
        exited, out = _exit_within(proc, 30)
        assert exited, f"still running 30s after Ctrl+C:\n{out}"
        assert time.monotonic() - started < 15
        assert proc.returncode == 0, out
        assert "still running" in out
        assert "APP-SHUTDOWN-RAN" in out
        # The cancelled request is one warning line, not a crash traceback.
        assert "Abandoned an in-flight request" in out
        assert "Traceback" not in out, out

    def test_a_second_ctrl_c_forces_it(self):
        proc, port = _start_hung_server(grace_s=120.0)
        started = time.monotonic()
        httpx.post(f"http://127.0.0.1:{port}/ctrl-c", params={"times": 2}, timeout=10)
        exited, out = _exit_within(proc, 30)
        assert exited, f"a second Ctrl+C did not force the exit:\n{out}"
        assert time.monotonic() - started < 15  # not the 120 s grace
        assert "forcing shutdown" in out
        # uvicorn skips the app's shutdown on a force; ppxai runs it anyway
        # (sessions saved, the "stopped" line printed), and nothing is left
        # to be cancelled with a traceback.
        assert "APP-SHUTDOWN-RAN" in out
        assert "Traceback" not in out, out

    def test_a_doubled_delivery_is_one_stop_not_a_force(self):
        """A terminal Ctrl+C reaches the process group AND is forwarded by the
        PyInstaller bootloader, so the child can see it twice within
        milliseconds. That must stay a graceful stop, not a forced one."""
        proc, port = _start_hung_server(grace_s=2.0)
        httpx.post(f"http://127.0.0.1:{port}/ctrl-c", params={"times": 2, "gap": 0.05},
                   timeout=10)
        exited, out = _exit_within(proc, 30)
        assert exited, out
        assert "forcing shutdown" not in out
        assert "still running 2s" in out  # the graceful path, full grace


@pytest.mark.skipif(not POSIX, reason="delivers SIGTERM to a child process")
@pytest.mark.slow
class TestSigtermStopsItDespiteAHungCall:
    def test_one_sigterm_stops_it_within_the_grace(self):
        proc, _ = _start_hung_server(grace_s=1.0)
        started = time.monotonic()
        os.kill(proc.pid, signal.SIGTERM)
        exited, out = _exit_within(proc, 30)
        assert exited, f"still running 30s after SIGTERM:\n{out}"
        assert time.monotonic() - started < 15  # ~2 x grace, plus startup slack
        assert proc.returncode == 0, out
        assert "still running" in out  # the release path logged it

    def test_a_second_signal_forces_it(self):
        """A long grace, then a second SIGTERM: out at once, not after it."""
        proc, _ = _start_hung_server(grace_s=120.0)
        os.kill(proc.pid, signal.SIGTERM)
        time.sleep(1.0)
        started = time.monotonic()
        os.kill(proc.pid, signal.SIGTERM)
        exited, out = _exit_within(proc, 30)
        assert exited, f"a second SIGTERM did not force the exit:\n{out}"
        assert time.monotonic() - started < 15
        assert "forcing shutdown" in out
