"""VSCode smoke defects 1, 2, 6 and 7 (found 2026-09-26, fixed 2026-09-27).

1. Inline `style="display:none"` is ignored under the webview CSP, which
   has no 'unsafe-inline' for style-src; six elements started visible.
2. marked passed raw HTML through, so "Use '/auto <task>'" lost `<task>`.
   The web client had the same code.
6. `/auto` read `TASK_COMPLETE:` only from `chunk` events; a tool-using
   turn sends its text in `done`, so the loop never stopped. "Max
   iterations reached" was also posted unconditionally.
7. The schema guard ran only in `initializeBackend()`, so a server
   restarted under a live connection was never re-checked.

Defects 2 and 6 run the real code under Node: the shipped marked build,
and `autoLoop.ts` compiled with the extension's esbuild. Defects 1 and 7
are wiring in `vscode`-bound code and are pinned structurally.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import ESBUILD, minimal_subprocess_env

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "vscode-extension"
CHAT_PANEL = EXT / "src" / "chatPanel.ts"
MAIN_JS = EXT / "media" / "webview" / "main.js"
STYLES = EXT / "media" / "webview" / "styles.css"
WEB_APP = ROOT / "ppxai" / "web" / "app.js"
MARKED = EXT / "media" / "marked.min.js"
NODE = shutil.which("node")

needs_node = pytest.mark.skipif(NODE is None, reason="node is required")

#: The six elements that start hidden.
STARTS_HIDDEN = (
    "streamingBadge", "agentBeatBadge", "backgroundAgentsBadge",
    "hintsBadge", "workspaceInfo", "fileInput",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Defect 1
# ---------------------------------------------------------------------------


class TestDefect1NoInlineStyles:

    def test_the_csp_still_forbids_inline_styles(self):
        """The fix works WITH the CSP; loosening it is not the fix."""
        csp = re.search(r'Content-Security-Policy" content="([^"]+)"', _read(CHAT_PANEL))
        assert csp, "CSP meta tag not found"
        assert "unsafe-inline" not in csp.group(1)

    def test_the_webview_markup_has_no_inline_style_attribute(self):
        """Any `style="..."` in the webview HTML is silently ignored."""
        html = _read(CHAT_PANEL).split("Content-Security-Policy", 1)[1]
        assert not re.findall(r'\sstyle="', html)

    @pytest.mark.parametrize("element_id", STARTS_HIDDEN)
    def test_each_element_starts_hidden_by_attribute(self, element_id):
        tag = re.search(rf'<[^>]*id="{element_id}"[^>]*>', _read(CHAT_PANEL))
        assert tag, element_id
        assert re.search(r"\shidden(\s|>|$)", tag.group(0)), tag.group(0)

    def test_the_hidden_attribute_beats_class_display_rules(self):
        assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important;?\s*\}", _read(STYLES))

    def test_the_toggles_use_hidden_not_style_display(self):
        js = _read(MAIN_JS)
        names = ("streamingBadge", "hintsBadge", "workspaceInfoEl")
        for name in names:
            assert f"{name}.style.display" not in js, name
            assert f"{name}.hidden" in js, name


# ---------------------------------------------------------------------------
# Defect 2
# ---------------------------------------------------------------------------

_MARKED_HARNESS = r"""
const { marked } = require(process.env.MARKED);
global.document = {
  createElement() {
    let t = '';
    return {
      set textContent(v) { t = String(v); },
      get innerHTML() {
        return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      },
    };
  },
};
const escapeHtml = (s) => {
  const d = document.createElement('div'); d.textContent = String(s); return d.innerHTML;
};
marked.setOptions({ breaks: true, gfm: true });
eval(process.env.CONFIG);
const out = {};
for (const [k, v] of Object.entries(JSON.parse(process.env.CASES))) out[k] = marked.parse(v);
console.log(JSON.stringify(out));
"""

_CASES = {
    "task": "Use '/auto <task>' to start",
    "img": "<img src=x onerror=alert(1)>",
    "code": "`<b>` stays code",
    "link": ('see <a href="https://x.io" target="_blank" rel="noopener" '
             'class="url-link">https://x.io</a> ok'),
}


def _marked_use_block(source: str, anchor: str) -> str:
    """The `marked.use({...});` statement after `anchor`, balanced by braces."""
    at = source.index(anchor)
    start = source.index("marked.use(", at)
    depth, i = 0, source.index("(", start)
    while True:
        ch = source[i]
        depth += ch == "("
        depth -= ch == ")"
        i += 1
        if depth == 0:
            break
    return source[start:i] + ";"


def _render(config: str) -> dict[str, str]:
    env = minimal_subprocess_env(
        PATH="", MARKED=str(MARKED), CONFIG=config, CASES=json.dumps(_CASES),
    )
    proc = subprocess.run(
        [NODE, "-e", _MARKED_HARNESS], capture_output=True, text=True,
        encoding="utf-8", env=env, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@needs_node
class TestDefect2RawHtmlIsEscaped:

    def _vscode(self):
        src = _read(MAIN_JS)
        # The URL_LINK_OPEN regex and escapeRawHtml helper precede the block.
        head = src[src.index("const URL_LINK_OPEN"):src.index("marked.use(")]
        return _render(head + _marked_use_block(src, "Smoke defect 2"))

    def _web(self):
        return _render(_marked_use_block(_read(WEB_APP), "Smoke defect 2"))

    @pytest.mark.parametrize("client", ["_vscode", "_web"])
    def test_a_tag_like_word_survives_as_text(self, client):
        out = getattr(self, client)()
        assert "&lt;task&gt;" in out["task"]
        assert "<task>" not in out["task"]

    @pytest.mark.parametrize("client", ["_vscode", "_web"])
    def test_raw_html_is_inert(self, client):
        out = getattr(self, client)()
        assert "<img" not in out["img"]

    @pytest.mark.parametrize("client", ["_vscode", "_web"])
    def test_code_spans_are_not_double_escaped(self, client):
        assert "<code>&lt;b&gt;</code>" in getattr(self, client)()["code"]

    def test_vscode_keeps_its_own_injected_url_link(self):
        assert 'class="url-link">https://x.io</a>' in self._vscode()["link"]


# ---------------------------------------------------------------------------
# Defect 6
# ---------------------------------------------------------------------------

_AUTO_HARNESS = r"""
const { AutoIterationText, taskCompleteSummary } = require(process.env.BUNDLE);
const run = (events) => { const t = new AutoIterationText(); events.forEach((e) => t.add(e)); return t.text; };
console.log(JSON.stringify({
  toolPath: taskCompleteSummary(run([
    { type: 'tool_call', content: '' }, { type: 'tool_result', content: 'x' },
    { type: 'done', content: 'All set.\nTASK_COMPLETE: wrote the file' },
  ])),
  chunkPath: taskCompleteSummary(run([
    { type: 'chunk', content: 'TASK_COMP' }, { type: 'chunk', content: 'LETE: ok' },
  ])),
  notDone: taskCompleteSummary(run([{ type: 'done', content: 'still working' }])),
  bare: taskCompleteSummary('TASK_COMPLETE:'),
  doneWins: run([{ type: 'chunk', content: 'partial' }, { type: 'done', content: 'whole' }]),
}));
"""


@pytest.mark.skipif(NODE is None or not ESBUILD.exists(), reason="node and esbuild are required")
class TestDefect6AutoLoopSeesCompletion:

    @pytest.fixture(scope="class")
    def result(self, tmp_path_factory):
        out = tmp_path_factory.mktemp("auto") / "autoLoop.js"
        build = subprocess.run(
            [str(ESBUILD), str(EXT / "src" / "autoLoop.ts"), "--bundle", "--format=cjs",
             "--platform=node", "--target=node18", f"--outfile={out}"],
            capture_output=True, text=True, timeout=120,
        )
        assert build.returncode == 0, build.stderr
        proc = subprocess.run(
            [NODE, "-e", _AUTO_HARNESS], capture_output=True, text=True,
            env=minimal_subprocess_env(PATH="", BUNDLE=str(out)), timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    def test_the_tool_path_done_event_is_read(self, result):
        assert result["toolPath"] == "wrote the file"

    def test_streamed_chunks_still_work(self, result):
        assert result["chunkPath"] == "ok"

    def test_no_marker_means_not_complete(self, result):
        assert result["notDone"] is None

    def test_a_bare_marker_is_done(self, result):
        assert result["bare"] == "Done"

    def test_the_whole_done_text_wins_over_partial_chunks(self, result):
        assert result["doneWins"] == "whole"


class TestDefect6LoopWiring:

    def test_the_loop_feeds_every_event_to_the_collector(self):
        src = _read(CHAT_PANEL)
        assert "reply.add(event)" in src
        assert "event.type === 'chunk' && event.content" not in src.split("handleAgentCommand", 1)[-1]

    def test_max_iterations_is_posted_only_when_the_loop_ran_out(self):
        src = _read(CHAT_PANEL)
        at = src.index("Max iterations (${maxIterations}) reached")
        assert "if (!stopped) {" in src[at - 200:at]


# ---------------------------------------------------------------------------
# Defect 7
# ---------------------------------------------------------------------------


class TestDefect7SchemaRecheckedOnFocus:

    def test_the_focus_reanchor_asks_for_a_schema_check(self):
        assert "installFocusReanchor(() => this._reanchorFromServer(true))" in _read(CHAT_PANEL)

    def test_the_reanchor_runs_the_guard_before_fetching_state(self):
        src = _read(CHAT_PANEL)
        body = src[src.index("private async _reanchorFromServer(checkSchema = false)"):]
        body = body[:body.index("\n    }\n")]
        assert body.index("this._schemaGuard.check()") < body.index("this._backend.fetchState()")

    def test_the_switch_reanchor_does_not_recheck(self):
        """Provider/model switches keep the default (same server), as on web."""
        src = _read(CHAT_PANEL)
        assert "await this._reanchorFromServer();" in src
