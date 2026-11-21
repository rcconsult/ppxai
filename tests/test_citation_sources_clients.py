"""ADR 0019 step 4: every client shows a turn's or a run's numbered sources.

The engine already puts them on a chat STREAM_END (`metadata.sources`), on a
stored assistant message (`Message.sources`) and on a run (`RunMeta.sources`).
These tests hold the four clients to rendering them:

- web + VSCode share ONE renderer, `sources-render.js`, kept as two
  byte-identical copies (the two clients share no code otherwise); its
  behaviour runs under plain Node;
- both TUIs and `/export` use `engine/sources.py::format_sources_markdown`;
  `/task get` (plain text, both TUIs) uses `format_sources_text`;
- each client's wiring is fenced by source, so dropping one fails here.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import time
from types import SimpleNamespace

import pytest

from ppxai.engine.sources import Source, format_sources_markdown, format_sources_text
from ppxai.engine.types import Event, EventType
from ppxai.rich.event_handler import EventHandler
from ppxai.tui import stream_handler
from ppxai.tui.event_bus import Events

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "ppxai" / "web" / "shared" / "sources-render.js"
VSC_JS = ROOT / "vscode-extension" / "media" / "webview" / "sources-render.js"
NODE = shutil.which("node")

ROWS = [
    {"n": 2, "url": "https://www.example.org/b?x=1&y=2", "title": "B <script>", "backend": "gemini", "query": "q"},
    {"n": 1, "url": "https://a.example.com/", "title": None, "backend": "perplexity", "query": "q"},
    {"n": 3, "url": "javascript:alert(1)", "title": "evil", "backend": "x", "query": "q"},
]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# --- one renderer, two copies ------------------------------------------------

def test_web_and_vscode_copies_are_byte_identical():
    assert WEB_JS.read_bytes() == VSC_JS.read_bytes(), (
        "ppxai/web/shared/sources-render.js and vscode-extension/media/webview/"
        "sources-render.js must stay identical — copy the edited one over the other"
    )


def _node(expr: str, rows) -> str:
    script = (
        f"const r = require({json.dumps(str(WEB_JS))});"
        f"const rows = {json.dumps(rows)};"
        f"process.stdout.write(String({expr}));"
    )
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return out.stdout


@pytest.mark.skipif(NODE is None, reason="node is required")
class TestSourcesHtmlUnderNode:
    def test_numbered_in_order_and_escaped(self):
        html = _node("r.sourcesHtml(rows)", ROWS)
        assert html.index('value="1"') < html.index('value="2"') < html.index('value="3"')
        assert "<script>" not in html and "B &lt;script&gt;" in html
        assert 'href="https://www.example.org/b?x=1&amp;y=2"' in html
        assert 'target="_blank" rel="noopener noreferrer"' in html
        # no title → the host is the label
        assert ">a.example.com</a>" in html

    def test_only_http_urls_become_links(self):
        html = _node("r.sourcesHtml(rows)", ROWS)
        assert "javascript:" not in html.split("<span title=")[0]
        assert html.count("<a ") == 2
        assert '<span title="javascript:alert(1)">evil</span>' in html

    @pytest.mark.parametrize("rows", [None, [], [{"n": 1}], [{"url": "https://x.org"}], "nope"])
    def test_nothing_to_show_is_empty(self, rows):
        assert _node("r.sourcesHtml(rows)", rows) == ""


def test_both_pages_load_the_renderer_before_their_app_code():
    index = _read("ppxai/web/index.html")
    assert '<script src="shared/sources-render.js"></script>' in index
    assert index.index("shared/sources-render.js") < index.index('src="app.js"')
    panel = _read("vscode-extension/src/chatPanel.ts")
    assert "'sources-render.js'" in panel
    assert panel.index("${sourcesJsUri}") < panel.index("${webviewJsUri}")


# --- each client's wiring (source fence) -------------------------------------

WIRING = {
    # web: chat stream_end, the run pane, the run fallback message
    "ppxai/web/app.js": ["attachSources(contentEl, event.metadata && event.metadata.sources)"],
    "ppxai/web/shared/agent-run-controller.js": [
        "view.setResult(run.result || '', run.sources)",
        "attachSources(contentEl, run.sources)",
    ],
    "ppxai/web/components/views/agent-run-view.js": ["setResult(markdown, sources)", "sourcesHtml(sources)"],
    # VSCode: done metadata → bus → webview; history mirror; run result
    "vscode-extension/src/handlers/stream.ts": ["eventBus.emit('stream:done', event.content, sourcesOf(event.metadata))"],
    "vscode-extension/src/chatPanel.ts": [
        "postMessage({ type: 'fullResponse', content, sources })",
        "postMessage({ type: 'fullResponse', content: text, sources })",
    ],
    "vscode-extension/src/httpClient.ts": ["content: fullResponse, sources: turnSources"],
    "vscode-extension/src/taskController.ts": ["this.ui.result(run.result, run.sources)"],
    "vscode-extension/media/webview/main.js": [
        "attachSources(\n                    currentResponseEl.querySelector('.message-content'), message.sources)",
        "attachSources(el.querySelector('.message-content'), msg.sources)",
    ],
    # TUIs: stream end, restore, /task get
    "ppxai/tui/stream_handler.py": [
        'format_sources_markdown((kwargs.get("metadata") or {}).get("sources"))',
        # the worker thread hands the event's metadata to the main thread
        "handle_stream_event, app, event.type.name, event.data, event.metadata",
    ],
    "ppxai/tui/session_restore_ops.py": ['format_sources_markdown(getattr(msg, "sources", None))'],
    "ppxai/rich/event_handler.py": ['format_sources_markdown((event.metadata or {}).get("sources"))'],
    "ppxai/commands/task.py": ['format_sources_text(getattr(meta, "sources", None))'],
    "ppxai/engine/session.py": ["format_sources_markdown(msg.sources)"],
}


@pytest.mark.parametrize("rel,needles", sorted(WIRING.items()))
def test_client_wiring_renders_sources(rel, needles):
    src = _read(rel)
    for needle in needles:
        assert needle in src, f"{rel} no longer renders ADR 0019 sources: missing {needle!r}"


# --- Python formatters --------------------------------------------------------

class TestPythonFormatters:
    def test_markdown_is_numbered_by_n_and_links_only_http(self):
        md = format_sources_markdown(ROWS)
        lines = md.splitlines()
        assert lines[0] == "**Sources:**"
        assert lines[2] == "1. [https://a.example.com/](<https://a.example.com/>)"
        assert lines[3] == "2. [B <script>](<https://www.example.org/b?x=1&y=2>)"
        assert lines[4] == "3. evil"

    def test_markdown_escapes_brackets_in_titles(self):
        md = format_sources_markdown([{"n": 1, "url": "https://x.org", "title": "a [1] b"}])
        assert "[a \\[1\\] b](<https://x.org>)" in md

    def test_accepts_source_objects_and_skips_malformed(self):
        rows = [Source(n=1, url="https://x.org", title="X"), {"n": "2", "url": "https://y"}, {"n": 3}]
        assert format_sources_markdown(rows).splitlines()[2:] == ["1. [X](<https://x.org>)"]
        assert format_sources_text(rows) == "[1] X https://x.org"

    @pytest.mark.parametrize("rows", [None, [], [{"n": 1}]])
    def test_empty(self, rows):
        assert format_sources_markdown(rows) == "" and format_sources_text(rows) == ""


# --- Rich: STREAM_END appends the list to what it displays --------------------

class TestRichStreamEnd:
    def _end(self, data, metadata):
        shown: list[str] = []
        EventHandler(on_stream_end=shown.append)._handle_stream_end(
            Event(type=EventType.STREAM_END, data=data, metadata=metadata)
        )
        return shown

    def test_sources_follow_the_answer(self):
        (shown,) = self._end("Answer [1].", {"sources": ROWS[:1]})
        assert shown.startswith("Answer [1].\n\n**Sources:**")
        assert "<https://www.example.org/b?x=1&y=2>" in shown

    def test_no_sources_leaves_the_answer_alone(self):
        assert self._end("Answer.", {}) == ["Answer."]
        assert self._end("Answer.", None) == ["Answer."]

    def test_empty_answer_gets_no_list(self):
        assert self._end("", {"sources": ROWS}) == [""]


# --- Textual: metadata reaches the bus, and on_stream_end shows the list ------

class TestTextualStreamEnd:
    def test_handle_stream_event_passes_metadata_to_the_bus(self):
        seen = []
        app = SimpleNamespace(
            _event_bus=SimpleNamespace(emit=lambda ev, **kw: seen.append((ev, kw))),
            _trace_logging=False,
        )
        stream_handler.handle_stream_event(app, "STREAM_END", "x", {"sources": ROWS})
        ((ev, kw),) = seen
        assert ev == Events.ENGINE_STREAM_END
        assert kw["metadata"] == {"sources": ROWS}

    def test_metadata_is_optional(self):
        seen = []
        app = SimpleNamespace(
            _event_bus=SimpleNamespace(emit=lambda ev, **kw: seen.append(kw)), _trace_logging=False
        )
        stream_handler.handle_stream_event(app, "STREAM_END", "x")
        assert seen[0]["metadata"] is None

    @pytest.mark.asyncio
    async def test_on_stream_end_appends_the_list(self, monkeypatch):
        monkeypatch.setattr(stream_handler, "clear_thinking_indicator", lambda app: None)
        monkeypatch.setattr(stream_handler, "update_usage_display", lambda app: None)
        added = []
        app = SimpleNamespace(
            _chat_view=SimpleNamespace(add_assistant_message=lambda c, response_time=0.0: added.append(c)),
            _log=SimpleNamespace(debug=lambda *a, **k: None, warning=lambda *a, **k: None),
            _current_message_content="Answer [1].",
            _reasoning_message=None, _reasoning_content="", _reasoning_started=False,
            _response_start_time=time.time(),
            _engine_client=SimpleNamespace(session=SimpleNamespace(messages=[])),
        )
        await stream_handler.on_stream_end(app, None, data="", metadata={"sources": ROWS[1:2]})
        assert added == ["Answer [1].\n\n**Sources:**\n\n1. [https://a.example.com/](<https://a.example.com/>)"]
