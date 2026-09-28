"""ADR 0013 phase 5: the web UI's SSH Launcher (right split pane).

Owner design (2026-09-28): a header "SSH" button, shown only on the local
page of a hub, opens `SshLauncherView` in the right split pane; Open puts the
remote's UI in a new, per-server named browser tab; Leave on a remote page
detaches and lands on `/#ssh`, which reopens the launcher.

The renderer and the view run from their own source under node with a fake
`fetch`, so what is pinned is behaviour: the markup escapes what the remote
announced, no token is ever rendered, session/run counts are read only through
HEALTHY attachments (reading them through the proxy otherwise attaches, i.e.
opens an SSH forward to, every server just because the pane is open), and Stop
asks first.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ppxai.engine.agent_runs import AgentRunRegistry
from tests.test_session_end_workflows import APP_JS_PATH, _extract_braced_body, _read

NODE = shutil.which("node")
WEB = Path(__file__).resolve().parents[1] / "ppxai" / "web"
VIEW = WEB / "components" / "views" / "ssh-launcher-view.js"
INDEX = WEB / "index.html"

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

_STUBS = """
global.BaseView = class {};
global.window = { location: { origin: 'http://127.0.0.1:54320' }, opened: [],
                  open(url, name) { this.opened.push([url, name]); } };
global.window.fetch = undefined;
global.confirmAnswer = false;
global.confirmed = [];
global.confirm = (m) => { confirmed.push(m); return confirmAnswer; };
global.setTimeout = () => 0;
global.setInterval = () => 0;
global.clearInterval = () => {};
"""


def _node(script: str) -> dict:
    src = _STUBS + VIEW.read_text(encoding="utf-8") + "\n" + script
    done = subprocess.run([NODE, "-e", src], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


MODEL = {
    "hosts": [{
        "id": "gpu01", "ssh": "me@gpu01", "error": None,
        "attachments": [{"server_id": "aaaa1111bbbb2222", "state": "healthy", "detail": None}],
        "servers": [
            {"id": "aaaa1111bbbb2222", "workdir": "/srv/<proj>", "version": "1.19.4",
             "label": "<img src=x onerror=alert(1)>", "token": "SECRET-TOKEN-1"},
            {"id": "cccc3333dddd4444", "workdir": "/home/me", "version": "1.19.4", "label": None},
        ],
        "counts": {"aaaa1111bbbb2222": {"sessions": 2, "activeRuns": 1}},
        "refused": [],
    }, {
        "id": "lab", "ssh": "lab", "error": "ssh: connect to host lab port 22: Connection refused",
        "attachments": [], "servers": None,
    }],
}


@needs_node
class TestRender:
    @pytest.fixture(scope="class")
    def html(self):
        return _node(f"process.stdout.write(JSON.stringify("
                     f"renderSshLauncher({json.dumps(MODEL)}, sshLauncherEscape)));")

    def test_announced_text_is_escaped(self, html):
        assert "<img" not in html and "<proj>" not in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html

    def test_no_token_is_rendered(self, html):
        assert "SECRET-TOKEN-1" not in html

    def test_rows_actions_and_counts(self, html):
        assert html.count('data-action="open"') == 2
        # Detach only for an attached server; Stop for every server.
        assert html.count('data-action="detach"') == 1
        assert html.count('data-action="stop"') == 2
        assert "2 sessions · 1 run active" in html
        assert "ssh-state-healthy" in html and "ssh-state-not-attached" in html

    def test_a_host_error_is_shown_not_hidden(self, html):
        assert "Connection refused" in html
        assert "ssh-dot-bad" in html

    def test_empty_host(self):
        model = {"hosts": [{"id": "h", "ssh": "h", "attachments": [], "servers": []}]}
        html = _node(f"process.stdout.write(JSON.stringify("
                     f"renderSshLauncher({json.dumps(model)}, sshLauncherEscape)));")
        assert "No ppxai servers running on this host." in html


_FAKE_FETCH = """
const calls = [];
const routes = %s;
function fakeFetch(url, init) {
    const path = url.replace(window.location.origin, '');
    calls.push([(init && init.method) || 'GET', path, init && init.body, (init && init.headers) || {}]);
    const body = routes[path];
    return Promise.resolve({ ok: body !== undefined, status: body !== undefined ? 200 : 404,
                             json: () => Promise.resolve(body === undefined ? {detail: 'nope'} : body) });
}
const container = { innerHTML: '', querySelectorAll: () => [],
                    addEventListener() {}, removeEventListener() {}, contains: () => true };
