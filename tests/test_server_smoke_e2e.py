"""End-to-end server smoke test (v1.18.1).

Spawns a real `python -m ppxai.server.http` subprocess on a free
port, waits for `/health`, then hits every registered endpoint and
asserts none of them return 5xx. The point is to catch the class
of bug that the v1.17.4 → v1.18.0 PyInstaller hidden-imports
disaster slipped through six releases on:

  * routes that import lazily and crash at first request,
  * routes that depend on optional deps not installed in the
    runtime environment,
  * lifespan/startup ordering bugs that don't show up in
    in-process TestClient tests,
  * the bare fact of "the binary boots and serves traffic."

It is NOT a behavioral test — handlers may legitimately return
4xx for missing args, missing files, etc. The only failure
condition is a 5xx (server crash) or a connection error
(server died mid-flight).

Why this is its own file:
  * Spawning a real subprocess is slow (~5-10s) — keeps the
    fast unit tests fast.
  * Marked with a slow marker so CI can opt in/out.
  * Self-contained: imports nothing from other test modules
    so it can run as a smoke test on a clean checkout.

For unit-level coverage of individual routes, see
`tests/test_server_routes.py` and `tests/test_command_envelope.py`.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Iterator, Tuple

import pytest

pytest.importorskip("httpx")
import httpx


# ---------------------------------------------------------------------------
# Endpoint catalog. Each tuple is (method, path, body|None).
# `{...}` placeholders get substituted with safe defaults at request time.
# Endpoints that REQUIRE specific resources (a file_id, checkpoint_id,
# session name, etc.) are exercised with a probe value — server is
# expected to 4xx but not 5xx.
# ---------------------------------------------------------------------------

GET_ENDPOINTS = [
    # Health & lifecycle
    "/health",
    "/ready",
    "/status",
    "/state",
    # Schema
    "/schema/app-state",
    # Static / static asset roots (catch import-time failures in static module)
    "/",
    "/app.js",
    "/styles.css",
    # Config
    "/config/paths",
    "/config/path",
    "/debug-log",
    # Providers / models / tools
    "/providers",
    "/models",
    "/tools",
    # Sessions
    "/sessions",
    "/sessions/list",
    "/sessions/last",
    # Agent
    "/agent/status",
    "/agent/config",
    # Checkpoint
    "/checkpoint/status",
    "/checkpoint/list",
    "/checkpoint/info/probe-cp-id",  # 4xx expected
    # Context
    "/context/working_dir",
    "/context/auto_inject",
    "/context/info",
    "/context/hints",
    "/context/bootstrap",
    # Files
    "/files/list",
    "/files/tree",
    "/files/serve/probe-file-id",   # 4xx expected
    "/files/preview/probe-file-id", # 4xx expected
    # Preview
    "/preview/serve/status",
    # Usage
    "/usage",
    "/usage/display",
    "/usage/report",
    "/usage/sessions",
]

POST_ENDPOINTS = [
    # Lifecycle
    ("/config/reload", {}),
    # Sessions
    ("/sessions/save", {"name": "smoke-test-probe"}),
    ("/sessions/clear", {}),
    ("/sessions/restore", {}),
    # Context
    ("/context/clear", {}),
    ("/context/reload", {}),
    # Tools
    ("/tools/config", {"key": "verbose", "value": "off"}),
    # Checkpoint (4xx expected — no checkpoints exist)
    ("/checkpoint/clear", {}),
    # Debug
    ("/debug-log", {"enabled": False}),
    ("/client-log", {"level": "info", "message": "smoke test"}),
    # Files
    # NOTE: /files/search rglobs the working dir. We pass a query
    # that should match common test artifacts to short-circuit the
    # scan via max_results=1. A miss-everything query would scan
    # .venv recursively and starve the single-worker server, making
    # downstream tests time out.
    ("/files/search", {"query": "py", "max_results": 1}),
    # Preview
    ("/preview/serve/stop", {}),
    ("/preview/proxy/stop", {}),
    # Usage
    ("/usage/display", {"mode": "compact"}),
    ("/usage/reset", {}),
    # Command — the unified factory dispatch (v1.18.1)
    ("/command/help", {"args": ""}),
    ("/command/status", {"args": ""}),
    ("/command/sessions", {"args": ""}),
    ("/command/tools", {"args": ""}),
    ("/command/usage", {"args": ""}),
    ("/command/pwd", {"args": ""}),
    # Interrupt — should be a no-op when no stream is active
    ("/interrupt", {}),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _free_port() -> int:
    """Return an available TCP port on localhost.

    On Windows, `bind(0)` can hand out a port that falls inside a
    WinNAT/Hyper-V reserved range — a range where a subsequent
    `listen()` call by an unrelated process is forbidden. To avoid
    that class of flake, we scan a stable user-space range
    (54100–54399) and return the first port whose plain bind
    succeeds.

    Note: we do NOT call `listen()` here. On Windows, holding a
    listener (even briefly with SO_REUSEADDR) can prevent a
    subsequent process from binding the same port for a few
    milliseconds — long enough to flake the test. A bare bind +
    immediate close is enough to confirm the port is unreserved.
    """
    # 54100-54399 sits above ppxai-server's default 54320 and well
    # outside the typical WinNAT ranges (50000-54012, 61000-62000).
    for port in range(54100, 54400):
        try:
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(
        "Could not find a usable free port in 54100-54399. "
        "Check Windows reserved port ranges with "
        "`netsh int ipv4 show excludedportrange protocol=tcp`."
    )


def _wait_for_health(port: int, timeout: float = 30.0) -> None:
    """Poll /health until the server responds 200 or timeout expires."""
    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
            if r.status_code == 200:
                return
        except httpx.HTTPError as e:
            last_err = e
        time.sleep(0.25)
    raise RuntimeError(
        f"Server on :{port} did not become healthy in {timeout}s. "
        f"Last error: {last_err}"
    )


def _can_spawn_server(repo_root: Path) -> Tuple[bool, str]:
    """Probe whether `python -m ppxai.server.http` can BOOT here.

    Actually starts the server briefly and checks for an HTTP /health
    response. Returns (ok, reason). The probe is necessary because a
    plain import test isn't enough — Windows Store Python venvs let
    `python -c "import ppxai.server.http"` succeed but kill the
    subprocess silently when uvicorn tries to bind a port (rc=1, no
    output, ~2s after spawn). The smoke test skips gracefully in
    those environments.
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    for var in ("VIRTUAL_ENV", "PYTHONHOME",
                "SSL_CERT_FILE", "SSL_VERIFY", "NODE_EXTRA_CA_CERTS",
                "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        env.pop(var, None)

    try:
        port = _free_port()
    except RuntimeError as exc:
        return False, str(exc)

    proc = subprocess.Popen(
        [sys.executable, "-u",
         "-m", "ppxai.server.http",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 6.0
        while time.time() < deadline:
            if proc.poll() is not None:
                return False, (
                    f"server exited prematurely (rc={proc.returncode}). "
                    f"Likely Windows Store Python sandbox blocking "
                    f"subprocess port binding."
                )
            try:
                r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
                if r.status_code == 200:
                    return True, ""
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        return False, "server did not respond to /health within 6s"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


@pytest.fixture(scope="module")
def server(tmp_path_factory) -> Iterator[Tuple[str, subprocess.Popen]]:
    """Spawn a real ppxai-server subprocess on a free port.

    Yields (base_url, process). Tears down by sending SIGTERM and
    waiting up to 10s for graceful shutdown.

    Implementation note: server stdout is redirected to a tempfile
    rather than `subprocess.PIPE`. On Windows, an unread PIPE buffer
    of ~4KB fills during uvicorn startup and the child blocks on
    write — eventually killing the process before it binds the
    port. File redirect sidesteps the buffer entirely.
    """
    repo_root = Path(__file__).resolve().parents[1]

    can_spawn, reason = _can_spawn_server(repo_root)
    if not can_spawn:
        pytest.skip(
            f"Cannot spawn ppxai-server subprocess in this environment: "
            f"{reason}. Common cause: Windows Store Python venv "
            f"(see CLAUDE.md). The smoke test runs cleanly on CI "
            f"Linux/macOS images."
        )

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    log_dir = tmp_path_factory.mktemp("server-smoke")
    log_path = log_dir / "server.log"

    # Inherit parent env, then strip vars that are known to break
    # uvicorn startup in test contexts:
    #   * VIRTUAL_ENV / PYTHONHOME — can point at a different
    #     interpreter than sys.executable.
    #   * SSL_CERT_FILE etc. — tests/conftest.py loads ~/.ppxai/.env
    #     into os.environ; quoted paths in the user's .env can pass
    #     through dotenv with literal quote characters and crash
    #     openssl initialization in the subprocess.
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    for var in ("VIRTUAL_ENV", "PYTHONHOME",
                "SSL_CERT_FILE", "SSL_VERIFY", "NODE_EXTRA_CA_CERTS",
                "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        env.pop(var, None)

    err_path = log_dir / "server.err.log"
    log_file = open(log_path, "wb")
    err_file = open(err_path, "wb")

    proc = subprocess.Popen(
        [
            sys.executable, "-u",
            "-m", "ppxai.server.http",
            "--host", "127.0.0.1", "--port", str(port),
        ],
        cwd=str(repo_root),
        env=env,
        stdout=log_file,
        stderr=err_file,
        stdin=subprocess.DEVNULL,
    )

    def _read_log() -> str:
        try:
            log_file.flush()
            err_file.flush()
        except Exception:
            pass
        out = log_path.read_text(encoding="utf-8", errors="replace")
        err = err_path.read_text(encoding="utf-8", errors="replace")
        return f"=== stdout ===\n{out}\n=== stderr ===\n{err}"

    try:
        _wait_for_health(port)
    except Exception as wait_err:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log_file.close()
        err_file.close()
        log = _read_log() or "(no output captured)"
        pytest.fail(
            f"Server failed to start on port {port}.\n"
            f"wait_for_health error: {wait_err!r}\n"
            f"proc returncode: {proc.returncode}\n"
            f"--- BEGIN SERVER OUTPUT ---\n{log}\n--- END SERVER OUTPUT ---",
            pytrace=False,
        )

    try:
        yield base_url, proc
    finally:
        # On Windows with DETACHED_PROCESS, terminate() still works
        # but the process group has no console — kill is reliable.
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        except OSError:
            pass
        log_file.close()
        err_file.close()


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

@pytest.mark.slow
class TestServerSmoke:
    """The server boots, every catalogued endpoint returns non-5xx."""

    def test_server_health(self, server):
        base_url, _ = server
        r = httpx.get(f"{base_url}/health", timeout=5.0)
        assert r.status_code == 200
        assert r.json().get("status") == "healthy"

    # Endpoints that recursively stat the server's working directory
    # (`get_working_dir()`, which resolves from config/session — NOT the
    # spawn cwd). `/files/tree` walks to depth 3 and `/files/list` enumerates
    # the tree; both are *bounded* (they complete, skipping ignore_dirs), but
    # under the FS-stat load of the full suite a cold walk can exceed the
    # 10s crash-detection timeout and flake the run (observed ~50% under
    # full-suite load; <1s in isolation). These are crash tests, not perf
    # tests, so give the filesystem walkers generous headroom while keeping
    # the tight 10s budget on every other endpoint as a genuine hang guard.
    _FS_WALK_TIMEOUT = 30.0
    _FS_WALK_ENDPOINTS = {"/files/tree", "/files/list"}

    @pytest.mark.parametrize("path", GET_ENDPOINTS)
    def test_get_endpoint_does_not_crash(self, server, path):
        base_url, _ = server
        timeout = self._FS_WALK_TIMEOUT if path in self._FS_WALK_ENDPOINTS else 10.0
        r = httpx.get(f"{base_url}{path}", timeout=timeout)
        assert r.status_code < 500, (
            f"GET {path} returned {r.status_code}: {r.text[:500]}"
        )

    @pytest.mark.parametrize("path,body", POST_ENDPOINTS)
    def test_post_endpoint_does_not_crash(self, server, path, body):
        base_url, _ = server
        r = httpx.post(f"{base_url}{path}", json=body, timeout=10.0)
        assert r.status_code < 500, (
            f"POST {path} body={json.dumps(body)} returned "
            f"{r.status_code}: {r.text[:500]}"
        )

    def test_unknown_command_returns_404_not_500(self, server):
        """Regression guard: unknown commands hit the factory's 404
        path, not a generic exception handler."""
        base_url, _ = server
        r = httpx.post(
            f"{base_url}/command/__no_such_command__",
            json={"args": ""},
            timeout=5.0,
        )
        assert r.status_code == 404

    def test_command_envelope_shape_via_real_server(self, server):
        """The v1.18.1 envelope must round-trip through a real
        uvicorn process, not just FastAPI's TestClient.

        v1.18.1 Phase B added `events[]` to the envelope alongside
        the existing keys.
        """
        base_url, _ = server
        r = httpx.post(
            f"{base_url}/command/status",
            json={"args": ""},
            timeout=10.0,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body.keys()) == {
            "ok", "result", "side_effects", "events", "version"
        }
        assert body["version"] == 1
        assert isinstance(body["side_effects"], list)
        assert isinstance(body["events"], list)

    def test_state_mutating_command_drains_events_via_real_server(
        self, server, tmp_path
    ):
        """v1.18.1 Phase B end-to-end: POST /command/cd through a
        real uvicorn process must drain state_sync/working_dir_changed
        events into envelope.events. Without this, the VSCode/web
        AppState mirror stays stale until the next /chat opens an SSE
        generator.
        """
        base_url, _ = server
        r = httpx.post(
            f"{base_url}/command/cd",
            json={"args": str(tmp_path)},
            headers={"X-Session-Id": "smoke-cd-piggyback"},
            timeout=10.0,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body["events"], list)
        types = [e["type"] for e in body["events"]]
        # /cd hits engine.set_working_dir which fires both
        # state_sync(working_dir=...) and working_dir_changed.
        assert any(
            t in types for t in ("state_sync", "working_dir_changed")
        ), (
            f"/cd against real server didn't drain state-sync events; "
            f"got: {types}"
        )

    def test_files_read_409_on_stale_cwd_anchor_via_real_server(
        self, server, tmp_path
    ):
        """v1.18.1 Phase D drift-simulation end-to-end: the server
        must surface a 409 with structured {expected, actual, events}
        when /files/read is called with a cwd_anchor that doesn't
        match the engine's current cwd.

        Drives the full path through real HTTP so the recovery
        helper on web/VSCode (handleCwdAnchorMismatch) has a wire
        contract it can rely on.
        """
        base_url, _ = server
        headers = {"X-Session-Id": "smoke-cwd-anchor-409"}
        # Step 1: server's engine cwd starts somewhere; pin it to the
        # actual tmp_path so we have a known anchor for the drift.
        r = httpx.post(
            f"{base_url}/context/working_dir",
            json={"path": str(tmp_path)},
            headers=headers,
            timeout=10.0,
        )
        assert r.status_code == 200, r.text
        # Step 2: simulate drift — client THINKS cwd is some stale
        # subdir that doesn't match the engine's actual cwd.
        stale_anchor = str(tmp_path / "definitely_not_the_engine_cwd")
        r = httpx.post(
            f"{base_url}/files/read",
            json={"path": "anything.txt", "cwd_anchor": stale_anchor},
            headers=headers,
            timeout=10.0,
        )
        assert r.status_code == 409, (
            f"Expected 409 from stale cwd_anchor; got {r.status_code}: "
            f"{r.text[:300]}"
        )
        body = r.json()
        # FastAPI wraps HTTPException body in `detail`
        detail = body.get("detail", body) if isinstance(body, dict) else body
        if isinstance(detail, dict):
            for field in ("expected", "actual", "events"):
                assert field in detail, (
                    f"409 body missing {field!r}; got keys: "
                    f"{sorted(detail.keys())}"
                )
            assert isinstance(detail["events"], list)
