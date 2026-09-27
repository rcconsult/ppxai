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

Split across four files (2026-09-27) so they run on separate xdist
workers, each with its own server (tests/server_smoke_support.py):
this file (health + wire-contract checks), test_server_smoke_get_a.py /
test_server_smoke_get_b.py (the GET catalog) and test_server_smoke_post.py
(the POST catalog). As one file it set the suite's wall-clock floor.

Why these are their own files:
  * Spawning a real subprocess is slow (~5-10s) — keeps the
    fast unit tests fast.
  * Marked with a slow marker so CI can opt in/out.
  * Self-contained: imports nothing from other test modules
    so it can run as a smoke test on a clean checkout.

For unit-level coverage of individual routes, see
`tests/test_server_routes.py` and `tests/test_command_envelope.py`.
"""

from __future__ import annotations

import pytest

pytest.importorskip("httpx")

from tests import server_smoke_support
from tests.server_smoke_support import HTTP

# The module-scoped real-server fixture, bound here so pytest finds it.
server = server_smoke_support.server


@pytest.mark.slow
class TestServerSmoke:
    """The server boots and its wire contracts hold through real HTTP."""

    def test_server_health(self, server):
        base_url, _ = server
        r = HTTP.get(f"{base_url}/health", timeout=5.0)
        assert r.status_code == 200
        assert r.json().get("status") == "healthy"
    def test_unknown_command_returns_404_not_500(self, server):
        """Regression guard: unknown commands hit the factory's 404
        path, not a generic exception handler."""
        base_url, _ = server
        r = HTTP.post(
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
        r = HTTP.post(
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
        r = HTTP.post(
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
        r = HTTP.post(
            f"{base_url}/context/working_dir",
            json={"path": str(tmp_path)},
            headers=headers,
            timeout=10.0,
        )
        assert r.status_code == 200, r.text
        # Step 2: simulate drift — client THINKS cwd is some stale
        # subdir that doesn't match the engine's actual cwd.
        stale_anchor = str(tmp_path / "definitely_not_the_engine_cwd")
        r = HTTP.post(
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