const view = new SshLauncherView({}, fakeFetch);
"""

HUB_ROUTES = {
    "/hub/hosts": {"hosts": [{
        "id": "gpu01", "ssh": "gpu01", "error": None,
        "attachments": [
            {"server_id": "healthy0000000001", "state": "healthy", "detail": None},
            {"server_id": "degraded000000002", "state": "degraded", "detail": "health: timeout"},
        ]}]},
    "/hub/hosts/gpu01/servers": {"refused": [], "servers": [
        {"id": "healthy0000000001", "workdir": "/a", "version": "1.19.4", "label": None},
        {"id": "degraded000000002", "workdir": "/b", "version": "1.19.4", "label": None},
        {"id": "idle0000000000003", "workdir": "/c", "version": "1.19.4", "label": None},
    ]},
    "/h/gpu01/healthy0000000001/sessions/list": {"count": 3, "sessions": []},
    "/h/gpu01/healthy0000000001/v1/agent/runs": {"runs": [
        {"status": "running"}, {"status": "completed"}, {"status": "parked"}]},
}


@needs_node
class TestBehaviour:
    def test_counts_are_read_only_through_healthy_attachments(self):
        out = _node(_FAKE_FETCH % json.dumps(HUB_ROUTES) + """
view._container = container;
view.refresh().then(() => process.stdout.write(JSON.stringify(
    { calls, html: container.innerHTML })));
""")
        proxied = [c[1] for c in out["calls"] if c[1].startswith("/h/")]
        assert proxied, "the healthy server's counts were never read"
        assert all(p.startswith("/h/gpu01/healthy0000000001/") for p in proxied), proxied
        assert all(c[0] == "GET" for c in out["calls"])
        assert "3 sessions · 2 runs active" in out["html"]
        # Observe only: a count read must never auto-attach (remote_hub.py).
        proxied_init = [c for c in out["calls"] if c[1].startswith("/h/")]
        assert all(c[3] == {"X-Ppxai-Hub-Attach": "no"} for c in proxied_init), proxied_init
        assert "health: timeout" in out["html"]

    def test_overlapping_refreshes_coalesce(self):
        # Three at once: one runs, the others fold into ONE follow-up.
        out = _node(_FAKE_FETCH % json.dumps(HUB_ROUTES) + """
view._container = container;
Promise.all([view.refresh(), view.refresh(), view.refresh()]).then(() =>
    process.stdout.write(JSON.stringify(calls.filter(c => c[1] === '/hub/hosts').length)));
""")
        assert out == 2

    def test_open_uses_one_named_tab_per_server(self):
        out = _node(_FAKE_FETCH % "{}" + """
view.open('gpu01', 'abc');
view.open('gpu01', 'abc');
process.stdout.write(JSON.stringify(window.opened));
""")
        assert out == [["http://127.0.0.1:54320/h/gpu01/abc/", "ppxai-gpu01-abc"]] * 2

    @pytest.mark.parametrize("answer", [False, True])
    def test_stop_asks_first(self, answer):
        out = _node(_FAKE_FETCH % json.dumps(HUB_ROUTES) + f"""
confirmAnswer = {json.dumps(answer)};
view._container = container;
const btn = {{ dataset: {{ action: 'stop', host: 'gpu01', server: 'idle0000000000003', label: 'idle' }} }};
view._handleClick({{ target: {{ closest: () => btn }} }});
Promise.resolve().then(() => process.stdout.write(JSON.stringify({{ calls, confirmed }})));
""")
        assert len(out["confirmed"]) == 1 and "idle" in out["confirmed"][0]
        posts = [c for c in out["calls"] if c[0] == "POST"]
        if answer:
            assert [c[:3] for c in posts] == [["POST", "/hub/hosts/gpu01/servers/idle0000000000003/stop", "{}"]]
        else:
            assert posts == [], "declining the confirm must not stop the server"

    def test_detach_does_not_ask(self):
        out = _node(_FAKE_FETCH % json.dumps(HUB_ROUTES) + """
