"""Real-server smoke, GET catalog part A: every endpoint answers non-5xx.

A 5xx or a dropped connection is the only failure; 4xx for missing args
is expected. Part B is test_server_smoke_get_b.py; the split exists so the
parts run on separate xdist workers (see tests/server_smoke_support.py).
"""

from __future__ import annotations

import pytest

pytest.importorskip("httpx")

from tests import server_smoke_support
from tests.server_smoke_support import HTTP

# The module-scoped real-server fixture, bound here so pytest finds it.
server = server_smoke_support.server

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
]
# Filesystem-walking endpoints get headroom: `/files/tree` walks to depth 3,
# `/files/list` enumerates the tree and `/sessions` opens every candidate
# session file (engine/session.py::list_sessions). All are bounded, but a
# cold walk under full-suite FS load can pass the 10s crash-detection
# timeout (observed ~50% under load, <1s in isolation). These are crash
# tests, not perf tests; every other endpoint keeps the tight 10s budget as
# a genuine hang guard.
_FS_WALK_TIMEOUT = 30.0
_FS_WALK_ENDPOINTS = {"/files/tree", "/files/list", "/sessions"}


@pytest.mark.slow
@pytest.mark.parametrize("path", GET_ENDPOINTS)
def test_get_endpoint_does_not_crash(server, path):
    base_url, _ = server
    timeout = _FS_WALK_TIMEOUT if path in _FS_WALK_ENDPOINTS else 10.0
    r = HTTP.get(f"{base_url}{path}", timeout=timeout)
    assert r.status_code < 500, f"GET {path} returned {r.status_code}: {r.text[:500]}"
