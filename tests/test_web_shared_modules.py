"""Static structural tests for the new v1.18.1 web shared modules.

Step 2b of v1.18.1 plan adds two pure JS modules under
`ppxai/web/shared/`:

  - `result-renderer.js` — type-based dispatch keyed off
    `result.type` from the v1.18.1 envelope's `result` field.
  - `side-effects.js`    — kind→DOM-action dispatch for the
    envelope's `side_effects[]` array.

Runtime behavior is exercised by the e2e suite (Step 6) against a
real spawned server. These tests pin the structural contracts:
- Both modules export their class via window AND CommonJS.
- Each handles every kind / type listed in its contract docstring
  (drift fence: if a new kind is added in
  `ppxai/commands/results.py::SideEffectKind` without a web
  handler, the parity test in `test_command_envelope.py` will
  catch the drift; this file pins that web's known set is at
  least the v1.18.1 minimum).
- index.html loads them BEFORE command-dispatcher.js (ordering
  matters: dispatcher uses both classes).
"""

from __future__ import annotations

import re
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1] / "ppxai" / "web"
SHARED = WEB_DIR / "shared"


def _read(name: str) -> str:
    return (SHARED / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# result-renderer.js
# ---------------------------------------------------------------------------

class TestResultRenderer:
    def test_module_file_exists(self):
        assert (SHARED / "result-renderer.js").exists()

    def test_class_defined(self):
        src = _read("result-renderer.js")
        assert "class ResultRenderer" in src

    def test_render_method_exists(self):
        src = _read("result-renderer.js")
        assert re.search(r"\brender\s*\(\s*result\s*\)", src), (
            "ResultRenderer.render(result) not found"
        )

    def test_window_export(self):
        src = _read("result-renderer.js")
        assert "window.ResultRenderer" in src, (
            "ResultRenderer must be exposed on window for app.js"
        )

    def test_commonjs_export(self):
        src = _read("result-renderer.js")
        assert "module.exports" in src and "ResultRenderer" in src

    def test_handles_seven_core_result_types(self):
        """The seven CommandResult types most-used today must each
        have an explicit handler. Adding more is fine (open enum on
        the fall-through), but these are the v1.18.1 floor."""
        src = _read("result-renderer.js")
        for type_name in (
            "NotificationResult",
            "ConfirmationResult",
            "ErrorResult",
            "MarkdownResult",
            "TableResult",
            "TreeResult",
            "KeyValueResult",
        ):
            assert type_name in src, (
                f"ResultRenderer missing handler for {type_name}"
            )

    def test_unknown_type_falls_through(self):
        """Unknown result.type values must not throw — they fall
        through to result.message as system text."""
        src = _read("result-renderer.js")
        assert "_default" in src or "_fallback" in src, (
            "ResultRenderer must have a default/fallback for unknown types"
        )


# ---------------------------------------------------------------------------
# side-effects.js
# ---------------------------------------------------------------------------

class TestSideEffectsHandler:
    def test_module_file_exists(self):
        assert (SHARED / "side-effects.js").exists()

    def test_class_defined(self):
        src = _read("side-effects.js")
        assert "class SideEffectsHandler" in src

    def test_apply_method_exists(self):
        src = _read("side-effects.js")
        assert re.search(r"\bapply\s*\(\s*sideEffects\s*\)", src), (
            "SideEffectsHandler.apply(sideEffects) not found"
        )

    def test_window_export(self):
        src = _read("side-effects.js")
        assert "window.SideEffectsHandler" in src

    def test_commonjs_export(self):
        src = _read("side-effects.js")
        assert "module.exports" in src and "SideEffectsHandler" in src

    def test_handles_every_v18_1_kind(self):
        """Drift fence: every kind in v1.18.1 SideEffectKind must
        have a handler in side-effects.js. The Python sentinel
        (test_command_envelope.py::TestSideEffectKindTaxonomy) pins
        the kind set; this test pins the web's coverage of it."""
        src = _read("side-effects.js")
        # Mirror the v1.18.1 EXPECTED_KINDS_V1 frozenset
        expected = {
            "open_editor",
            "open_viewer",
            "show_image",
            "show_pdf",
            "reveal_in_explorer",
            "open_terminal",
            "run_shell",
            "open_html_preview",
            "refresh_file_tree",
            "set_theme",
            "copy_to_clipboard",
            "attach_file",
            "prompt_quick_pick",
            "notify",
            "vscode_delegate",
        }
        for kind in expected:
            assert kind in src, (
                f"side-effects.js missing handler for kind: {kind}"
            )

    def test_unknown_kind_is_no_op(self):
        """Open-enum invariant: unknown kinds are silently ignored,
        not thrown, so client-specific kinds (like vscode_delegate
        for VSCode-only) don't break the other client."""
        src = _read("side-effects.js")
        # The class explicitly checks `if (!handler)` and continues
        assert "if (!handler)" in src or "if (handler)" in src, (
            "SideEffectsHandler must check handler existence before calling"
        )

    def test_quick_pick_resume_protocol(self):
        """Per ADR Q3 (b): the chosen value IS the literal next
        args. The web handler must dispatch the resume command via
        the dispatcher, not via a server-side continuation call."""
        src = _read("side-effects.js")
        # Must reference the dispatcher dispatch entry point with
        # the chosen value
        assert "commandDispatcher" in src and "dispatch" in src, (
            "prompt_quick_pick handler must re-issue the command via "
            "commandDispatcher.dispatch"
        )

    def test_per_handler_errors_are_caught(self):
        """One bad side-effect (e.g. clipboard denied) must not
        prevent the rest of the batch from running."""
        src = _read("side-effects.js")
        # Look for try/catch in the apply loop
        match = re.search(
            r"\bapply\s*\([\s\S]*?\}\s*\n\s*\}",
            src,
        )
        assert match, "could not extract apply() body"
        body = match.group(0)
        assert "try" in body and "catch" in body, (
            "apply() loop must wrap each handler in try/catch"
        )


# ---------------------------------------------------------------------------
# index.html — load order
# ---------------------------------------------------------------------------

class TestIndexHtmlScriptOrder:
    def test_renderer_loaded_before_dispatcher(self):
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        renderer_pos = html.find("result-renderer.js")
        dispatcher_pos = html.find("command-dispatcher.js")
        assert renderer_pos != -1, (
            "result-renderer.js missing from index.html"
        )
        assert dispatcher_pos != -1
        assert renderer_pos < dispatcher_pos, (
            "result-renderer.js must load BEFORE command-dispatcher.js"
        )

    def test_side_effects_loaded_before_dispatcher(self):
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        se_pos = html.find("side-effects.js")
        dispatcher_pos = html.find("command-dispatcher.js")
        assert se_pos != -1, "side-effects.js missing from index.html"
        assert se_pos < dispatcher_pos, (
            "side-effects.js must load BEFORE command-dispatcher.js"
        )


class TestPreviewUrlNormalisesWindowsPaths:
    """`/preview` rendered "Internal Server Error" on Windows and nowhere else.

    `openHtmlPreview` builds a RELATIVE iframe URL by stripping the
    working-dir prefix, then percent-encoding each `/`-separated segment.
    Both steps assumed POSIX separators. On Windows the server returns a
    native path (`C:\\proj\\index.html`) while `working_dir` carries forward
    slashes, so `startsWith` never matched, `split('/')` saw ONE segment, and
    the whole path was encoded backslashes and all:

        /preview/C%3A%5Cproj%5Cindex.html   -> HTTP 500
        /preview/index.html                 -> HTTP 200

    The command itself reported success (ok=True, side-effect dispatched), so
    only the pane was broken -- which is why it read as "preview does not
    work at all". Measured against the running server 2026-09-13.

    Source-text assertions match this file's existing idiom: the web tree is
    not executed under pytest, so the fence is that the normalisation is
    PRESENT and that the raw un-normalised form has not come back.
    """

    def _preview_block(self) -> str:
        app = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        start = app.find("openHtmlPreview(filepath")
        assert start != -1, "openHtmlPreview not found in app.js"
        end = app.find("const encodedPath", start)
        assert end != -1, "encodedPath construction not found after openHtmlPreview"
        return app[start:end]

    def test_filepath_is_normalised_before_use(self):
        block = self._preview_block()
        assert "replace(/\\\\/g, '/')" in block, (
            "openHtmlPreview must normalise backslashes to forward slashes "
            "before comparing/splitting, or Windows paths produce a 500"
        )

    def test_working_dir_is_normalised_too(self):
        """Normalising only one side still fails: the prefix never matches."""
        block = self._preview_block()
        wd_line = [ln for ln in block.splitlines() if "workingDir" in ln]
        assert wd_line, "workingDir lookup missing from openHtmlPreview"
        assert any("replace(" in ln for ln in wd_line), (
            "the working-dir side must be normalised as well -- comparing a "
            "normalised filepath against a raw working_dir still never matches"
        )

    def test_the_unnormalised_form_has_not_returned(self):
        """Guards the exact pre-fix line, which looked correct on POSIX."""
        block = self._preview_block()
        assert "let pathForUrl = filepath;" not in block, (
            "pathForUrl must not be assigned the raw filepath -- that is the "
            "pre-2026-09-13 form that broke every Windows preview"
        )


class TestToolTurnWrapper:
    """The per-turn tool strip, and the two clients staying the same shape.

    v1.19.3. The engine emits one TOOL_GROUP_START per tool-loop ITERATION
    (`engine/chat.py`), and an agentic run is usually one or two tools per
    iteration -- so a twelve-iteration run stacked twelve collapsed strips
    between the prompt and the answer, each inserted BEFORE the assistant
    message and so pushing the answer further down. `.tool-turn` is the level
    above: one strip per assistant turn.

    Source-text assertions, matching this file's existing idiom: the web tree
    is not executed under pytest, and the logic lives on a class in a
    3,700-line file that cannot be instantiated standalone. The CSS collapse
    contract has real DOM coverage in `tests/e2e/tool-turn.spec.ts`; what is
    fenced HERE is the JS wiring that Playwright harness deliberately does not
    reimplement -- when a turn opens, where groups nest, and when it closes.
    """

    def _app_js(self) -> str:
        return (WEB_DIR / "app.js").read_text(encoding="utf-8")

    def _vscode_js(self) -> str:
        return (
            WEB_DIR.parent.parent
            / "vscode-extension"
            / "media"
            / "webview"
            / "main.js"
        ).read_text(encoding="utf-8")

    def test_the_group_nests_inside_the_turn(self):
        """A group appended to the container instead is the original bug."""
        app = self._app_js()
        assert "_ensureToolTurn()" in app, "the per-turn wrapper is gone"
        assert "querySelector('.tool-turn-body').appendChild(groupEl)" in app, (
            "iteration groups must be appended INTO the turn wrapper; "
            "appending them to the messages container is exactly the "
            "pre-v1.19.3 behaviour that stacked a strip per iteration"
        )

    def test_the_turn_is_closed_in_the_streaming_finally(self):
        """A turn left open leaks the next turn's tools into this strip."""
        app = self._app_js()
        start = app.find("} finally {", app.find("this.state.currentAssistantMessage = msgEl;"))
        assert start != -1, "streaming finally block not found"
        block = app[start:start + 1200]
        assert "this.endToolTurn()" in block, (
            "endToolTurn() must run in the streaming `finally` so an "
            "interrupted or failed turn still closes its strip"
        )
        assert block.find("this.endToolTurn()") < block.find(
            "this.state.currentAssistantMessage = null"
        ), (
            "endToolTurn() must run BEFORE currentAssistantMessage is "
            "cleared -- that reference is the strip's insertion anchor"
        )

    def test_clearing_the_transcript_drops_the_wrapper(self):
        """Otherwise the next turn appends into a detached node."""
        app = self._app_js()
        start = app.find("async clearConversation()")
        assert start != -1, "clearConversation not found"
        block = app[start:start + 900]
        assert "this._toolTurn = null" in block and "this._currentToolGroup = null" in block, (
            "clearConversation must drop both the turn and group references; "
            "they point at DOM it is about to discard, and a stale one "
            "silently swallows the next turn's tool bubbles"
        )

    def test_tool_details_are_always_rendered(self):
        """Verbose means 'start expanded', never 'render at all'."""
        app = self._app_js()
        assert "_fillToolBubble(" in app, "the shared bubble builder is gone"
        start = app.find("_fillToolBubble(msgEl, icon, name, payload) {")
        assert start != -1, "_fillToolBubble definition not found"
        block = app[start:app.find("showToolCall(data) {", start)]
        assert "const hasPayload = Boolean(payload);" in block, (
            "whether to render details must depend on the PAYLOAD, not on "
            "toolsVerbose -- gating on verbose while rendering the chevron "
            "unconditionally is what made a click reveal nothing"
        )
        assert "msgEl.classList.add('expanded')" in block, (
            "verbose mode must pre-expand the bubble"
        )

    def test_the_verbose_gated_details_have_not_returned(self):
        """Guards the exact pre-fix condition."""
        app = self._app_js()
        assert "if (this.state.toolsVerbose && data.arguments)" not in app, (
            "this is the pre-v1.19.3 form: details built only in verbose "
            "mode while the chevron rendered either way"
        )
        assert "if (this.state.toolsVerbose && data.result)" not in app, (
            "same defect on the result bubble"
        )

    def test_the_disclosure_is_keyboard_reachable(self):
        """New interactive UI does not get to be mouse-only."""
        app = self._app_js()
        assert "_wireDisclosure(header, target, collapsedClass)" in app, (
            "the shared disclosure helper is gone"
        )
        start = app.find("_wireDisclosure(header, target, collapsedClass) {")
        block = app[start:start + 900]
        for needed in ("aria-expanded", "keydown", "'Enter'"):
            assert needed in block, (
                f"_wireDisclosure must set {needed!r}; there was no "
                "aria-expanded anywhere in the web app before this, and "
                "repeating that for new UI is the thing to avoid"
            )

    def test_the_inline_onclick_toggle_is_gone(self):
        """The old bubbles carried behaviour inside an HTML string."""
        app = self._app_js()
        assert "onclick=\"this.parentElement.classList.toggle('expanded')\"" not in app, (
            "inline onclick cannot set aria-expanded and cannot be reached "
            "by keyboard; the listener in _wireDisclosure replaces it"
        )

    def test_vscode_has_the_same_wrapper(self):
        """A capability in one client only is how three shipped half-missing.

        `docs/lessons/parity-harness-must-know-every-client.md` -- the web and
        VSCode transcripts are line-for-line twins, so the wrapper has to land
        in both or they diverge on the next edit.
        """
        vs = self._vscode_js()
        assert "function ensureToolTurn()" in vs, (
            "the VSCode webview needs the same per-turn wrapper as the web app"
        )
        assert "function endToolTurn()" in vs
        assert "querySelector('.tool-turn-body').appendChild(groupEl)" in vs, (
            "VSCode must nest iteration groups into the turn wrapper too"
        )

    def test_vscode_closes_the_turn_on_both_exits(self):
        """endResponse AND error -- a failed turn still has to close."""
        vs = self._vscode_js()
        for case in ("case 'endResponse':", "case 'error':"):
            start = vs.find(case)
            assert start != -1, f"{case} not found in the webview dispatcher"
            assert "endToolTurn();" in vs[start:start + 400], (
                f"{case} must close the tool turn, or an interrupted loop "
                "leaves the strip open for the next turn to append into"
            )

    def test_both_clients_style_the_wrapper(self):
        """Markup with no stylesheet collapses into an always-open list."""
        web_css = (WEB_DIR / "styles.css").read_text(encoding="utf-8")
        vs_css = (
            WEB_DIR.parent.parent
            / "vscode-extension"
            / "media"
            / "webview"
            / "styles.css"
        ).read_text(encoding="utf-8")
        for name, css in (("web", web_css), ("vscode", vs_css)):
            assert ".tool-turn.collapsed .tool-turn-body" in css, (
                f"{name} stylesheet is missing the rule that actually hides a "
                "collapsed turn -- without it the wrapper renders but never "
                "collapses, and the transcript is as noisy as before"
            )

