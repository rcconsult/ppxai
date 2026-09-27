"""Real-server smoke, POST catalog: every endpoint answers non-5xx.

Split from test_server_smoke_e2e.py so it runs on its own xdist worker with
its own server (see tests/server_smoke_support.py).
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("httpx")

from tests import server_smoke_support
from tests.server_smoke_support import HTTP

# The module-scoped real-server fixture, bound here so pytest finds it.
server = server_smoke_support.server

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


@pytest.mark.slow
@pytest.mark.parametrize("path,body", POST_ENDPOINTS)
def test_post_endpoint_does_not_crash(server, path, body):
    base_url, _ = server
    r = HTTP.post(f"{base_url}{path}", json=body, timeout=10.0)
    assert r.status_code < 500, (
        f"POST {path} body={json.dumps(body)} returned {r.status_code}: {r.text[:500]}"
    )
