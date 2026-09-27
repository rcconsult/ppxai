"""Real-server smoke, GET catalog part B: every endpoint answers non-5xx.

Endpoints that need a real resource (a checkpoint or file id) are probed
with a fake id and expected to 4xx, never 5xx. Part A is
test_server_smoke_get_a.py (see tests/server_smoke_support.py for the split).
"""

from __future__ import annotations

import pytest

pytest.importorskip("httpx")

from tests import server_smoke_support
from tests.server_smoke_support import HTTP

# The module-scoped real-server fixture, bound here so pytest finds it.
server = server_smoke_support.server

GET_ENDPOINTS = [
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
