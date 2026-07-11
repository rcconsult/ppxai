"""Behavioral tests for the web ApiClient's /v1 bearer scoping (Item 40).

Exercises the actual runtime via Node (same pattern as
test_task_controller_behavior.py): the bearer must ride ONLY on /v1/*
endpoints — the server validates any presented bearer even on
loopback-exempt UI routes (server/auth.py: "If a caller DID present a
bearer, fall through and validate it"), so a stale token attached
everywhere would 401 the whole UI instead of just the agent API.

Skips cleanly where Node isn't available.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
API_CLIENT = (
    Path(__file__).resolve().parents[1]
    / "ppxai" / "web" / "shared" / "api-client.js"
)

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


_HARNESS = r"""
const {{ ApiClient }} = require({api_client});

function assert(cond, msg) {{ if (!cond) throw new Error("FAIL: " + msg); }}

const calls = [];
global.fetch = async (url, opts) => {{
  calls.push([url, (opts && opts.headers) || {{}}]);
  return {{ ok: true, json: async () => ({{}}) }};
}};

(async () => {{
  const c = new ApiClient('http://x', 'sess-1');

  // --- No token: nothing carries Authorization ---
  await c.get('/v1/agent/runs');
  await c.get('/status');
  assert(!('Authorization' in calls[0][1]), "no-token /v1 GET must not carry Authorization");
  assert(!('Authorization' in calls[1][1]), "no-token UI GET must not carry Authorization");

  // --- Token set: bearer on /v1/* only, GET and POST alike ---
  c.setApiToken('tok-abc');
  await c.get('/v1/agent/runs');
  await c.post('/v1/agent/task', {{}});
  await c.get('/status');
  await c.post('/command/pwd', {{}});
  assert(calls[2][1]['Authorization'] === 'Bearer tok-abc', "bearer on /v1 GET");
  assert(calls[3][1]['Authorization'] === 'Bearer tok-abc', "bearer on /v1 POST");
  assert(!('Authorization' in calls[4][1]), "UI GET stays bearer-free (stale-token blast radius)");
  assert(!('Authorization' in calls[5][1]), "UI POST stays bearer-free");

  // --- Session headers survive alongside the bearer ---
  assert(calls[2][1]['X-Session-Id'] === 'sess-1', "session header kept with bearer");

  // --- headersFor is the single seam (used by raw fetches like _tailEvents) ---
  const h = c.headersFor('/v1/agent/runs/run_1/events?live=1');
  assert(h['Authorization'] === 'Bearer tok-abc', "headersFor attaches bearer for /v1 path");
  const h2 = c.headersFor('/files/list');
  assert(!('Authorization' in h2), "headersFor omits bearer off /v1");

  // --- Clearing removes it everywhere ---
  c.setApiToken(null);
  await c.get('/v1/agent/runs');
  assert(!('Authorization' in calls[6][1]), "cleared token no longer attached");

  console.log("ALL_PASS");
}})().catch((e) => {{ console.error(e.message); process.exit(1); }});
"""


def test_api_client_scopes_bearer_to_v1():
    script = _HARNESS.format(api_client=repr(str(API_CLIENT)))
    proc = subprocess.run(
        [NODE, "-e", script], capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert "ALL_PASS" in proc.stdout
