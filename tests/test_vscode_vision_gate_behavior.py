"""Behavioural fence for the VSCode webview's attach-time vision gate.

Owner decision 8 (2026-09-21, `docs/plan-adr-0007-completion-service.md`
§"Open owner decisions"): VSCode gets web's vision badge + image-attach
warning, mirroring `ppxai/web/app.js`'s `_stageFile` semantics exactly:

  - `modelSupportsVision === false`            -> warn (only a KNOWN-false blocks)
  - `modelSupportsVision === true` / `undefined` / `null` -> allow (unknown must not warn)
  - a non-image attachment is never gated, regardless of vision support

The decision lives in `vscode-extension/media/webview/visionGate.js` as a
pure, DOM-free function (`shouldBlockImageAttach`) precisely so it can be
driven under plain Node without a browser/webview — no esbuild needed,
since the module is already vscode-free, DOM-free, plain JS with a
CommonJS export guard (unlike `schemaGuard.ts`, which needs the extension's
TypeScript compiled first).

`main.js` (the actual webview script) calls this function rather than
re-implementing the condition inline; that wiring is NOT exercised here
(no webview/DOM under pytest) — it is source-fenced instead, in
`tests/test_vscode_vision_badge_wiring.py`.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATE_JS = ROOT / "vscode-extension" / "media" / "webview" / "visionGate.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is required")


def _run_gate(js_path: pathlib.Path, is_image, model_supports_vision) -> bool:
    """Load `js_path` under Node and call `shouldBlockImageAttach` with the
    given arguments, returning the boolean result.

    `model_supports_vision` may be the Python sentinel `...` to mean
    "pass `undefined`" (Python has no `undefined`; JSON would turn a
    missing arg into nothing at all, which is exactly what we want to
    drive here).
    """
    if model_supports_vision is ...:
        vision_arg = "undefined"
    elif model_supports_vision is None:
        vision_arg = "null"
    else:
        vision_arg = "true" if model_supports_vision else "false"
    image_arg = "true" if is_image else "false"
    script = (
        f"const g = require({str(js_path)!r});\n"
        f"process.stdout.write(String(g.shouldBlockImageAttach({image_arg}, {vision_arg})));\n"
    )
    result = subprocess.run(
        [NODE, "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"node failed: {result.stderr}"
    out = result.stdout.strip()
    assert out in ("true", "false"), f"unexpected node output: {out!r} (stderr: {result.stderr})"
    return out == "true"


class TestVisionGateBehavior:
    def test_image_on_known_non_vision_model_is_blocked(self):
        assert _run_gate(GATE_JS, True, False) is True

    def test_image_on_vision_model_is_allowed(self):
        assert _run_gate(GATE_JS, True, True) is False

    def test_image_on_unknown_vision_support_is_allowed(self):
        """`undefined` (field not yet pushed) must NOT block — same
        conservative-allow rule as web's `=== false` check."""
        assert _run_gate(GATE_JS, True, ...) is False

    def test_image_on_null_vision_support_is_allowed(self):
        assert _run_gate(GATE_JS, True, None) is False

    def test_non_image_is_never_blocked_even_on_non_vision_model(self):
        assert _run_gate(GATE_JS, False, False) is False

    def test_non_image_is_never_blocked_on_vision_model(self):
        assert _run_gate(GATE_JS, False, True) is False


class TestMutationVerification:
    """Prove the harness actually exercises the real predicate: a scratch
    copy with the `=== false` narrowing removed must return a DIFFERENT
    (wrong) answer for the `undefined` case, and the harness must catch it.
    """

    def test_mutated_gate_blocks_on_unknown_vision_support(self, tmp_path):
        real_source = GATE_JS.read_text(encoding="utf-8")
        assert "modelSupportsVision === false" in real_source, (
            "expected narrowing changed shape — update this mutation to match"
        )
        mutated_source = real_source.replace(
            "modelSupportsVision === false",
            "modelSupportsVision !== true",
        )
        assert mutated_source != real_source

        mutated_path = tmp_path / "visionGate.mutated.js"
        mutated_path.write_text(mutated_source, encoding="utf-8")

        # Real module: undefined vision support must NOT block.
        assert _run_gate(GATE_JS, True, ...) is False
        # Mutated module: `!== true` DOES block on undefined — the mutation
        # is observable, so a harness that could not see it would be inert.
        assert _run_gate(mutated_path, True, ...) is True
