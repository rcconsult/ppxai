"""Shared real-server fixture for the `test_server_smoke_*` files.

The smoke suite spawns a real `python -m ppxai.server.http` subprocess and
hits it over a socket (see test_server_smoke_e2e.py's docstring for why).
It used to be one 63-test file, which with `--dist loadfile` ran on a
single worker and set the suite's wall-clock floor (114s on Windows,
2026-09-27). It is now split across files; each takes this module-scoped
`server` fixture, so each file boots its own server and the files run in
parallel on separate workers.

Import the fixture into a test module with
`from tests.server_smoke_support import server  # noqa: F401`.

One boot, not two: the fixture used to start a throwaway server first,
only to decide skip-versus-fail, then start the real one. The real start
now makes that decision itself: exiting before /health means the host
cannot spawn a server here (skip, the Windows Store Python sandbox case),
and staying alive without answering means a real start failure (fail,
with the server's own output).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from tests.conftest import pin_server_working_dir

REPO_ROOT = Path(__file__).resolve().parents[1]

#: One client per process for every smoke request. `httpx.get()` builds a
#: fresh Client per call, and a Client builds a CA-loaded SSL context even
#: for plain http:// -- ~0.75s of CPU per request on Windows' OpenSSL 3.0,
#: which made each trivial smoke request cost ~1.3s (2026-09-27).
HTTP = httpx.Client()

# One budget for the whole start. A probe must never be stricter than the
# thing it gates: on a Windows dev host the server answers /health in
# ~7.4s, and a 6s probe once skipped 58 working tests.
STARTUP_BUDGET_S = 30.0

# Env vars stripped from the child: VIRTUAL_ENV/PYTHONHOME can point at a
# different interpreter than sys.executable, and conftest loads the
# developer's ~/.ppxai/.env, whose quoted TLS paths can reach the child with
# literal quote characters and crash OpenSSL initialization.
_STRIPPED_ENV = ("VIRTUAL_ENV", "PYTHONHOME", "SSL_CERT_FILE", "SSL_VERIFY",
                 "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")


def free_port() -> int:
    """Return an available TCP port on localhost.

    Scans a stable user-space range (54100-54399) instead of `bind(0)`: on
    Windows `bind(0)` can return a port inside a WinNAT/Hyper-V reserved
    range, where a later `listen()` by another process is forbidden. No
    `listen()` here either -- on Windows even a brief listener can keep the
    child from binding the same port for a few milliseconds.

    Under xdist several smoke files start servers at the same moment, and a
    free-looking port is NOT proof: uvicorn binds with SO_REUSEADDR, which
    on Windows lets a second process bind a port the first is listening on.
    Two servers then share one port, and when either shuts down the other
    file's requests fail (seen 2026-09-27). So each xdist worker scans its
    own slice of the range first; a lost race is still retried by `_start`.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
    index = int(worker[2:]) if worker[2:].isdigit() else 0
    offset = (index * 18) % 300
    for port in [54100 + (offset + i) % 300 for i in range(300)]:
        try:
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(
        "Could not find a usable free port in 54100-54399. Check Windows "
        "reserved port ranges with "
        "`netsh int ipv4 show excludedportrange protocol=tcp`."
    )


def _port_in_use(port: int) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    except OSError:
        pass


def _start(log_dir: Path) -> tuple[str, subprocess.Popen, list]:
    """Start a server and wait for /health. Returns (base_url, proc, files).

    Skips when the child exits before answering and the port was NOT taken
    by someone else (the host cannot spawn servers); retries on a lost
    port race; fails with the server's output on a live-but-silent start.
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    for var in _STRIPPED_ENV:
        env.pop(var, None)

    for attempt in range(3):
        port = free_port()
        out_path = log_dir / f"server.{attempt}.log"
        err_path = log_dir / f"server.{attempt}.err.log"
        # Files, not PIPE: on Windows an unread ~4KB PIPE buffer fills
        # during uvicorn startup and the child blocks before binding.
        out_file = open(out_path, "wb")
        err_file = open(err_path, "wb")
        proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "ppxai.server.http",
             "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(REPO_ROOT), env=env,
            stdout=out_file, stderr=err_file, stdin=subprocess.DEVNULL,
        )

        def output() -> str:
            for f in (out_file, err_file):
                try:
                    f.flush()
                except Exception:
                    pass
            out = out_path.read_text(encoding="utf-8", errors="replace")
            err = err_path.read_text(encoding="utf-8", errors="replace")
            return f"=== stdout ===\n{out}\n=== stderr ===\n{err}"

        deadline = time.time() + STARTUP_BUDGET_S
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            try:
                if HTTP.get(f"http://127.0.0.1:{port}/health", timeout=1.0).status_code == 200:
                    return f"http://127.0.0.1:{port}", proc, [out_file, err_file]
            except httpx.HTTPError:
                pass
            time.sleep(0.25)

        exited = proc.poll() is not None
        _stop(proc)
        out_file.close()
        err_file.close()
        if exited and _port_in_use(port):
            continue  # another smoke file's server took the port; try again
        if exited:
            pytest.skip(
                f"Cannot spawn ppxai-server here: it exited before answering "
                f"/health (rc={proc.returncode}). Common cause: Windows Store "
                f"Python venv (see CLAUDE.md). Runs cleanly on CI Linux/macOS.")
        pytest.fail(
            f"Server on port {port} stayed alive but did not answer /health in "
            f"{STARTUP_BUDGET_S:.0f}s.\n--- BEGIN SERVER OUTPUT ---\n"
            f"{output()}\n--- END SERVER OUTPUT ---", pytrace=False)
    pytest.fail("Server lost the port race three times in a row.", pytrace=False)


@pytest.fixture(scope="module")
def server(tmp_path_factory) -> Iterator[tuple[str, subprocess.Popen]]:
    """A real ppxai-server subprocess on a free port: yields (base_url, proc)."""
    base_url, proc, files = _start(tmp_path_factory.mktemp("server-smoke"))
    # Never inherit the host's working directory -- see
    # pin_server_working_dir's docstring for the measurements.
    pin_server_working_dir(base_url, REPO_ROOT)
    try:
        yield base_url, proc
    finally:
        _stop(proc)
        for f in files:
            f.close()
