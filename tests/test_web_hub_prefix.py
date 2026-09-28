"""The web UI finds its API under the path prefix it was served at.

`ppxai/web/app.js` builds every API and websocket URL from `serverUrl`, which
is the page origin plus a path prefix. Two proxies serve the UI under one:

- `/s/<slug>` -- the k8s coder ingress (per-user pod);
- `/h/<host>/<id>` -- ADR 0013's local hub, proxying a remote ppxai-server.

The hub case was missing when phase 4 shipped: win32-ppxai's live run
(2026-09-28) loaded `/h/wsl/<id>/` and every API call went to the LOCAL hub
server, so the page showed the Windows session, not the WSL one. These tests
run the prefix functions from app.js's own source under node, and pin the
Leave button's hub branch (detach, never shut anything down, land on the
launcher) next to the
coder branch that `tests/test_session_end_workflows.py` already pins.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from tests.test_session_end_workflows import APP_JS_PATH, _extract_braced_body, _read

NODE = shutil.which("node")


def _prefix_functions_source() -> str:
    src = _read(APP_JS_PATH)
    start = src.index("const CODER_PREFIX_RE")
    end = src.index("class PpxaiApp")
    return src[start:end]


def _run(pathnames: list[str]) -> list:
    script = _prefix_functions_source() + f"""
const out = {json.dumps(pathnames)}.map(p => ({{
    prefix: servedPathPrefix(p), hub: hubLocation(p) }}));
process.stdout.write(JSON.stringify(out));
"""
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True,
                          encoding="utf-8", timeout=30)  # node writes UTF-8; Windows would decode cp1252
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


CASES = [
    # (pathname, expected prefix, expected hub or None)
    ("/", "", None),
    ("/index.html", "", None),
    ("/s/alice/", "/s/alice", None),
    ("/s/alice", "/s/alice", None),
    ("/s/alice/h/gpu01/abc/", "/s/alice", None),          # coder first: /s/ owns the path
    ("/h/gpu01/9f2c0000aaaa1111/", "/h/gpu01/9f2c0000aaaa1111",
     {"host": "gpu01", "serverId": "9f2c0000aaaa1111", "prefix": "/h/gpu01/9f2c0000aaaa1111"}),
    ("/h/gpu01/9f2c0000aaaa1111", "/h/gpu01/9f2c0000aaaa1111",
     {"host": "gpu01", "serverId": "9f2c0000aaaa1111", "prefix": "/h/gpu01/9f2c0000aaaa1111"}),
    ("/h/lab-mac/abc_DEF-1/index.html", "/h/lab-mac/abc_DEF-1",
     {"host": "lab-mac", "serverId": "abc_DEF-1", "prefix": "/h/lab-mac/abc_DEF-1"}),
    ("/h/gpu01/", "", None),                    # no server id: not a proxied UI
    ("/h/GPU01/abc/", "", None),                # host ids are lower-case
    ("/h/gpu01/abc.def/", "", None),            # not a server id
    ("/hub/hosts", "", None),
    ("/help/x/y/", "", None),
]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
class TestPrefixFromAppJsSource:
    def test_every_case(self):
        results = _run([c[0] for c in CASES])
        for (path, prefix, hub), got in zip(CASES, results):
            assert got["prefix"] == prefix, path
            assert got["hub"] == hub, path


class TestAppJsWiring:
    def test_the_constructor_uses_the_shared_prefix(self):
        src = _read(APP_JS_PATH)
        assert "const pathPrefix = servedPathPrefix(window.location.pathname);" in src
        assert "this.serverUrl = usePageOrigin ? (pageOrigin + pathPrefix)" in src

    def test_no_other_site_derives_a_prefix_from_the_location(self):
        # One place decides the prefix; a second hand-rolled regex is how the
        # hub case was missed. handleQuit's coder branch reuses the constant.
        src = _read(APP_JS_PATH)
        inline = re.findall(r"pathname\.match\(/", src)
        assert inline == [], "use servedPathPrefix()/hubLocation() or CODER_PREFIX_RE"

    def test_the_hub_leave_branch_detaches_and_never_shuts_down(self):
        body = _extract_braced_body(_read(APP_JS_PATH), r"async handleQuit\(\)\s*")
        hub_at = body.index("if (hub)")
        coder_at = body.index("if (pathPrefix)")
        shutdown_at = body.index("this.apiClient.shutdown()")
        assert hub_at < coder_at < shutdown_at, "hub branch, then coder branch, then local shutdown"
        hub_block = body[hub_at:coder_at]
        assert "/detach" in hub_block
        assert "shutdown" not in hub_block, "leaving a remote session must not stop anything"
        # Back to the local page with the SSH Launcher open (owner, 2026-09-28).
        assert re.search(r"window\.location\.href = '/#ssh';[^\n]*\n\s*return;", hub_block)