view._container = container;
const btn = { dataset: { action: 'detach', host: 'gpu01', server: 'healthy0000000001' } };
view._handleClick({ target: { closest: () => btn } });
Promise.resolve().then(() => process.stdout.write(JSON.stringify({ calls, confirmed })));
""")
        assert out["confirmed"] == []
        assert ["POST", "/hub/hosts/gpu01/servers/healthy0000000001/detach", "{}"] in [c[:3] for c in out["calls"]]


class TestContracts:
    def test_the_icon_is_the_brand_bubble_with_a_prompt(self):
        # Same bubble geometry and gradient as the brand icon, so the two
        # stay recognisably one family (owner's pick, 2026-09-28).
        src = VIEW.read_text(encoding="utf-8")
        brand = (WEB.parents[1] / "vscode-extension" / "resources" / "icon.svg").read_text(encoding="utf-8")
        for part in ('rect x="8" y="8" width="112" height="88" rx="16"',
                     "points=\"24,96 24,120 48,96\"", "#6366f1", "#8b5cf6"):
            assert part in brand and part in src, part

    @needs_node
    def test_the_icon_is_a_self_contained_data_uri(self):
        html = _node("process.stdout.write(JSON.stringify(sshLauncherIconHtml(16)));")
        assert html.startswith('<img class="ssh-icon" src="data:image/svg+xml,%3Csvg')
        assert 'width="16" height="16"' in html
        assert "<svg" not in html, "inline <svg> ids would collide; keep it a data: URI"

    def test_terminal_run_statuses_match_the_registry(self):
        src = VIEW.read_text(encoding="utf-8")
        m = re.search(r"SSH_LAUNCHER_TERMINAL_RUNS = new Set\(\s*\[([^\]]*)\]", src)
        listed = set(re.findall(r"'([a-z_]+)'", m.group(1)))
        assert listed == set(AgentRunRegistry._TERMINAL_STATUSES)

    def test_the_view_loads_before_app_js_and_after_base_view(self):
        html = INDEX.read_text(encoding="utf-8")
        order = [html.index(f'src="{s}"') for s in (
            "shared/formatters.js", "components/views/base-view.js",
            "components/views/ssh-launcher-view.js", "app.js")]
        assert order == sorted(order)

    def test_the_button_and_badge_start_hidden(self):
        html = INDEX.read_text(encoding="utf-8")
        assert re.search(r'<button[^>]*class="[^"]*\bhidden\b[^"]*"[^>]*id="sshBtn"', html)
        assert re.search(r'<span[^>]*class="[^"]*\bhidden\b[^"]*"[^>]*id="hostBadge"', html)


class TestAppJsWiring:
    def test_the_hub_probe_runs_after_connecting(self):
        src = _read(APP_JS_PATH)
        assert re.search(r"await this\.connectToServer\(\);\s*await this\._initRemoteHub\(\);", src)

    def test_the_probe_only_runs_on_the_local_page(self):
        body = _extract_braced_body(_read(APP_JS_PATH), r"async _initRemoteHub\(\)\s*")
        remote_at = body.index("if (hub)")
        prefix_at = body.index("servedPathPrefix(window.location.pathname)")
        fetch_at = body.index("/hub/hosts")
        # A proxied remote page returns before probing; so does a coder /s/ page.
        assert remote_at < prefix_at < fetch_at
        assert "return;" in body[remote_at:prefix_at]
        assert "#ssh" in body[fetch_at:] and "openSshLauncher()" in body[fetch_at:]

    def test_the_button_opens_the_launcher(self):
        src = _read(APP_JS_PATH)
        assert "this.elements.sshBtn.addEventListener('click', () => this.openSshLauncher())" in src

    def test_the_launcher_is_never_persisted_as_a_file(self):
        body = _extract_braced_body(_read(APP_JS_PATH), r"(?m)^\s*_saveRpfStack\(\)\s*")
        assert "view instanceof SshLauncherView) continue" in body
