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
